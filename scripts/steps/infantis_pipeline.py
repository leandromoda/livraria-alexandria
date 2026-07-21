# ============================================================
# PIPELINE PARALELO — LIVROS INFANTIS (até 12 anos)
# Livraria Alexandria
#
# Pipeline INDEPENDENTE, como o de jogos (decisão 2026-07-21).
#
# POR QUE TABELA PRÓPRIA
#   A seção precisa de campos que a tabela `livros` não tem e que não
#   fazem sentido para o catálogo geral: faixa_etaria, idade_min/max e
#   ilustrador (em livro infantil o ilustrador é coautor de fato).
#   Acrescentá-los em `livros` mexeria no pipeline de livros, que está
#   funcional — o mesmo motivo que isolou os jogos.
#
# DIFERENÇA IMPORTANTE EM RELAÇÃO A JOGOS
#   Livro infantil É livro: Google Books e OpenLibrary CATALOGAM esses
#   títulos. Por isso aqui existe um step de ENRIQUECIMENTO por ISBN/título
#   (gratuito, sem LLM) antes do scraper — o que torna este pipeline MUITO
#   mais barato em quota que o de jogos, onde a descrição só vinha via
#   agente finder (WebSearch). O LLM aqui é usado apenas na sinopse.
#
# REUSO (só funções puras — nenhum arquivo do pipeline de livros é alterado):
#   steps.offer_resolver.resolve_offer            (URL afiliada)
#   steps.marketplace_scraper.try_google_books    (descrição + capa)
#   steps.marketplace_scraper.try_open_library    (descrição + capa)
#   steps.marketplace_scraper.scrape_marketplace  (preço/capa no marketplace)
#   core.claude_runner / core.batch_numbering
# ============================================================

import json
import os
import re
import shutil
import sqlite3
import time
import unicodedata
import uuid
from datetime import datetime
from os import urandom
from pathlib import Path

import requests

from core.logger import log


# =========================
# CONFIG
# =========================

BASE_DIR  = os.path.dirname(os.path.dirname(__file__))
DATA_DIR  = os.path.join(BASE_DIR, "data")
SEEDS_DIR = os.path.join(DATA_DIR, "seeds")
BATCH_DIR = os.path.join(DATA_DIR, "batch")
DB_PATH   = os.path.join(DATA_DIR, "books.db")

SEED_PATTERN  = re.compile(r"^\d{3}_infantis_seeds\.json$")
BATCH_PREFIX  = "synopsis_infantis"
PROCESSED_DIR = os.path.join(BATCH_DIR, f"processed_{BATCH_PREFIX}")

BATCH_SIZE          = int(os.environ.get("BATCH_SIZE_SYNOPSIS_INFANTIS", 15))
MAX_LOTES_SYNOPSIS  = int(os.environ.get("INFANTIS_MAX_LOTES_SYNOPSIS", 12))
BATCH_STALE_MINUTES = int(os.environ.get("INFANTIS_BATCH_STALE_MINUTES", 45))
MAX_SCRAPE_ATTEMPTS = int(os.environ.get("INFANTIS_MAX_SCRAPE_ATTEMPTS", 3))

SINOPSE_MIN_CHARS = 400
SCRAPE_DELAY_S    = 3.0
SYN_REJECTS_MAX   = 2

UUID_NAMESPACE_INFANTIS = uuid.UUID("33333333-4444-5555-6666-777777777777")


# =========================
# FAIXAS ETÁRIAS (subcategorias da seção)
# =========================

FAIXAS = {
    "0-2-anos": {
        "label": "0 a 2 anos",
        "min": 0, "max": 2,
        "descricao": "Livros de pano, banho e cartonados para os primeiros contatos.",
    },
    "3-5-anos": {
        "label": "3 a 5 anos",
        "min": 3, "max": 5,
        "descricao": "Livros ilustrados para ler junto, na pré-escola.",
    },
    "6-8-anos": {
        "label": "6 a 8 anos",
        "min": 6, "max": 8,
        "descricao": "Primeiros leitores — texto curto e muita ilustração.",
    },
    "9-12-anos": {
        "label": "9 a 12 anos",
        "min": 9, "max": 12,
        "descricao": "Leitores independentes — capítulos, séries e aventuras.",
    },
}
FAIXA_SLUGS = tuple(FAIXAS.keys())

# Rótulos aceitos no seed -> slug canônico
_FAIXA_ALIASES = {}
for _slug, _f in FAIXAS.items():
    _FAIXA_ALIASES[_slug] = _slug
    _FAIXA_ALIASES[_f["label"].lower()] = _slug
    _FAIXA_ALIASES[_f["label"].lower().replace(" a ", "-")] = _slug


def faixa_slug(valor):
    """Normaliza a faixa do seed (rótulo ou slug) -> slug; None se inválida."""
    if not valor:
        return None
    return _FAIXA_ALIASES.get(str(valor).strip().lower())


def faixa_por_idade(idade):
    """Deriva a faixa a partir de uma idade mínima declarada."""
    try:
        i = int(idade)
    except (TypeError, ValueError):
        return None
    for slug, f in FAIXAS.items():
        if f["min"] <= i <= f["max"]:
            return slug
    return None


