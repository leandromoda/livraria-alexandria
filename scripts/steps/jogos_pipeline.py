# ============================================================
# PIPELINE PARALELO — JOGOS (Seção Jogos)
# Livraria Alexandria
#
# Pipeline INDEPENDENTE do pipeline de livros, por decisão de
# arquitetura (2026-07-14): jogos (RPG de mesa, tabuleiro, cartas)
# não são análogos a livros — enrich/covers/dedup/review/listas/
# auditorias de livros produziriam dados errados ou despublicação
# indevida. Isolamento por construção:
#
#   - Tabela própria `jogos` (mesmo books.db — coberto pelo backup)
#   - Seeds próprios: NNN_jogos_seeds.json (padrão distinto do offer_seed)
#   - Lotes LLM próprios: NNN_synopsis_jogos_input/output.json
#     (agente agents/synopsis_jogos_batch — glob distinto do de livros)
#   - Publicação em tabela Supabase própria `jogos`
#     (migração: scripts/sql/2026-07-14_secao_jogos.sql)
#
# REUSO (só funções puras — nenhum arquivo de livros é modificado):
#   - steps.offer_resolver.resolve_offer      (montagem de URL afiliada)
#   - steps.marketplace_scraper.scrape_marketplace (capa/descrição/preço)
#   - core.claude_runner.run_agent            (sinopses via claude CLI)
#
# NÃO existe aqui (de propósito): enrich via Google Books, capas via
# APIs de livro, dedup contra livros, review is_book, categorize LLM,
# listas "Melhores livros de…", páginas de autor para designers.
# ============================================================

import json
import os
import re
import shutil
import time
import unicodedata
import uuid
import sqlite3
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

SEED_PATTERN  = re.compile(r"^\d{3}_jogos_seeds\.json$")
BATCH_PREFIX  = "synopsis_jogos"   # NNN_synopsis_jogos_input.json
PROCESSED_DIR = os.path.join(BATCH_DIR, f"processed_{BATCH_PREFIX}")

BATCH_SIZE = int(os.environ.get("BATCH_SIZE_SYNOPSIS_JOGOS", 15))

SINOPSE_MIN_CHARS = 400
SCRAPE_DELAY_S    = 3.0

# UUID namespace próprio (distinto do de livros) — publicação determinística
UUID_NAMESPACE_JOGOS = uuid.UUID("22222222-3333-4444-5555-666666666666")

# Categorias fixas da Seção Jogos. Seeds usam o rótulo; o banco guarda o slug.
CATEGORIA_LABEL_TO_SLUG = {
    "rpg":                "rpg",
    "jogos de tabuleiro": "jogos-de-tabuleiro",
    "jogos de cartas":    "jogos-de-cartas",
}
CATEGORIA_SLUGS  = frozenset(CATEGORIA_LABEL_TO_SLUG.values())
CATEGORIA_LABELS = {
    "rpg":                "RPG",
    "jogos-de-tabuleiro": "Jogos de Tabuleiro",
    "jogos-de-cartas":    "Jogos de Cartas",
}


def categoria_slug(valor):
    """Normaliza categoria de seed (rótulo ou slug) -> slug; None se inválida."""
    if not valor:
        return None
    v = valor.strip().lower()
    if v in CATEGORIA_SLUGS:
        return v
    return CATEGORIA_LABEL_TO_SLUG.get(v)


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
    """Bootstrap-safe: cria a tabela jogos do zero. NÃO toca na tabela livros."""

    conn.execute("""
    CREATE TABLE IF NOT EXISTS jogos (

        id              TEXT PRIMARY KEY,

        titulo          TEXT NOT NULL,
        slug            TEXT,
        autor           TEXT,               -- designer / autor de RPG
        categoria       TEXT NOT NULL,      -- rpg | jogos-de-tabuleiro | jogos-de-cartas
        idioma          TEXT DEFAULT 'PT',
        ano_lancamento  INTEGER,

        -- Oferta / afiliado (offer-first: 1 oferta por jogo)
        lookup_query    TEXT,
        marketplace     TEXT,
        offer_url       TEXT,
        offer_status    TEXT DEFAULT 'active',
        preco           REAL,
        preco_atual     REAL,

        -- Conteúdo
        imagem_url      TEXT,
        descricao       TEXT,               -- bruto (scraper)
        sinopse         TEXT,               -- editorial (LLM)

        -- Publicação
        is_publishable  INTEGER DEFAULT 0,
        publish_blockers TEXT,
        supabase_id     TEXT,

        -- Flags de pipeline (0=pendente, 1=feito; sinopse: 3=em fila LLM)
        status_resolve  INTEGER DEFAULT 0,
        status_scrape   INTEGER DEFAULT 0,
        status_slug     INTEGER DEFAULT 0,
        status_synopsis INTEGER DEFAULT 0,
        status_publish  INTEGER DEFAULT 0,

        seed_id         TEXT,
        created_at      DATETIME,
        updated_at      DATETIME
    )
    """)

    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_jogos_slug ON jogos(slug)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jogos_categoria ON jogos(categoria)")

    # Ledger de seeds já importados (compartilhado com livros por ser só um
    # registro de filenames — os padrões de nome nunca colidem).
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
# 1. SEEDS
# =========================