# =========================
# DB
# =========================

def get_conn():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=60000")
    return conn


def ensure_schema(conn):
    """Bootstrap-safe. NÃO toca nas tabelas livros nem jogos."""

    conn.execute("""
    CREATE TABLE IF NOT EXISTS livros_infantis (

        id              TEXT PRIMARY KEY,

        titulo          TEXT NOT NULL,
        slug            TEXT,
        autor           TEXT,
        ilustrador      TEXT,               -- coautor de fato no livro infantil
        isbn            TEXT,
        editora         TEXT,
        idioma          TEXT DEFAULT 'PT',
        ano_publicacao  INTEGER,

        -- Segmentação por idade (o eixo da seção)
        faixa_etaria    TEXT NOT NULL,      -- 0-2-anos | 3-5-anos | 6-8-anos | 9-12-anos
        idade_min       INTEGER,
        idade_max       INTEGER,

        -- Oferta / afiliado
        lookup_query    TEXT,
        marketplace     TEXT,
        offer_url       TEXT,
        offer_status    TEXT DEFAULT 'active',
        preco           REAL,
        preco_atual     REAL,

        -- Conteúdo
        imagem_url      TEXT,
        descricao       TEXT,               -- bruto (Google Books/OpenLibrary/scraper)
        sinopse         TEXT,               -- editorial (LLM)

        -- Publicação
        is_publishable   INTEGER DEFAULT 0,
        publish_blockers TEXT,
        supabase_id      TEXT,

        -- Flags de pipeline (0=pendente, 1=feito; sinopse: 3=em fila LLM)
        status_resolve  INTEGER DEFAULT 0,
        status_enrich   INTEGER DEFAULT 0,
        status_scrape   INTEGER DEFAULT 0,
        status_cover    INTEGER DEFAULT 0,
        status_slug     INTEGER DEFAULT 0,
        status_synopsis INTEGER DEFAULT 0,
        status_publish  INTEGER DEFAULT 0,

        syn_rejects     INTEGER DEFAULT 0,
        scrape_attempts INTEGER DEFAULT 0,

        seed_id         TEXT,
        created_at      DATETIME,
        updated_at      DATETIME
    )
    """)

    for col, definition in [
        ("ilustrador",      "TEXT"),
        ("editora",         "TEXT"),
        ("syn_rejects",     "INTEGER DEFAULT 0"),
        ("scrape_attempts", "INTEGER DEFAULT 0"),
    ]:
        try:
            conn.execute(f"ALTER TABLE livros_infantis ADD COLUMN {col} {definition}")
        except sqlite3.OperationalError:
            pass

    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_infantis_slug ON livros_infantis(slug)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_infantis_faixa ON livros_infantis(faixa_etaria)")

    conn.execute("""
    CREATE TABLE IF NOT EXISTS seed_imports (
        filename    TEXT PRIMARY KEY,
        imported_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        inserted    INTEGER DEFAULT 0,
        skipped     INTEGER DEFAULT 0
    )
    """)
    conn.commit()


# =========================
# LOTES ÓRFÃOS (mesma proteção do pipeline de jogos)
# =========================

def purge_stale_inputs(prefix, tag="INFANTIS_RECLAIM"):
    """Remove inputs de lote órfãos de runs mortos; devolve os ainda em voo."""
    import glob as _glob

    vivos, orfaos = [], []
    limite_s = BATCH_STALE_MINUTES * 60
    agora = time.time()

    for path in _glob.glob(os.path.join(BATCH_DIR, f"*_{prefix}_input.json")):
        try:
            idade_s = agora - os.path.getmtime(path)
        except OSError:
            continue
        (orfaos if idade_s > limite_s else vivos).append((path, idade_s))

    for path, idade_s in orfaos:
        try:
            os.remove(path)
            log(f"[{tag}] Lote órfão removido: {os.path.basename(path)} "
                f"(parado há {int(idade_s // 60)} min, sem agente)")
        except OSError as e:
            log(f"[{tag}] AVISO: falha ao remover {os.path.basename(path)}: {e}")

    return [p for p, _ in vivos]


def reclaim_stuck(conn=None):
    own = conn is None
    if own:
        conn = get_conn()
        ensure_schema(conn)

    em_voo = purge_stale_inputs(BATCH_PREFIX)
    n = 0
    if not em_voo:
        cur = conn.execute(
            "UPDATE livros_infantis SET status_synopsis=0, updated_at=CURRENT_TIMESTAMP "
            "WHERE status_synopsis=3"
        )
        n = cur.rowcount
        conn.commit()
        if n:
            log(f"[INFANTIS_RECLAIM] {n} livro(s) recuperado(s) de fila órfã (3->0)")
    else:
        log(f"[INFANTIS_RECLAIM] {len(em_voo)} lote(s) em voo — reclaim adiado.")

    if own:
        conn.close()
    return n


# =========================
# 1. SEEDS
# =========================

def discover_seed_files():
    if not os.path.exists(SEEDS_DIR):
        return []
    files = sorted(f for f in os.listdir(SEEDS_DIR) if SEED_PATTERN.match(f))
    return [(f, os.path.join(SEEDS_DIR, f)) for f in files]


def _load_seeds(filepath):
    """Lê o seed tolerando o que o agente costuma errar: BOM, cerca de
    markdown (```json) e JSONL. O pipeline não pode falhar por formatação."""
    with open(filepath, "r", encoding="utf-8-sig") as f:
        text = f.read().strip()

    if text.startswith("```"):
        linhas = [l for l in text.splitlines() if not l.strip().startswith("```")]
        text = "\n".join(linhas).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return [json.loads(l) for l in text.splitlines() if l.strip()]


def insert_seed(conn, seed, seed_id=None):
    """Retorna (resultado, id): inserted | duplicate | invalid."""
    now = datetime.utcnow().isoformat()

    titulo       = (seed.get("titulo") or "").strip()
    autor        = (seed.get("autor") or "").strip() or None
    ilustrador   = (seed.get("ilustrador") or "").strip() or None
    lookup_query = (seed.get("lookup_query") or "").strip()
    marketplace  = (seed.get("marketplace") or "amazon").strip().lower()

    faixa = faixa_slug(seed.get("faixa_etaria")) or faixa_por_idade(seed.get("idade_min"))
    if not titulo or not lookup_query or not faixa:
        return "invalid", None

    cur = conn.cursor()
    cur.execute("""
        SELECT id FROM livros_infantis
        WHERE LOWER(titulo) = LOWER(?)
          AND LOWER(IFNULL(autor,'')) = LOWER(IFNULL(?, ''))
        LIMIT 1
    """, (titulo, autor))
    if cur.fetchone():
        return "duplicate", None

    f = FAIXAS[faixa]
    livro_id = urandom(12).hex()
    cur.execute("""
        INSERT INTO livros_infantis (
            id, titulo, autor, ilustrador, isbn, editora, idioma, ano_publicacao,
            faixa_etaria, idade_min, idade_max,
            lookup_query, marketplace, offer_status, preco,
            seed_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'PT', ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
    """, (
        livro_id, titulo, autor, ilustrador,
        (seed.get("isbn") or "").strip() or None,
        (seed.get("editora") or "").strip() or None,
        seed.get("ano_publicacao"),
        faixa, f["min"], f["max"],
        lookup_query, marketplace, seed.get("preco"),
        seed_id, now, now,
    ))
    return "inserted", livro_id


def import_seeds():
    """Nome de arquivo repetido NÃO é falha: reprocessa e sobrescreve
    (mesma regra do pipeline de jogos). Dedup real é por item."""
    log("[INFANTIS_SEED] Iniciando importação de seeds")
    conn = get_conn()
    ensure_schema(conn)

    files = discover_seed_files()
    if not files:
        log("[INFANTIS_SEED] Nenhum NNN_infantis_seeds.json em data/seeds/")
        conn.close()
        return 0

    total = 0
    for filename, filepath in files:
        if conn.execute("SELECT 1 FROM seed_imports WHERE filename=?", (filename,)).fetchone():
            log(f"[INFANTIS_SEED] Nome já usado -> {filename} | reprocessando "
                f"(sobrescreve; repetidos caem no dedup)")

        try:
            seeds = _load_seeds(filepath)
        except Exception as e:
            log(f"[INFANTIS_SEED] ERRO ao ler {filename}: {e} — mantido para correção")
            continue

        counts = {"inserted": 0, "duplicate": 0, "invalid": 0, "error": 0}
        for i, seed in enumerate(seeds, 1):
            titulo_log = seed.get("titulo", "?")
            print(f"[INFANTIS_SEED][{i:03d}/{len(seeds):03d}] -> {titulo_log}")
            try:
                result, _ = insert_seed(conn, seed, seed_id=filename)
                counts[result] += 1
            except Exception as e:
                log(f"[INFANTIS_SEED] ERRO -> {titulo_log} | {e}")
                counts["error"] += 1
        conn.commit()

        conn.execute(
            "INSERT OR REPLACE INTO seed_imports (filename, imported_at, inserted, skipped) "
            "VALUES (?, CURRENT_TIMESTAMP, ?, ?)",
            (filename, counts["inserted"], counts["duplicate"] + counts["invalid"]),
        )
        conn.commit()

        ingested = os.path.join(SEEDS_DIR, "ingested_seeds")
        os.makedirs(ingested, exist_ok=True)
        dest = os.path.join(ingested, filename)
        try:
            if os.path.exists(dest):
                os.remove(dest)
            shutil.move(filepath, dest)
        except Exception as e:
            log(f"[INFANTIS_SEED] AVISO: falha ao mover {filename}: {e}")

        total += counts["inserted"]
        log(f"[INFANTIS_SEED] {filename} -> OK: {counts['inserted']} | "
            f"Duplicados: {counts['duplicate']} | Inválidos: {counts['invalid']} | "
            f"Erros: {counts['error']}")

    conn.close()
    log(f"[INFANTIS_SEED] Finalizado | Total inseridos: {total}")
    return total


# =========================
# 2. RESOLVER OFERTAS
# =========================