def discover_seed_files():
    if not os.path.exists(SEEDS_DIR):
        return []
    files = sorted(f for f in os.listdir(SEEDS_DIR) if SEED_PATTERN.match(f))
    return [(f, os.path.join(SEEDS_DIR, f)) for f in files]


def _load_seeds(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        text = f.read().strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return [json.loads(l) for l in text.splitlines() if l.strip()]


def insert_seed(conn, seed, seed_id=None):
    """Retorna (resultado, jogo_id): inserted | duplicate | invalid."""
    now = datetime.utcnow().isoformat()

    titulo       = (seed.get("titulo") or "").strip()
    autor        = (seed.get("autor") or "").strip() or None
    lookup_query = (seed.get("lookup_query") or "").strip()
    cat_slug     = categoria_slug(seed.get("categoria"))
    marketplace  = (seed.get("marketplace") or "amazon").strip().lower()
    ano          = seed.get("ano_lancamento") or seed.get("ano_sorteado")

    if not titulo or not lookup_query or not cat_slug:
        return "invalid", None

    cur = conn.cursor()
    cur.execute("""
        SELECT id FROM jogos
        WHERE LOWER(titulo) = LOWER(?)
          AND LOWER(IFNULL(autor,'')) = LOWER(IFNULL(?, ''))
        LIMIT 1
    """, (titulo, autor))
    if cur.fetchone():
        return "duplicate", None

    jogo_id = urandom(12).hex()
    cur.execute("""
        INSERT INTO jogos (
            id, titulo, autor, categoria, idioma, ano_lancamento,
            lookup_query, marketplace, offer_status,
            preco, seed_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'PT', ?, ?, ?, 'active', ?, ?, ?, ?)
    """, (
        jogo_id, titulo, autor, cat_slug, ano,
        lookup_query, marketplace,
        seed.get("preco"), seed_id, now, now,
    ))

    return "inserted", jogo_id


def import_seeds():
    """Step 1 — importa NNN_jogos_seeds.json e move para ingested_seeds/."""
    log("[JOGOS_SEED] Iniciando importação de seeds de jogos")
    conn = get_conn()
    ensure_schema(conn)

    files = discover_seed_files()
    if not files:
        log("[JOGOS_SEED] Nenhum arquivo NNN_jogos_seeds.json em data/seeds/")
        conn.close()
        return 0

    total_inserted = 0
    for filename, filepath in files:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM seed_imports WHERE filename = ?", (filename,))
        if cur.fetchone():
            log(f"[JOGOS_SEED] Já importado -> {filename}")
            continue

        try:
            seeds = _load_seeds(filepath)
        except Exception as e:
            log(f"[JOGOS_SEED] ERRO ao ler {filename}: {e} — arquivo mantido para correção")
            continue

        counts = {"inserted": 0, "duplicate": 0, "invalid": 0, "error": 0}
        for i, seed in enumerate(seeds, 1):
            titulo_log = seed.get("titulo", "?")
            print(f"[JOGOS_SEED][{i:03d}/{len(seeds):03d}] -> {titulo_log}")
            try:
                result, _ = insert_seed(conn, seed, seed_id=filename)
                counts[result] += 1
            except Exception as e:
                log(f"[JOGOS_SEED] ERRO -> {titulo_log} | {e}")
                counts["error"] += 1
        conn.commit()

        skipped = counts["duplicate"] + counts["invalid"]
        conn.execute(
            "INSERT OR REPLACE INTO seed_imports (filename, imported_at, inserted, skipped) "
            "VALUES (?, CURRENT_TIMESTAMP, ?, ?)",
            (filename, counts["inserted"], skipped),
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
            log(f"[JOGOS_SEED] AVISO: falha ao mover {filename}: {e}")

        total_inserted += counts["inserted"]
        log(f"[JOGOS_SEED] {filename} -> OK: {counts['inserted']} | "
            f"Duplicados: {counts['duplicate']} | Inválidos: {counts['invalid']} | "
            f"Erros: {counts['error']}")

    conn.close()
    log(f"[JOGOS_SEED] Finalizado | Total inseridos: {total_inserted}")
    return total_inserted


# =========================
# 2. RESOLVER OFERTAS
# =========================

def resolve_offers(pacote=100):
    """Step 2 — monta offer_url afiliada a partir de lookup_query (função pura
    reutilizada do offer_resolver de livros; nada é modificado lá)."""
    from steps.offer_resolver import resolve_offer  # puro: (marketplace, query) -> url

    log("[JOGOS_RESOLVE] Iniciando")
    conn = get_conn()
    ensure_schema(conn)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, titulo, marketplace, lookup_query FROM jogos
        WHERE status_resolve = 0 AND lookup_query IS NOT NULL AND lookup_query != ''
        LIMIT ?
    """, (pacote,))
    rows = cur.fetchall()

    ok = falhas = 0
    for i, r in enumerate(rows, 1):
        url = resolve_offer(r["marketplace"], r["lookup_query"])
        if url:
            cur.execute(
                "UPDATE jogos SET offer_url=?, status_resolve=1, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (url, r["id"]),
            )
            ok += 1
            log(f"[JOGOS_RESOLVE][{i:03d}/{len(rows):03d}] OK -> {r['titulo']}")
        else:
            cur.execute(
                "UPDATE jogos SET status_resolve=-1, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (r["id"],),
            )
            falhas += 1
            log(f"[JOGOS_RESOLVE][{i:03d}/{len(rows):03d}] FALHA -> {r['titulo']}")
        conn.commit()

    conn.close()
    log(f"[JOGOS_RESOLVE] Finalizado | OK: {ok} | Falhas: {falhas}")
    return ok


# =========================
# 3. SCRAPER (capa + descrição + preço)
# =========================

def scrape(pacote=30):
    """Step 3 — extrai imagem/descrição/preço da página do marketplace.
    ÚNICA fonte de capa e descrição para jogos (sem Google Books/OpenLibrary,
    que só catalogam livros e devolveriam dados de obra homônima)."""
    from steps.marketplace_scraper import scrape_marketplace  # puro: url -> dict

    log("[JOGOS_SCRAPE] Iniciando")
    conn = get_conn()
    ensure_schema(conn)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, titulo, offer_url FROM jogos
        WHERE status_scrape = 0
          AND offer_url IS NOT NULL AND offer_url != ''
        LIMIT ?
    """, (pacote,))
    rows = cur.fetchall()

    ok = falhas = 0
    for i, r in enumerate(rows, 1):
        log(f"[JOGOS_SCRAPE][{i:03d}/{len(rows):03d}] -> {r['titulo']}")
        try:
            result = scrape_marketplace(r["offer_url"])
        except Exception as e:
            result = None
            log(f"[JOGOS_SCRAPE] ERRO -> {r['titulo']} | {e}")

        if result:
            offer_status = "active" if result.get("disponivel", True) else "unavailable"
            cur.execute("""
                UPDATE jogos
                SET imagem_url  = COALESCE(?, imagem_url),
                    descricao   = COALESCE(?, descricao),
                    preco_atual = COALESCE(?, preco_atual),
                    offer_status = ?,
                    status_scrape = 1,
                    updated_at  = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (result.get("cover_url"), result.get("descricao"),
                  result.get("preco"), offer_status, r["id"]))
            ok += 1
        else:
            cur.execute(
                "UPDATE jogos SET status_scrape=2, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (r["id"],),
            )
            falhas += 1
        conn.commit()
        time.sleep(SCRAPE_DELAY_S)

    conn.close()
    log(f"[JOGOS_SCRAPE] Finalizado | OK: {ok} | Falhas: {falhas}")
    return ok


# =========================
# 4. SLUGS
# =========================

def _base_slug(text):
    text = unicodedata.normalize("NFKD", text or "")
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text)
    return text.strip("-")


def gen_slugs(pacote=500):
    """Step 4 — slugs únicos DENTRO da tabela jogos (namespace /jogos/ é
    independente de /livros/, então não há colisão entre domínios)."""
    log("[JOGOS_SLUG] Iniciando")
    conn = get_conn()
    ensure_schema(conn)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, titulo FROM jogos
        WHERE status_slug = 0 OR slug IS NULL OR slug = ''
        LIMIT ?
    """, (pacote,))
    rows = cur.fetchall()

    ok = 0
    for r in rows:
        base = _base_slug(r["titulo"]) or f"jogo-{r['id'][:12]}"
        slug, n = base, 2
        while True:
            cur.execute("SELECT 1 FROM jogos WHERE slug = ? AND id != ? LIMIT 1", (slug, r["id"]))
            if not cur.fetchone():
                break
            slug = f"{base}-{n}"
            n += 1
        cur.execute(
            "UPDATE jogos SET slug=?, status_slug=1, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (slug, r["id"]),
        )
        conn.commit()
        ok += 1
        log(f"[JOGOS_SLUG] -> {r['titulo']} | {slug}")

    conn.close()
    log(f"[JOGOS_SLUG] Finalizado | Slugs gerados: {ok}")
    return ok


# =========================
# 5. SINOPSES (batch LLM — claude CLI)
# =========================

def reclaim_stuck(conn=None):
    """Recupera jogos presos em status_synopsis=3 sem lote em voo (órfãos de
    fila — export feito mas agente nunca gerou output)."""
    own = conn is None
    if own:
        conn = get_conn()
        ensure_schema(conn)
    import glob as _glob
    in_flight = _glob.glob(os.path.join(BATCH_DIR, f"*_{BATCH_PREFIX}_input.json"))
    n = 0
    if not in_flight:
        cur = conn.execute(
            "UPDATE jogos SET status_synopsis=0, updated_at=CURRENT_TIMESTAMP WHERE status_synopsis=3"
        )
        n = cur.rowcount
        conn.commit()
        if n:
            log(f"[JOGOS_RECLAIM] {n} jogo(s) recuperado(s) de fila órfã (status 3->0)")
    if own:
        conn.close()
    return n


def synopsis_export(pacote=None):
    """Exporta lote NNN_synopsis_jogos_input.json para o agente."""
    from core.batch_numbering import next_batch_number

    os.makedirs(BATCH_DIR, exist_ok=True)
    os.makedirs(PROCESSED_DIR, exist_ok=True)

    conn = get_conn()
    ensure_schema(conn)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, slug, titulo, autor, categoria, descricao FROM jogos
        WHERE status_synopsis = 0
          AND descricao IS NOT NULL AND TRIM(descricao) != ''
        ORDER BY created_at ASC
        LIMIT ?
    """, (min(pacote or BATCH_SIZE, BATCH_SIZE),))
    rows = cur.fetchall()

    if not rows:
        log("[JOGOS_SYN_EXPORT] Nada pendente (com descrição).")
        conn.close()
        return 0

    jogos = [{
        "id":        r["id"],
        "slug":      r["slug"] or "",
        "titulo":    r["titulo"],
        "autor":     r["autor"] or "",
        "categoria": CATEGORIA_LABELS.get(r["categoria"], r["categoria"]),
        "descricao": r["descricao"],
    } for r in rows]

    num = next_batch_number(BATCH_DIR, BATCH_PREFIX)
    path = os.path.join(BATCH_DIR, f"{num}_{BATCH_PREFIX}_input.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "meta": {"exported_at": datetime.utcnow().isoformat(), "batch": num,
                     "total": len(jogos)},
            "jogos": jogos,
        }, f, ensure_ascii=False, indent=2)

    cur.executemany(
        "UPDATE jogos SET status_synopsis=3, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        [(j["id"],) for j in jogos],
    )
    conn.commit()
    conn.close()
    log(f"[JOGOS_SYN_EXPORT] Exportados: {len(jogos)} -> {os.path.basename(path)}")
    return len(jogos)


def _valida_sinopse(texto):
    """Validação determinística da sinopse de jogo."""
    if not texto or not texto.strip():
        return "vazia"
    t = texto.strip()
    if len(t) < SINOPSE_MIN_CHARS:
        return f"curta ({len(t)} < {SINOPSE_MIN_CHARS} chars)"
    if t.startswith("#") or "\n#" in t:
        return "contem heading markdown"
    for artefato in ("[SYSTEM]", "[PROCESS]", "[TASK]", "```"):
        if artefato in t:
            return f"artefato meta: {artefato}"
    return None


def synopsis_import():
    """Importa NNN_synopsis_jogos_output.json -> sinopse + status_synopsis=1.
    REJECTED/inválida -> status_synopsis=0 (volta à fila)."""
    import glob as _glob

    os.makedirs(PROCESSED_DIR, exist_ok=True)
    outputs = sorted(_glob.glob(os.path.join(BATCH_DIR, f"*_{BATCH_PREFIX}_output.json")))
    if not outputs:
        log("[JOGOS_SYN_IMPORT] Nenhum output pendente.")
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
            log(f"[JOGOS_SYN_IMPORT] ERRO ao ler {os.path.basename(path)}: {e}")
            continue

        for item in data.get("resultados", []):
            jogo_id = item.get("id")
            sinopse = (item.get("sinopse") or "").strip()
            status  = (item.get("status") or "").upper()

            problema = _valida_sinopse(sinopse) if status == "APPROVED" else (
                item.get("motivo") or "REJECTED pelo agente"
            )

            if status == "APPROVED" and not problema:
                cur.execute("""
                    UPDATE jogos SET sinopse=?, status_synopsis=1,
                           updated_at=CURRENT_TIMESTAMP WHERE id=?
                """, (sinopse, jogo_id))
                aprovados += 1
            else:
                cur.execute("""
                    UPDATE jogos SET status_synopsis=0,
                           updated_at=CURRENT_TIMESTAMP WHERE id=?
                """, (jogo_id,))
                rejeitados += 1
                log(f"[JOGOS_SYN_IMPORT] Rejeitado ({problema}) -> id={jogo_id}")
        conn.commit()

        dest = os.path.join(PROCESSED_DIR, os.path.basename(path))
        try:
            if os.path.exists(dest):
                os.remove(dest)
            shutil.move(path, dest)
        except Exception as e:
            log(f"[JOGOS_SYN_IMPORT] AVISO: falha ao arquivar {os.path.basename(path)}: {e}")

    conn.close()
    log(f"[JOGOS_SYN_IMPORT] Finalizado | Aprovados: {aprovados} | Rejeitados: {rejeitados}")
    return aprovados


def run_synopsis_batch(max_lotes=10):
    """Ciclo LLM completo: export -> agente (claude CLI) -> import, até drenar
    as pendências, esgotar max_lotes ou o agente falhar (limite de sessão)."""
    from core.claude_runner import agent_prompt_path, run_agent

    total = 0
    for _ in range(max_lotes):
        exportados = synopsis_export()
        if not exportados:
            break
        ok, out = run_agent(agent_prompt_path("synopsis_jogos_batch"), wait_on_limit=False)
        if not ok:
            log(f"[JOGOS_SYN] Agente falhou/limite de sessão — parando ciclo LLM. {out[:200]}")
            reclaim_stuck()
            break
        total += synopsis_import()
    return total


# =========================
# 6. QUALITY GATE
# =========================

def quality_gate():
    """Reavalia todos os não publicados: define is_publishable + blockers."""
    log("[JOGOS_QG] Iniciando")
    conn = get_conn()
    ensure_schema(conn)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, titulo, slug, categoria, sinopse, offer_url FROM jogos
        WHERE status_publish = 0
    """)
    rows = cur.fetchall()

    aprovados = reprovados = 0
    for r in rows:
        blockers = []
        if not r["slug"]:
            blockers.append("sem_slug")
        if not r["offer_url"]:
            blockers.append("sem_oferta")
        if r["categoria"] not in CATEGORIA_SLUGS:
            blockers.append("categoria_invalida")
        sinopse = (r["sinopse"] or "").strip()
        if len(sinopse) < SINOPSE_MIN_CHARS:
            blockers.append("sinopse_ausente_ou_curta")

        publishable = 0 if blockers else 1
        cur.execute("""
            UPDATE jogos SET is_publishable=?, publish_blockers=?,
                   updated_at=CURRENT_TIMESTAMP WHERE id=?
        """, (publishable, json.dumps(blockers) if blockers else None, r["id"]))
        if publishable:
            aprovados += 1
        else:
            reprovados += 1
    conn.commit()
    conn.close()
    log(f"[JOGOS_QG] Finalizado | Aprovados: {aprovados} | Bloqueados: {reprovados}")
    return aprovados


# =========================
# 7. PUBLISH (Supabase — tabela jogos)
# =========================

# Contrato de publicação — FONTE ÚNICA dos campos enviados ao Supabase.
# Mapeamento local (SQLite jogos) -> remoto (Supabase jogos):
#   ano_lancamento -> ano_publicacao | offer_url -> url_afiliada
#   sinopse -> descricao (convenção do site, igual a livros)
#   preco_atual -> preco_atual (fallback: preco do seed)
# Colunas SÓ locais (nunca enviadas): lookup_query, preco, sinopse,
#   status_*, publish_blockers, seed_id, idioma.
# verify_supabase() valida este contrato contra o schema remoto real.
SUPABASE_PAYLOAD_COLUMNS = (
    "id", "titulo", "slug", "autor", "categoria", "descricao",
    "imagem_url", "ano_publicacao", "preco_atual", "marketplace",
    "url_afiliada", "offer_status", "is_publishable",
    "created_at", "updated_at",
)

# Colunas inseridas pela rota /api/click-jogo/[id] em jogo_clicks
CLICK_COLUMNS = (
    "jogo_id", "user_agent", "referer", "ip_hash",
    "utm_source", "utm_medium", "utm_campaign", "session_id",
)


def _int_or_none(v):
    """Coerção defensiva: '' e strings numéricas do seed viram int/None —
    string vazia num campo integer do PostgREST retorna 400 (bug conhecido
    do publish de livros, sessão 18)."""
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