def resolve_offers(pacote=200):
    from steps.offer_resolver import resolve_offer

    log("[INFANTIS_RESOLVE] Iniciando")
    conn = get_conn()
    ensure_schema(conn)
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT id, titulo, marketplace, lookup_query FROM livros_infantis
        WHERE status_resolve = 0 AND lookup_query IS NOT NULL AND lookup_query != ''
        LIMIT ?
    """, (pacote,)).fetchall()

    ok = falhas = 0
    for i, r in enumerate(rows, 1):
        url = resolve_offer(r["marketplace"], r["lookup_query"])
        if url:
            cur.execute("UPDATE livros_infantis SET offer_url=?, status_resolve=1, "
                        "updated_at=CURRENT_TIMESTAMP WHERE id=?", (url, r["id"]))
            ok += 1
        else:
            cur.execute("UPDATE livros_infantis SET status_resolve=-1, "
                        "updated_at=CURRENT_TIMESTAMP WHERE id=?", (r["id"],))
            falhas += 1
        conn.commit()
        log(f"[INFANTIS_RESOLVE][{i:03d}/{len(rows):03d}] "
            f"{'OK' if url else 'FALHA'} -> {r['titulo']}")

    conn.close()
    log(f"[INFANTIS_RESOLVE] Finalizado | OK: {ok} | Falhas: {falhas}")
    return ok


# =========================
# 3. ENRIQUECER (Google Books / OpenLibrary) — SEM LLM
# =========================

def enrich(pacote=100):
    """Descrição e capa por ISBN/título. É o step que torna esta seção barata:
    livro infantil É livro e está catalogado nessas APIs, então a maior parte
    do conteúdo entra aqui, de graça, sem consumir quota de LLM."""
    from steps.marketplace_scraper import try_google_books, try_open_library

    log("[INFANTIS_ENRICH] Iniciando (Google Books / OpenLibrary)")
    conn = get_conn()
    ensure_schema(conn)
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT id, titulo, autor, isbn FROM livros_infantis
        WHERE status_enrich = 0
        LIMIT ?
    """, (pacote,)).fetchall()

    ok = vazios = 0
    for i, r in enumerate(rows, 1):
        log(f"[INFANTIS_ENRICH][{i:03d}/{len(rows):03d}] -> {r['titulo']}")
        res = None
        try:
            res = try_google_books(r["isbn"], r["titulo"], r["autor"] or "")
            if not (res and res.get("descricao")):
                res = try_open_library(r["titulo"], isbn=r["isbn"], autor=r["autor"]) or res
        except Exception as e:
            log(f"[INFANTIS_ENRICH] ERRO -> {r['titulo']} | {e}")

        desc  = (res or {}).get("descricao")
        cover = (res or {}).get("cover_url")
        if desc or cover:
            cur.execute("""
                UPDATE livros_infantis
                SET descricao   = COALESCE(descricao, ?),
                    imagem_url  = COALESCE(imagem_url, ?),
                    status_enrich = 1,
                    status_cover  = CASE WHEN COALESCE(imagem_url, ?) IS NOT NULL
                                         THEN 1 ELSE status_cover END,
                    syn_rejects = CASE WHEN ? IS NOT NULL THEN 0 ELSE COALESCE(syn_rejects,0) END,
                    updated_at  = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (desc, cover, cover, desc, r["id"]))
            ok += 1
        else:
            cur.execute("UPDATE livros_infantis SET status_enrich=2, "
                        "updated_at=CURRENT_TIMESTAMP WHERE id=?", (r["id"],))
            vazios += 1
        conn.commit()
        time.sleep(0.3)

    conn.close()
    log(f"[INFANTIS_ENRICH] Finalizado | Enriquecidos: {ok} | Sem dado: {vazios}")
    return ok


# =========================
# 4. SCRAPER (preço/capa no marketplace) — fallback
# =========================

def _requeue_scrape_sem_descricao():
    """Requeue com backoff (mesma proteção do pipeline de jogos)."""
    conn = get_conn()
    ensure_schema(conn)
    cur = conn.execute(f"""
        UPDATE livros_infantis
        SET status_scrape   = 0,
            scrape_attempts = COALESCE(scrape_attempts, 0) + 1,
            updated_at      = CURRENT_TIMESTAMP
        WHERE status_scrape != 0
          AND (descricao IS NULL OR TRIM(descricao) = '')
          AND offer_url IS NOT NULL AND offer_url != ''
          AND status_publish = 0
          AND COALESCE(scrape_attempts, 0) < {MAX_SCRAPE_ATTEMPTS}
    """)
    n = cur.rowcount
    conn.commit()
    conn.close()
    if n:
        log(f"[INFANTIS_SCRAPE] {n} re-enfileirado(s) (limite {MAX_SCRAPE_ATTEMPTS})")
    return n


def scrape(pacote=30):
    from steps.marketplace_scraper import scrape_marketplace

    log("[INFANTIS_SCRAPE] Iniciando")
    conn = get_conn()
    ensure_schema(conn)
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT id, titulo, offer_url FROM livros_infantis
        WHERE status_scrape = 0
          AND offer_url IS NOT NULL AND offer_url != ''
        LIMIT ?
    """, (pacote,)).fetchall()

    ok = falhas = 0
    for i, r in enumerate(rows, 1):
        log(f"[INFANTIS_SCRAPE][{i:03d}/{len(rows):03d}] -> {r['titulo']}")
        try:
            res = scrape_marketplace(r["offer_url"])
        except Exception as e:
            res = None
            log(f"[INFANTIS_SCRAPE] ERRO -> {r['titulo']} | {e}")

        if res:
            cur.execute("""
                UPDATE livros_infantis
                SET imagem_url  = COALESCE(imagem_url, ?),
                    descricao   = COALESCE(descricao, ?),
                    preco_atual = COALESCE(?, preco_atual),
                    offer_status = ?,
                    status_scrape = 1,
                    updated_at  = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (res.get("cover_url"), res.get("descricao"), res.get("preco"),
                  "active" if res.get("disponivel", True) else "unavailable", r["id"]))
            ok += 1
        else:
            cur.execute("UPDATE livros_infantis SET status_scrape=2, "
                        "updated_at=CURRENT_TIMESTAMP WHERE id=?", (r["id"],))
            falhas += 1
        conn.commit()
        time.sleep(SCRAPE_DELAY_S)

    conn.close()
    log(f"[INFANTIS_SCRAPE] Finalizado | OK: {ok} | Falhas: {falhas}")
    return ok


# =========================
# 5. SLUGS
# =========================

def _base_slug(text):
    text = unicodedata.normalize("NFKD", text or "")
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    return re.sub(r"\s+", "-", text).strip("-")


def gen_slugs(pacote=500):
    log("[INFANTIS_SLUG] Iniciando")
    conn = get_conn()
    ensure_schema(conn)
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT id, titulo FROM livros_infantis
        WHERE status_slug = 0 OR slug IS NULL OR slug = ''
        LIMIT ?
    """, (pacote,)).fetchall()

    ok = 0
    for r in rows:
        base = _base_slug(r["titulo"]) or f"livro-{r['id'][:12]}"
        slug, n = base, 2
        while cur.execute("SELECT 1 FROM livros_infantis WHERE slug=? AND id!=? LIMIT 1",
                          (slug, r["id"])).fetchone():
            slug = f"{base}-{n}"
            n += 1
        cur.execute("UPDATE livros_infantis SET slug=?, status_slug=1, "
                    "updated_at=CURRENT_TIMESTAMP WHERE id=?", (slug, r["id"]))
        conn.commit()
        ok += 1

    conn.close()
    log(f"[INFANTIS_SLUG] Finalizado | Slugs: {ok}")
    return ok