def _build_payload(r, now):
    """Monta o payload de upsert a partir de uma row local. As chaves são
    EXATAMENTE SUPABASE_PAYLOAD_COLUMNS (validadas por teste)."""
    supabase_id = r["supabase_id"] or str(uuid.uuid5(UUID_NAMESPACE_JOGOS, r["id"]))
    return {
        "id":             supabase_id,
        "titulo":         r["titulo"],
        "slug":           r["slug"],
        "autor":          _text_or_none(r["autor"]),
        "categoria":      r["categoria"],
        # Convenção do site (igual a livros): descricao publicada = sinopse editorial
        "descricao":      _text_or_none(r["sinopse"]),
        "imagem_url":     _text_or_none(r["imagem_url"]),
        "ano_publicacao": _int_or_none(r["ano_lancamento"]),
        "preco_atual":    _float_or_none(r["preco_atual"]) or _float_or_none(r["preco"]),
        "marketplace":    _text_or_none(r["marketplace"]),
        "url_afiliada":   _text_or_none(r["offer_url"]),
        "offer_status":   r["offer_status"] or "active",
        "is_publishable": True,
        "created_at":     r["created_at"] or now,
        "updated_at":     now,
    }


def verify_supabase(verbose=True):
    """Valida o contrato local<->Supabase contra o schema remoto REAL (OpenAPI
    do PostgREST): toda coluna do payload precisa existir em `jogos`, e toda
    coluna gravada pela rota de click precisa existir em `jogo_clicks`.

    Retorna True se compatível; False se tabela ausente (migração pendente,
    TASK-JOGOS-001) ou se houver coluna faltante (drift de schema)."""
    url, key = _supabase_creds()
    if not url or not key:
        log("[JOGOS_VERIFY] ERRO: credenciais Supabase ausentes em .env.local")
        return False

    try:
        res = requests.get(
            f"{url}/rest/v1/",
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
            timeout=30,
        )
        defs = res.json().get("definitions", {})
    except Exception as e:
        log(f"[JOGOS_VERIFY] ERRO ao ler schema remoto: {e}")
        return False

    ok = True
    for table, wanted in (("jogos", SUPABASE_PAYLOAD_COLUMNS),
                          ("jogo_clicks", CLICK_COLUMNS)):
        props = defs.get(table, {}).get("properties")
        if not props:
            log(f"[JOGOS_VERIFY] [X] Tabela `{table}` AUSENTE no Supabase — aplicar "
                f"scripts/sql/2026-07-14_secao_jogos.sql no SQL Editor (TASK-JOGOS-001).")
            ok = False
            continue

        remote = set(props.keys())
        faltantes = [c for c in wanted if c not in remote]
        if faltantes:
            log(f"[JOGOS_VERIFY] [X] `{table}`: colunas do contrato AUSENTES no remoto "
                f"(publicação retornaria 400 PGRST204): {', '.join(faltantes)}")
            ok = False
        elif verbose:
            extras = sorted(remote - set(wanted))
            log(f"[JOGOS_VERIFY] [OK] `{table}`: {len(wanted)} coluna(s) do contrato "
                f"presentes no remoto"
                + (f" (remoto tem ainda: {', '.join(extras)})" if extras else ""))

    if ok and verbose:
        log("[JOGOS_VERIFY] Contrato local<->Supabase compatível.")
    return ok


def _supabase_creds():
    """Credenciais lidas de PROJECT_ROOT/.env.local (padrão publish_autores)."""
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


def publish(pacote=200):
    """Upsert (on_conflict=slug) na tabela Supabase `jogos`.

    Pré-requisito: migração scripts/sql/2026-07-14_secao_jogos.sql aplicada
    no SQL Editor do Supabase (uma vez). Sem ela -> erro claro abaixo.
    """
    log("[JOGOS_PUBLISH] Iniciando")
    url, key = _supabase_creds()
    if not url or not key:
        log("[JOGOS_PUBLISH] ERRO: NEXT_PUBLIC_SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY ausentes em .env.local")
        return 0

    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=representation",
    }
    table_url = f"{url}/rest/v1/jogos?on_conflict=slug"

    conn = get_conn()
    ensure_schema(conn)
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM jogos
        WHERE status_publish = 0 AND is_publishable = 1
        LIMIT ?
    """, (pacote,))
    rows = cur.fetchall()

    if not rows:
        log("[JOGOS_PUBLISH] Nada publicável pendente.")
        conn.close()
        return 0

    ok = falhas = 0
    now = datetime.utcnow().isoformat()
    for i, r in enumerate(rows, 1):
        payload = _build_payload(r, now)
        supabase_id = payload["id"]
        try:
            res = requests.post(table_url, headers=headers, json=payload, timeout=60)
            if res.status_code in (200, 201, 409):
                cur.execute("""
                    UPDATE jogos SET status_publish=1, supabase_id=?,
                           updated_at=CURRENT_TIMESTAMP WHERE id=?
                """, (supabase_id, r["id"]))
                conn.commit()
                ok += 1
                log(f"[JOGOS_PUBLISH][{i:03d}/{len(rows):03d}] OK -> {r['titulo']}")
            else:
                falhas += 1
                detail = res.text[:200]
                log(f"[JOGOS_PUBLISH] ERRO {res.status_code} -> {r['titulo']} | {detail}")
                if res.status_code == 404 or "jogos" in detail and "not exist" in detail:
                    log("[JOGOS_PUBLISH] ⚠ Tabela `jogos` não existe no Supabase. "
                        "Aplicar scripts/sql/2026-07-14_secao_jogos.sql no SQL Editor e re-rodar.")
                    break
        except Exception as e:
            falhas += 1
            log(f"[JOGOS_PUBLISH] ERRO -> {r['titulo']} | {e}")

    conn.close()
    log(f"[JOGOS_PUBLISH] Finalizado | OK: {ok} | Falhas: {falhas}")
    return ok


# =========================
# STATUS
# =========================

def status():
    conn = get_conn()
    ensure_schema(conn)
    cur = conn.cursor()
    q = lambda sql: cur.execute(sql).fetchone()[0]  # noqa: E731

    print("\n=== SEÇÃO JOGOS — PIPELINE PARALELO ===")
    print(f"Total de jogos:        {q('SELECT COUNT(*) FROM jogos')}")
    for slug in sorted(CATEGORIA_SLUGS):
        n = cur.execute("SELECT COUNT(*) FROM jogos WHERE categoria=?", (slug,)).fetchone()[0]
        print(f"  {CATEGORIA_LABELS[slug]:<22} {n}")
    print(f"Com oferta resolvida:  {q('SELECT COUNT(*) FROM jogos WHERE offer_url IS NOT NULL')}")
    print(f"Com scrape feito:      {q('SELECT COUNT(*) FROM jogos WHERE status_scrape=1')}")
    print(f"Com slug:              {q('SELECT COUNT(*) FROM jogos WHERE status_slug=1')}")
    print(f"Sinopse pendente:      {q('SELECT COUNT(*) FROM jogos WHERE status_synopsis=0')}")
    print(f"Sinopse em fila (3):   {q('SELECT COUNT(*) FROM jogos WHERE status_synopsis=3')}")
    print(f"Sinopse ok:            {q('SELECT COUNT(*) FROM jogos WHERE status_synopsis=1')}")
    print(f"Publicáveis (QG):      {q('SELECT COUNT(*) FROM jogos WHERE is_publishable=1')}")
    print(f"Publicados:            {q('SELECT COUNT(*) FROM jogos WHERE status_publish=1')}")
    print()
    conn.close()


# =========================
# AUTOPILOT
# =========================

def _synopsis_backlog(conn=None) -> int:
    """Jogos com descrição válida ainda sem sinopse aprovada — é o backlog
    que trava publicação (QG exige sinopse), análogo ao _content_backlog do G."""
    own = conn is None
    if own:
        conn = get_conn()
        ensure_schema(conn)
    n = conn.execute("""
        SELECT COUNT(*) FROM jogos
        WHERE status_synopsis != 1
          AND descricao IS NOT NULL AND TRIM(descricao) != ''
          AND status_publish = 0
    """).fetchone()[0]
    if own:
        conn.close()
    return n


def _drain_non_llm():
    """Exaure todo o trabalho não-LLM (idempotente — flags de status impedem
    reprocessamento): seeds novos -> resolver -> scraper -> slugs."""
    import_seeds()
    while resolve_offers(200):
        pass
    while scrape(30):
        pass
    gen_slugs()


def autopilot(max_lotes_llm=10):
    """Passe único (opção A do jogos.py): seeds -> resolver -> scraper ->
    slugs -> sinopses (lotes LLM até drenar/limite) -> QG -> publicar."""
    log("[JOGOS_AUTOPILOT] Iniciando passe completo da Seção Jogos")
    reclaim_stuck()
    _drain_non_llm()

    run_synopsis_batch(max_lotes=max_lotes_llm)

    quality_gate()
    publish()
    status()
    log("[JOGOS_AUTOPILOT] Passe concluído")


def autopilot_j():
    """Opção J — autopilot da Seção Jogos no MODELO DO G (loop multijanela).

    Espelha o _run_gargalo do main.py: um passe não-LLM + fase LLM; se sobrar
    backlog de sinopse (a quota da sessão PRO esgotou), entra em loop
    multijanela — espera produtiva (drena não-LLM + publica) -> aguarda o
    reset da sessão -> nova janela LLM -> publica — até o backlog zerar,
    uma janela não progredir (guard anti-giro) ou Ctrl+C.
    Sem confirmações interativas, como o G."""
    from core.claude_runner import claude_available
    from core.claude_usage_tracker import session_window

    log("[J] Autopilot Jogos (modelo G) — passe único + loop multijanela")

    # Pré-checagem do contrato de publicação (não bloqueia o trabalho local:
    # sem a migração o pipeline avança até o publish, que falha com instrução).
    verify_supabase(verbose=False)

    reclaim_stuck()
    _drain_non_llm()

    # ── 1ª janela LLM ──────────────────────────────────────────
    if claude_available():
        run_synopsis_batch(max_lotes=100)
    else:
        log("[J] claude CLI indisponível — pulando fase LLM (sinopses ficam pendentes).")
    quality_gate()
    publish()

    backlog = _synopsis_backlog()
    if backlog <= 0:
        log("[J] Backlog de sinopses zerado no primeiro passe.")
    elif not claude_available():
        log(f"[J] {backlog} sinopse(s) pendente(s), mas claude CLI indisponível — "
            f"encerrando sem loop multijanela.")
    else:
        # ── LOOP MULTIJANELA (modelo G) ────────────────────────
        log(f"[J] Backlog de sinopses restante: {backlog} — entrando em loop "
            f"multijanela (drena não-LLM -> aguarda reset -> retoma LLM).")
        try:
            while True:
                # 1) Espera produtiva: drena/publica o não-LLM enquanto a
                #    sessão PRO está em cooldown; sai quando a quota volta.
                while True:
                    _drain_non_llm()
                    quality_gate()
                    publish()
                    w = session_window()
                    if not w.get("in_cooldown"):
                        break                                # quota restaurada
                    secs = max(0, int(w.get("seconds_until_reset", 0)))
                    nap = min(300, secs)                     # re-checa a cada <=5 min
                    if nap <= 0:
                        break
                    log(f"[J] Não-LLM drenado; aguardando reset da sessão "
                        f"(~{secs // 60} min restantes)…")
                    time.sleep(nap)

                if session_window().get("in_cooldown"):
                    log("[J] Sessão ainda em cooldown — encerrando loop multijanela.")
                    break

                backlog_antes = _synopsis_backlog()
                if backlog_antes <= 0:
                    log("[J] Backlog de sinopses zerado — loop multijanela concluído.")
                    break

                # 2) Nova janela LLM (quota restaurada) + publicação.
                log(f"[J] ── Janela LLM (quota restaurada) — backlog: {backlog_antes} ──")
                run_synopsis_batch(max_lotes=100)
                quality_gate()
                publish()

                # 3) Guard anti-giro: janela sem progresso -> para (evita loop
                #    infinito quando o restante não é gerável, ex: descrição ruim).
                backlog_depois = _synopsis_backlog()
                if backlog_depois >= backlog_antes:
                    log(f"[J] Janela LLM sem progresso "
                        f"({backlog_antes}->{backlog_depois}) — encerrando loop.")
                    break
        except KeyboardInterrupt:
            log("[J] Loop multijanela interrompido pelo usuário.")

    # ── Relatório final ────────────────────────────────────────
    status()
    try:
        w = session_window()
        restante = _synopsis_backlog()
        if w.get("in_cooldown"):
            log(f"[J] Sessão PRO em cooldown (reset previsto: {w.get('reset_at', '?')}). "
                f"Backlog de sinopses: {restante}.")
        elif restante > 0:
            log(f"[J] Janela disponível e {restante} sinopse(s) pendente(s) — "
                f"re-rode J para avançar.")
    except Exception:
        pass
    log("[J] Passe concluído.")