# =========================
# 6. SINOPSES (batch LLM)
# =========================

def synopsis_export(pacote=None):
    from core.batch_numbering import next_batch_number

    os.makedirs(BATCH_DIR, exist_ok=True)
    os.makedirs(PROCESSED_DIR, exist_ok=True)

    conn = get_conn()
    ensure_schema(conn)
    rows = conn.execute("""
        SELECT id, slug, titulo, autor, ilustrador, faixa_etaria, descricao
        FROM livros_infantis
        WHERE status_synopsis = 0
          AND descricao IS NOT NULL AND TRIM(descricao) != ''
        ORDER BY created_at ASC
        LIMIT ?
    """, (min(pacote or BATCH_SIZE, BATCH_SIZE),)).fetchall()

    if not rows:
        log("[INFANTIS_SYN_EXPORT] Nada pendente (com descrição).")
        conn.close()
        return 0

    livros = [{
        "id":            r["id"],
        "slug":          r["slug"] or "",
        "titulo":        r["titulo"],
        "autor":         r["autor"] or "",
        "ilustrador":    r["ilustrador"] or "",
        "faixa_etaria":  FAIXAS[r["faixa_etaria"]]["label"],
        "descricao":     r["descricao"],
    } for r in rows]

    num = next_batch_number(BATCH_DIR, BATCH_PREFIX)
    path = os.path.join(BATCH_DIR, f"{num}_{BATCH_PREFIX}_input.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"meta": {"exported_at": datetime.utcnow().isoformat(),
                            "batch": num, "total": len(livros)},
                   "livros": livros}, f, ensure_ascii=False, indent=2)

    conn.executemany("UPDATE livros_infantis SET status_synopsis=3, "
                     "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                     [(l["id"],) for l in livros])
    conn.commit()
    conn.close()
    log(f"[INFANTIS_SYN_EXPORT] Exportados: {len(livros)} -> {os.path.basename(path)}")
    return len(livros)


def _valida_sinopse(texto):
    if not texto or not texto.strip():
        return "vazia"
    t = texto.strip()
    if len(t) < SINOPSE_MIN_CHARS:
        return f"curta ({len(t)} < {SINOPSE_MIN_CHARS})"
    if t.startswith("#") or "\n#" in t:
        return "heading markdown"
    for a in ("[SYSTEM]", "[PROCESS]", "[TASK]", "```"):
        if a in t:
            return f"artefato meta: {a}"
    return None


def synopsis_import():
    import glob as _glob

    os.makedirs(PROCESSED_DIR, exist_ok=True)
    outputs = sorted(_glob.glob(os.path.join(BATCH_DIR, f"*_{BATCH_PREFIX}_output.json")))
    if not outputs:
        log("[INFANTIS_SYN_IMPORT] Nenhum output pendente.")
        return 0

    conn = get_conn()
    ensure_schema(conn)
    cur = conn.cursor()
    aprovados = rejeitados = 0

    for path in outputs:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            log(f"[INFANTIS_SYN_IMPORT] ERRO ao ler {os.path.basename(path)}: {e}")
            continue

        for item in data.get("resultados", []):
            lid     = item.get("id")
            sinopse = (item.get("sinopse") or "").strip()
            status  = (item.get("status") or "").upper()
            problema = _valida_sinopse(sinopse) if status == "APPROVED" else (
                item.get("motivo") or "REJECTED pelo agente")

            if status == "APPROVED" and not problema:
                cur.execute("UPDATE livros_infantis SET sinopse=?, status_synopsis=1, "
                            "syn_rejects=0, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                            (sinopse, lid))
                aprovados += 1
            else:
                cur.execute("UPDATE livros_infantis SET status_synopsis=0, "
                            "syn_rejects=COALESCE(syn_rejects,0)+1, "
                            "updated_at=CURRENT_TIMESTAMP WHERE id=?", (lid,))
                rejeitados += 1
                row = cur.execute("SELECT COALESCE(syn_rejects,0) FROM livros_infantis "
                                  "WHERE id=?", (lid,)).fetchone()
                if row and row[0] >= SYN_REJECTS_MAX:
                    # Fonte ruim: descarta a descrição e devolve ao enriquecimento
                    cur.execute("UPDATE livros_infantis SET descricao=NULL, status_enrich=0, "
                                "syn_rejects=0, updated_at=CURRENT_TIMESTAMP WHERE id=?", (lid,))
                    log(f"[INFANTIS_SYN_IMPORT] Rejeitado ({problema}) -> id={lid} | "
                        f"descrição descartada (fonte ruim)")
                else:
                    log(f"[INFANTIS_SYN_IMPORT] Rejeitado ({problema}) -> id={lid}")
        conn.commit()

        dest = os.path.join(PROCESSED_DIR, os.path.basename(path))
        try:
            if os.path.exists(dest):
                os.remove(dest)
            shutil.move(path, dest)
        except Exception as e:
            log(f"[INFANTIS_SYN_IMPORT] AVISO: falha ao arquivar: {e}")

    conn.close()
    log(f"[INFANTIS_SYN_IMPORT] Finalizado | Aprovados: {aprovados} | Rejeitados: {rejeitados}")
    return aprovados


def run_synopsis_batch(max_lotes=None):
    from core.claude_runner import agent_prompt_path, run_agent

    max_lotes = max_lotes or MAX_LOTES_SYNOPSIS
    total = 0
    for _ in range(max_lotes):
        if not synopsis_export():
            break
        ok, out = run_agent(agent_prompt_path("synopsis_infantis_batch"), wait_on_limit=False)
        if not ok:
            log(f"[INFANTIS_SYN] Agente falhou/limite — parando. {out[:200]}")
            reclaim_stuck()
            break
        total += synopsis_import()
    return total


# =========================
# 7. QUALITY GATE
# =========================

def quality_gate():
    log("[INFANTIS_QG] Iniciando")
    conn = get_conn()
    ensure_schema(conn)
    cur = conn.cursor()
    rows = cur.execute("SELECT id, slug, faixa_etaria, sinopse, offer_url "
                       "FROM livros_infantis WHERE status_publish = 0").fetchall()

    aprovados = reprovados = 0
    for r in rows:
        blockers = []
        if not r["slug"]:
            blockers.append("sem_slug")
        if not r["offer_url"]:
            blockers.append("sem_oferta")
        if r["faixa_etaria"] not in FAIXA_SLUGS:
            blockers.append("faixa_invalida")
        if len((r["sinopse"] or "").strip()) < SINOPSE_MIN_CHARS:
            blockers.append("sinopse_ausente_ou_curta")

        pub = 0 if blockers else 1
        cur.execute("UPDATE livros_infantis SET is_publishable=?, publish_blockers=?, "
                    "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (pub, json.dumps(blockers) if blockers else None, r["id"]))
        aprovados += pub
        reprovados += (1 - pub)
    conn.commit()
    conn.close()
    log(f"[INFANTIS_QG] Finalizado | Aprovados: {aprovados} | Bloqueados: {reprovados}")
    return aprovados


# =========================
# 8. PUBLISH (Supabase — tabela livros_infantis)
# =========================

SUPABASE_PAYLOAD_COLUMNS = (
    "id", "titulo", "slug", "autor", "ilustrador", "faixa_etaria",
    "idade_min", "idade_max", "descricao", "imagem_url", "ano_publicacao",
    "preco_atual", "marketplace", "url_afiliada", "offer_status",
    "is_publishable", "created_at", "updated_at",
)
CLICK_COLUMNS = ("livro_infantil_id", "user_agent", "referer", "ip_hash",
                 "utm_source", "utm_medium", "utm_campaign", "session_id")


def _int_or_none(v):
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _float_or_none(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _text_or_none(v):
    if v is None:
        return None
    v = str(v).strip()
    return v or None


def _supabase_creds():
    env_path = Path(BASE_DIR).parent / ".env.local"
    url = key = None
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("NEXT_PUBLIC_SUPABASE_URL="):
                url = line.split("=", 1)[1].strip()
            elif line.startswith("SUPABASE_SERVICE_ROLE_KEY="):
                key = line.split("=", 1)[1].strip()
    return url, key


def _build_payload(r, now):
    sid = r["supabase_id"] or str(uuid.uuid5(UUID_NAMESPACE_INFANTIS, r["id"]))
    return {
        "id":             sid,
        "titulo":         r["titulo"],
        "slug":           r["slug"],
        "autor":          _text_or_none(r["autor"]),
        "ilustrador":     _text_or_none(r["ilustrador"]),
        "faixa_etaria":   r["faixa_etaria"],
        "idade_min":      _int_or_none(r["idade_min"]),
        "idade_max":      _int_or_none(r["idade_max"]),
        "descricao":      _text_or_none(r["sinopse"]),
        "imagem_url":     _text_or_none(r["imagem_url"]),
        "ano_publicacao": _int_or_none(r["ano_publicacao"]),
        "preco_atual":    _float_or_none(r["preco_atual"]) or _float_or_none(r["preco"]),
        "marketplace":    _text_or_none(r["marketplace"]),
        "url_afiliada":   _text_or_none(r["offer_url"]),
        "offer_status":   r["offer_status"] or "active",
        "is_publishable": True,
        "created_at":     r["created_at"] or now,
        "updated_at":     now,
    }


def verify_supabase(verbose=True):
    """Valida o contrato local<->Supabase contra o schema remoto real."""
    url, key = _supabase_creds()
    if not url or not key:
        log("[INFANTIS_VERIFY] ERRO: credenciais ausentes em .env.local")
        return False
    try:
        res = requests.get(f"{url}/rest/v1/",
                           headers={"apikey": key, "Authorization": f"Bearer {key}"},
                           timeout=30)
        defs = res.json().get("definitions", {})
    except Exception as e:
        log(f"[INFANTIS_VERIFY] ERRO ao ler schema remoto: {e}")
        return False

    ok = True
    for table, wanted in (("livros_infantis", SUPABASE_PAYLOAD_COLUMNS),
                          ("livro_infantil_clicks", CLICK_COLUMNS)):
        props = defs.get(table, {}).get("properties")
        if not props:
            log(f"[INFANTIS_VERIFY] [X] Tabela `{table}` AUSENTE — aplicar "
                f"scripts/sql/2026-07-21_secao_infantis.sql no SQL Editor.")
            ok = False
            continue
        faltantes = [c for c in wanted if c not in props]
        if faltantes:
            log(f"[INFANTIS_VERIFY] [X] `{table}`: faltam {', '.join(faltantes)}")
            ok = False
        elif verbose:
            log(f"[INFANTIS_VERIFY] [OK] `{table}`: {len(wanted)} coluna(s) do contrato presentes")
    if ok and verbose:
        log("[INFANTIS_VERIFY] Contrato local<->Supabase compatível.")
    return ok


def publish(pacote=200):
    log("[INFANTIS_PUBLISH] Iniciando")
    url, key = _supabase_creds()
    if not url or not key:
        log("[INFANTIS_PUBLISH] ERRO: credenciais ausentes em .env.local")
        return 0

    headers = {"apikey": key, "Authorization": f"Bearer {key}",
               "Content-Type": "application/json",
               "Prefer": "resolution=merge-duplicates,return=representation"}
    table_url = f"{url}/rest/v1/livros_infantis?on_conflict=slug"

    conn = get_conn()
    ensure_schema(conn)
    cur = conn.cursor()
    rows = cur.execute("SELECT * FROM livros_infantis "
                       "WHERE status_publish = 0 AND is_publishable = 1 LIMIT ?",
                       (pacote,)).fetchall()
    if not rows:
        log("[INFANTIS_PUBLISH] Nada publicável pendente.")
        conn.close()
        return 0

    ok = falhas = 0
    now = datetime.utcnow().isoformat()
    for i, r in enumerate(rows, 1):
        payload = _build_payload(r, now)
        try:
            res = requests.post(table_url, headers=headers, json=payload, timeout=60)
            if res.status_code in (200, 201, 409):
                cur.execute("UPDATE livros_infantis SET status_publish=1, supabase_id=?, "
                            "updated_at=CURRENT_TIMESTAMP WHERE id=?", (payload["id"], r["id"]))
                conn.commit()
                ok += 1
                log(f"[INFANTIS_PUBLISH][{i:03d}/{len(rows):03d}] OK -> {r['titulo']}")
            else:
                falhas += 1
                log(f"[INFANTIS_PUBLISH] ERRO {res.status_code} -> {r['titulo']} | {res.text[:200]}")
                if res.status_code == 404:
                    log("[INFANTIS_PUBLISH] Tabela ausente — aplicar "
                        "scripts/sql/2026-07-21_secao_infantis.sql e re-rodar.")
                    break
        except Exception as e:
            falhas += 1
            log(f"[INFANTIS_PUBLISH] ERRO -> {r['titulo']} | {e}")

    conn.close()
    log(f"[INFANTIS_PUBLISH] Finalizado | OK: {ok} | Falhas: {falhas}")
    return ok


# =========================
# STATUS
# =========================

def status():
    conn = get_conn()
    ensure_schema(conn)
    cur = conn.cursor()
    q = lambda s: cur.execute(s).fetchone()[0]  # noqa: E731

    print("\n=== LIVROS INFANTIS - PIPELINE PARALELO ===")
    print(f"Total:                 {q('SELECT COUNT(*) FROM livros_infantis')}")
    for slug in FAIXA_SLUGS:
        tot = cur.execute("SELECT COUNT(*) FROM livros_infantis WHERE faixa_etaria=?",
                          (slug,)).fetchone()[0]
        pub = cur.execute("SELECT COUNT(*) FROM livros_infantis "
                          "WHERE faixa_etaria=? AND status_publish=1", (slug,)).fetchone()[0]
        print(f"  {FAIXAS[slug]['label']:<14} total={tot:<5} publicados={pub}")
    com_descricao = q("SELECT COUNT(*) FROM livros_infantis "
                      "WHERE descricao IS NOT NULL AND TRIM(descricao) != ''")
    print(f"Com oferta:            {q('SELECT COUNT(*) FROM livros_infantis WHERE offer_url IS NOT NULL')}")
    print(f"Com descrição:         {com_descricao}")
    print(f"Sinopse ok:            {q('SELECT COUNT(*) FROM livros_infantis WHERE status_synopsis=1')}")
    print(f"Publicáveis (QG):      {q('SELECT COUNT(*) FROM livros_infantis WHERE is_publishable=1')}")
    print(f"Publicados:            {q('SELECT COUNT(*) FROM livros_infantis WHERE status_publish=1')}")
    print()
    conn.close()


# =========================
# AUTOPILOT (opção I)
# =========================

def _synopsis_backlog(conn=None):
    own = conn is None
    if own:
        conn = get_conn()
        ensure_schema(conn)
    n = conn.execute("""
        SELECT COUNT(*) FROM livros_infantis
        WHERE status_synopsis != 1
          AND descricao IS NOT NULL AND TRIM(descricao) != ''
          AND status_publish = 0
    """).fetchone()[0]
    if own:
        conn.close()
    return n


def _sem_descricao(conn=None):
    own = conn is None
    if own:
        conn = get_conn()
        ensure_schema(conn)
    n = conn.execute("""
        SELECT COUNT(*) FROM livros_infantis
        WHERE (descricao IS NULL OR TRIM(descricao) = '') AND status_publish = 0
    """).fetchone()[0]
    if own:
        conn.close()
    return n


def _drain_non_llm():
    """Tudo que não custa quota: seeds -> ofertas -> enrich (APIs de livro)
    -> scraper -> slugs."""
    import_seeds()
    while resolve_offers(200):
        pass
    while enrich(100):
        pass
    while scrape(30):
        pass
    gen_slugs()


def autopilot_i():
    """Opção I — autopilot de Livros Infantis, no modelo do G/J:
    passe não-LLM + fase LLM (só sinopse); com backlog e quota esgotada,
    entra em loop multijanela até drenar, com guard anti-giro."""
    from core.claude_runner import claude_available
    from core.claude_usage_tracker import session_window

    log("[I] Autopilot Livros Infantis (modelo G) - passe único + loop multijanela")
    verify_supabase(verbose=False)

    reclaim_stuck()
    _requeue_scrape_sem_descricao()
    _drain_non_llm()

    if claude_available():
        run_synopsis_batch()
    else:
        log("[I] claude CLI indisponível — sinopses ficam pendentes.")
    quality_gate()
    publish()

    backlog = _synopsis_backlog()
    if backlog <= 0:
        sem_desc = _sem_descricao()
        if sem_desc:
            log(f"[I] 0 sinopses geráveis — {sem_desc} livro(s) sem descrição "
                f"(nem Google Books nem OpenLibrary tinham dado).")
        else:
            log("[I] Backlog de conteúdo zerado no primeiro passe.")
    elif not claude_available():
        log(f"[I] {backlog} sinopse(s) pendente(s), claude CLI indisponível.")
    else:
        log(f"[I] Backlog de sinopses: {backlog} - entrando em loop multijanela.")
        try:
            while True:
                while True:
                    _drain_non_llm()
                    quality_gate()
                    publish()
                    w = session_window()
                    if not w.get("in_cooldown"):
                        break
                    secs = max(0, int(w.get("seconds_until_reset", 0)))
                    nap = min(300, secs)
                    if nap <= 0:
                        break
                    log(f"[I] Não-LLM drenado; aguardando reset (~{secs // 60} min)…")
                    time.sleep(nap)

                if session_window().get("in_cooldown"):
                    log("[I] Sessão ainda em cooldown — encerrando loop.")
                    break

                antes = _synopsis_backlog()
                if antes <= 0:
                    log("[I] Backlog zerado — loop concluído.")
                    break

                log(f"[I] -- Janela LLM (quota restaurada) - backlog: {antes} --")
                run_synopsis_batch()
                quality_gate()
                publish()

                depois = _synopsis_backlog()
                if depois >= antes:
                    log(f"[I] Janela sem progresso ({antes}->{depois}) — encerrando.")
                    break
        except KeyboardInterrupt:
            log("[I] Loop interrompido pelo usuário.")

    status()
    log("[I] Passe concluído.")


# Alias para simetria com o pipeline de jogos
autopilot = autopilot_i
