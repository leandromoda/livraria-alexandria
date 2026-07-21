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

# Custo previsível por execução: quantos lotes LLM cada fase pode consumir
# num passe. Antes era 100 (até 1.000 itens), o que tornava impossível prever
# se um run cabia na janela da sessão PRO.
MAX_LOTES_FINDER   = int(os.environ.get("JOGOS_MAX_LOTES_FINDER", 12))
MAX_LOTES_SYNOPSIS = int(os.environ.get("JOGOS_MAX_LOTES_SYNOPSIS", 12))

# Um input de lote parado além disto é ÓRFÃO de um run morto: o agente move o
# input para processed_* assim que começa a processá-lo, então um arquivo que
# permanece em batch/ por mais que o timeout do agente (finder: 30 min)
# significa que ninguém o consumiu.
BATCH_STALE_MINUTES = int(os.environ.get("JOGOS_BATCH_STALE_MINUTES", 45))

# Tentativas de raspagem por jogo antes de desistir e deixar para o finder.
# Sem isto, todo passe re-enfileirava TODOS os sem-descrição (centenas de
# requisições a marketplaces que bloqueiam, com rendimento ~zero).
MAX_SCRAPE_ATTEMPTS = int(os.environ.get("JOGOS_MAX_SCRAPE_ATTEMPTS", 3))

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

        -- Agente finder (LLM): 1=já tentou e não achou (não re-exportar)
        finder_tried    INTEGER DEFAULT 0,

        -- Rejeições de sinopse com a MESMA descrição (anti-loop de quota):
        -- ao atingir SYN_REJECTS_MAX a descrição é descartada como fonte ruim
        syn_rejects     INTEGER DEFAULT 0,

        -- Tentativas de raspagem já gastas (backoff do requeue)
        scrape_attempts INTEGER DEFAULT 0,

        seed_id         TEXT,
        created_at      DATETIME,
        updated_at      DATETIME
    )
    """)

    # Migrations para bancos onde a tabela jogos já existia sem colunas novas
    for col, definition in [
        ("finder_tried",    "INTEGER DEFAULT 0"),
        ("syn_rejects",     "INTEGER DEFAULT 0"),
        ("scrape_attempts", "INTEGER DEFAULT 0"),
    ]:
        try:
            conn.execute(f"ALTER TABLE jogos ADD COLUMN {col} {definition}")
        except sqlite3.OperationalError:
            pass  # coluna já existe

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
    """Step 1 — importa NNN_jogos_seeds.json e move para ingested_seeds/.

    Nome de arquivo repetido NÃO é falha: o seed é reprocessado e SOBRESCREVE
    o anterior (registro em seed_imports via INSERT OR REPLACE + arquivo em
    ingested_seeds/). A proteção contra dado duplicado é por ITEM
    (insert_seed -> "duplicate" em titulo+autor), não pelo nome do arquivo —
    mesmo comportamento do pipeline de livros (offer_seed.run()). Antes, o
    skip por nome fazia um seed novo reusando um número já consumido ser
    ignorado em silêncio e ficar preso em seeds/ para sempre.
    """
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
            log(f"[JOGOS_SEED] Nome já usado -> {filename} | reprocessando "
                f"(sobrescreve o anterior; itens repetidos caem no dedup)")

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
# 3. SCRAPER (capa + descrição + preço — via PÁGINA DO PRODUTO)
# =========================

# O offer_url do resolver é uma URL de BUSCA. Os SELECTORS do
# marketplace_scraper são de PÁGINA DE PRODUTO (#productDescription,
# .ui-pdp-*) — raspar a busca não rende descrição nem imagem (só um preço
# de card, possivelmente de outro item). Nos livros esse buraco era coberto
# pelos fallbacks Open Library/Google Books, que jogos não usam (por design).
# Aqui, portanto: busca -> resultado CUJO TÍTULO CASA com o jogo -> raspa a
# página do produto, e o offer_url é promovido ao deep-link afiliado.
#
# A validação de título é OBRIGATÓRIA: o 1º resultado da busca pode ser
# outro produto (medido: "Knave" retornou Blades in the Dark). Sem card
# compatível -> sem produto -> item fica sem descrição e vai para o agente
# finder (LLM), que cobre também os muros anti-bot (Amazon 503/captcha,
# ML account-verification) — mesmo papel do offer_finder nos livros.

_AMAZON_ASIN_RE = re.compile(r"/dp/([A-Z0-9]{10})")
_ML_LINK_RE     = re.compile(
    r"https?://(?:produto\.mercadolivre\.com\.br/MLB-?\d+[^\s\"'#?]*"
    r"|www\.mercadolivre\.com\.br/[^\s\"'#?]*?/p/MLB\d+)"
)

# Tokens que não identificam o produto (edição/formato/tipo)
_TITULO_STOPWORDS = {
    "rpg", "livro", "basico", "básico", "caixa", "box", "edicao", "edição",
    "jogo", "jogos", "de", "do", "da", "dos", "das", "e", "o", "a", "em",
    "para", "ed", "vol", "volume", "2a", "1a", "3a", "ii", "iii",
}


def _tokens_titulo(texto):
    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode("ascii")
    t = re.sub(r"[^a-z0-9\s]", " ", t.lower())
    return [w for w in t.split() if w and w not in _TITULO_STOPWORDS]


def _titulo_compativel(titulo_jogo, titulo_resultado):
    """True se o título do resultado da busca corresponde ao jogo procurado.
    Critério: >=60% dos tokens significativos do jogo presentes no resultado
    (ou similaridade global >=0.6). Rejeita produto errado; falso negativo é
    aceitável (o item vai para o agente finder)."""
    from difflib import SequenceMatcher

    tj = _tokens_titulo(titulo_jogo)
    if not tj:
        return False
    tr = set(_tokens_titulo(titulo_resultado))
    if tr:
        hits = sum(1 for w in tj if w in tr)
        if hits / len(tj) >= 0.6:
            return True
    a = " ".join(tj)
    b = " ".join(sorted(tr))
    return SequenceMatcher(None, a, b).ratio() >= 0.6


def _find_product_url(soup, marketplace, titulo):
    """Extrai da página de BUSCA a URL do primeiro resultado cujo TÍTULO casa
    com o jogo. Retorna URL canônica sem tag de afiliado, ou None."""
    if soup is None:
        return None

    if marketplace == "amazon":
        # Cards de resultado (páginas reais têm; páginas de captcha, não)
        for card in soup.select('div[data-component-type="s-search-result"]'):
            h2 = card.select_one("h2")
            card_titulo = h2.get_text(" ", strip=True) if h2 else ""
            if not _titulo_compativel(titulo, card_titulo):
                continue
            for a in card.select('a[href*="/dp/"]'):
                href = a.get("href") or ""
                if "/sspa/" in href or "sspa=" in href:   # patrocinado
                    continue
                m = _AMAZON_ASIN_RE.search(href)
                if m:
                    return f"https://www.amazon.com.br/dp/{m.group(1)}"
        return None

    if marketplace == "mercadolivre":
        # Layouts novo (poly-card) e antigo (ui-search)
        cards = soup.select("div.poly-card, li.ui-search-layout__item")
        for card in cards:
            t = card.select_one(
                ".poly-component__title, .ui-search-item__title, h3, h2"
            )
            card_titulo = t.get_text(" ", strip=True) if t else ""
            if not _titulo_compativel(titulo, card_titulo):
                continue
            for a in card.select("a[href]"):
                href = (a.get("href") or "").split("#", 1)[0]
                if "click1.mercadolivre" in href or "mclics" in href:  # anúncio
                    continue
                m = _ML_LINK_RE.match(href)
                if m:
                    return m.group(0)
        return None

    return None


def _resolve_produto(search_url, titulo):
    """Busca -> página do produto compatível com o título.
    Retorna (result_dict|None, product_url_afiliada|None). SEM fallback de
    raspar a página de busca: dado de produto errado é pior que dado nenhum
    (o item sem descrição segue para o agente finder)."""
    from steps.marketplace_scraper import (
        detect_marketplace, fetch_page, scrape_marketplace,
    )
    from steps.offer_resolver import inject_amazon_tag, inject_ml_affiliate

    marketplace = detect_marketplace(search_url)
    soup = fetch_page(search_url)
    if soup is None:
        return None, None

    product_url = _find_product_url(soup, marketplace, titulo)
    if not product_url:
        return None, None

    result = scrape_marketplace(product_url)
    if not result:
        return None, None

    afiliada = (inject_amazon_tag(product_url) if marketplace == "amazon"
                else inject_ml_affiliate(product_url))
    return result, afiliada


def scrape(pacote=30):
    """Step 3 — resolve a busca para a página do PRODUTO e extrai
    imagem/descrição/preço de lá. ÚNICA fonte de conteúdo para jogos
    (sem Google Books/OpenLibrary, que só catalogam livros)."""
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
            result, product_url = _resolve_produto(r["offer_url"], r["titulo"])
        except Exception as e:
            result, product_url = None, None
            log(f"[JOGOS_SCRAPE] ERRO -> {r['titulo']} | {e}")

        if result and product_url:
            offer_status = "active" if result.get("disponivel", True) else "unavailable"
            cur.execute("""
                UPDATE jogos
                SET offer_url   = ?,
                    imagem_url  = COALESCE(?, imagem_url),
                    descricao   = COALESCE(?, descricao),
                    preco_atual = COALESCE(?, preco_atual),
                    offer_status = ?,
                    status_scrape = 1,
                    syn_rejects = CASE WHEN ? IS NOT NULL THEN 0
                                       ELSE COALESCE(syn_rejects, 0) END,
                    updated_at  = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (product_url, result.get("cover_url"), result.get("descricao"),
                  result.get("preco"), offer_status, result.get("descricao"), r["id"]))
            log(f"[JOGOS_SCRAPE] OK [produto] -> {r['titulo']}"
                + ("" if result.get("descricao") else " (sem descrição na página)"))
            ok += 1
        else:
            # Sem produto compatível (busca bloqueada/captcha ou título sem
            # correspondência) — fica para o agente finder (LLM).
            cur.execute(
                "UPDATE jogos SET status_scrape=2, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (r["id"],),
            )
            log(f"[JOGOS_SCRAPE] SEM PRODUTO COMPATÍVEL -> {r['titulo']} (vai ao finder LLM)")
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
# 4b. FINDER (batch LLM — conteúdo quando o scraper não alcança)
# =========================

# Os marketplaces bot-walham scraping direto (Amazon: 503/captcha; ML:
# account-verification). Mesmo papel do offer_finder nos livros: um agente
# claude com WebSearch/WebFetch localiza a página REAL do produto, valida a
# correspondência de título e extrai descrição/imagem/preço.

FINDER_PREFIX     = "jogos_finder"   # NNN_jogos_finder_input.json
FINDER_BATCH_SIZE = int(os.environ.get("BATCH_SIZE_JOGOS_FINDER", 10))
FINDER_PROCESSED  = os.path.join(BATCH_DIR, f"processed_{FINDER_PREFIX}")
FINDER_TIMEOUT_S  = 1800   # WebSearch+WebFetch por item — lote é lento

# detect_marketplace() -> convenção local dos seeds
_MKT_LOCAL = {"amazon": "amazon", "mercadolivre": "mercado_livre"}


def finder_export(pacote=None):
    """Exporta lote NNN_jogos_finder_input.json com os jogos sem descrição
    ainda não tentados pelo finder. Não exporta se já há input em voo."""
    import glob as _glob

    os.makedirs(BATCH_DIR, exist_ok=True)
    os.makedirs(FINDER_PROCESSED, exist_ok=True)

    # Descarta lotes órfãos antes de decidir: sem isto, um input de run morto
    # bloqueava o finder indefinidamente.
    if purge_stale_inputs(FINDER_PREFIX, tag="JOGOS_FINDER"):
        log("[JOGOS_FINDER] Input já em voo — aguardando o agente processar.")
        return 0

    conn = get_conn()
    ensure_schema(conn)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, slug, titulo, autor, categoria, marketplace, lookup_query
        FROM jogos
        WHERE (descricao IS NULL OR TRIM(descricao) = '')
          AND COALESCE(finder_tried, 0) = 0
          AND status_publish = 0
        ORDER BY created_at ASC
        LIMIT ?
    """, (min(pacote or FINDER_BATCH_SIZE, FINDER_BATCH_SIZE),))
    rows = cur.fetchall()

    if not rows:
        log("[JOGOS_FINDER] Nada pendente para o finder.")
        conn.close()
        return 0

    jogos = [{
        "id":           r["id"],
        "slug":         r["slug"] or "",
        "titulo":       r["titulo"],
        "autor":        r["autor"] or "",
        "categoria":    CATEGORIA_LABELS.get(r["categoria"], r["categoria"]),
        "marketplace":  r["marketplace"] or "amazon",
        "lookup_query": r["lookup_query"] or "",
    } for r in rows]

    from core.batch_numbering import next_batch_number
    num = next_batch_number(BATCH_DIR, FINDER_PREFIX)
    path = os.path.join(BATCH_DIR, f"{num}_{FINDER_PREFIX}_input.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "meta": {"exported_at": datetime.utcnow().isoformat(), "batch": num,
                     "total": len(jogos)},
            "jogos": jogos,
        }, f, ensure_ascii=False, indent=2)

    conn.close()
    log(f"[JOGOS_FINDER] Exportados: {len(jogos)} -> {os.path.basename(path)}")
    return len(jogos)


def finder_import():
    """Importa NNN_jogos_finder_output.json: FOUND -> descrição/imagem/preço +
    offer_url promovida ao deep-link afiliado; NOT_FOUND -> finder_tried=1."""
    import glob as _glob
    from steps.marketplace_scraper import detect_marketplace
    from steps.offer_resolver import inject_amazon_tag, inject_ml_affiliate

    os.makedirs(FINDER_PROCESSED, exist_ok=True)
    outputs = sorted(_glob.glob(os.path.join(BATCH_DIR, f"*_{FINDER_PREFIX}_output.json")))
    if not outputs:
        log("[JOGOS_FINDER] Nenhum output pendente.")
        return 0

    conn = get_conn()
    ensure_schema(conn)
    cur = conn.cursor()
    encontrados = nao_encontrados = 0

    for path in outputs:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            log(f"[JOGOS_FINDER] ERRO ao ler {os.path.basename(path)}: {e}")
            continue

        for item in data.get("resultados", []):
            jogo_id   = item.get("id")
            status    = (item.get("status") or "").upper()
            url       = (item.get("url_produto") or "").strip()
            descricao = (item.get("descricao") or "").strip()
            mkt       = detect_marketplace(url)

            if status == "FOUND" and url and mkt and len(descricao) >= 80:
                afiliada = (inject_amazon_tag(url) if mkt == "amazon"
                            else inject_ml_affiliate(url))
                cur.execute("""
                    UPDATE jogos
                    SET offer_url    = ?,
                        marketplace  = ?,
                        descricao    = ?,
                        imagem_url   = COALESCE(?, imagem_url),
                        preco_atual  = COALESCE(?, preco_atual),
                        offer_status = 'active',
                        status_scrape = 1,
                        syn_rejects  = 0,
                        updated_at   = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (afiliada, _MKT_LOCAL[mkt], descricao,
                      _text_or_none(item.get("imagem_url")),
                      _float_or_none(item.get("preco")),
                      jogo_id))
                encontrados += 1
            else:
                motivo = item.get("motivo") or ("output inválido" if status == "FOUND" else "não encontrado")
                cur.execute("""
                    UPDATE jogos SET finder_tried = 1,
                           updated_at = CURRENT_TIMESTAMP WHERE id = ?
                """, (jogo_id,))
                nao_encontrados += 1
                log(f"[JOGOS_FINDER] NOT_FOUND ({motivo}) -> id={jogo_id}")
        conn.commit()

        dest = os.path.join(FINDER_PROCESSED, os.path.basename(path))
        try:
            if os.path.exists(dest):
                os.remove(dest)
            shutil.move(path, dest)
        except Exception as e:
            log(f"[JOGOS_FINDER] AVISO: falha ao arquivar {os.path.basename(path)}: {e}")

    conn.close()
    log(f"[JOGOS_FINDER] Finalizado | Encontrados: {encontrados} | Não encontrados: {nao_encontrados}")
    return encontrados


def run_finder_batch(max_lotes=5):
    """Ciclo finder completo: export -> agente (claude CLI + WebSearch) ->
    import, até drenar os sem-descrição, esgotar max_lotes ou falhar/limite."""
    from core.claude_runner import agent_prompt_path, run_agent

    total = 0
    for _ in range(max_lotes):
        exportados = finder_export()
        if not exportados:
            break
        ok, out = run_agent(agent_prompt_path("jogos_finder_batch"),
                            timeout=FINDER_TIMEOUT_S, wait_on_limit=False)
        if not ok:
            log(f"[JOGOS_FINDER] Agente falhou/limite de sessão — parando. {out[:200]}")
            # devolve o input em voo para a fila (evita lote órfão)
            import glob as _glob
            for p in _glob.glob(os.path.join(BATCH_DIR, f"*_{FINDER_PREFIX}_input.json")):
                try:
                    os.remove(p)
                except OSError:
                    pass
            break
        total += finder_import()
    return total


# =========================
# 5. SINOPSES (batch LLM — claude CLI)
# =========================

def purge_stale_inputs(prefix, tag="JOGOS_RECLAIM"):
    """Remove inputs de lote ÓRFÃOS (mais velhos que BATCH_STALE_MINUTES) e
    devolve a lista dos que continuam legitimamente em voo.

    O agente move o input para processed_* assim que começa a processá-lo.
    Logo, um input que permanece em batch/ por mais tempo que o timeout do
    agente é resto de um run morto — mantê-lo bloqueava o reclaim e os itens
    ficavam presos em status 3 para sempre, enquanto cada novo passe exportava
    mais um lote que também morria (moinho de quota).
    """
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
            log(f"[{tag}] AVISO: falha ao remover lote órfão "
                f"{os.path.basename(path)}: {e}")

    return [p for p, _ in vivos]


def reclaim_stuck(conn=None):
    """Recupera jogos presos em status_synopsis=3 cuja fila não existe mais.

    Lotes órfãos (run morto) são descartados primeiro; só um lote realmente
    recente segura o reclaim."""
    own = conn is None
    if own:
        conn = get_conn()
        ensure_schema(conn)

    em_voo = purge_stale_inputs(BATCH_PREFIX)

    n = 0
    if not em_voo:
        cur = conn.execute(
            "UPDATE jogos SET status_synopsis=0, updated_at=CURRENT_TIMESTAMP WHERE status_synopsis=3"
        )
        n = cur.rowcount
        conn.commit()
        if n:
            log(f"[JOGOS_RECLAIM] {n} jogo(s) recuperado(s) de fila órfã (status 3->0)")
    else:
        log(f"[JOGOS_RECLAIM] {len(em_voo)} lote(s) ainda em voo — reclaim adiado.")

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


SYN_REJECTS_MAX = 2   # tentativas de sinopse por FONTE (descrição)


def synopsis_import():
    """Importa NNN_synopsis_jogos_output.json -> sinopse + status_synopsis=1.

    REJECTED/inválida -> status_synopsis=0 (volta à fila) e syn_rejects+1.
    Ao atingir SYN_REJECTS_MAX, a DESCRIÇÃO é descartada como fonte ruim
    (medido: title-mismatch re-exportava a mesma descrição em loop, queimando
    quota) e o jogo volta ao finder (finder_tried=0) por uma fonte melhor."""
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
                    UPDATE jogos SET sinopse=?, status_synopsis=1, syn_rejects=0,
                           updated_at=CURRENT_TIMESTAMP WHERE id=?
                """, (sinopse, jogo_id))
                aprovados += 1
            else:
                cur.execute("""
                    UPDATE jogos SET status_synopsis=0,
                           syn_rejects = COALESCE(syn_rejects, 0) + 1,
                           updated_at=CURRENT_TIMESTAMP WHERE id=?
                """, (jogo_id,))
                rejeitados += 1
                row = cur.execute(
                    "SELECT COALESCE(syn_rejects,0) FROM jogos WHERE id=?", (jogo_id,)
                ).fetchone()
                n_rejects = row[0] if row else 0
                if n_rejects >= SYN_REJECTS_MAX:
                    cur.execute("""
                        UPDATE jogos SET descricao=NULL, finder_tried=0, syn_rejects=0,
                               updated_at=CURRENT_TIMESTAMP WHERE id=?
                    """, (jogo_id,))
                    log(f"[JOGOS_SYN_IMPORT] Rejeitado ({problema}) -> id={jogo_id} | "
                        f"{n_rejects}ª rejeição: descrição DESCARTADA (fonte ruim) — "
                        f"volta ao finder por fonte nova")
                else:
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
    com_descricao = q("SELECT COUNT(*) FROM jogos "
                      "WHERE descricao IS NOT NULL AND TRIM(descricao) != ''")
    print(f"Com oferta resolvida:  {q('SELECT COUNT(*) FROM jogos WHERE offer_url IS NOT NULL')}")
    print(f"Com scrape feito:      {q('SELECT COUNT(*) FROM jogos WHERE status_scrape=1')}")
    print(f"Com descrição:         {com_descricao}")
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


def _sem_descricao(conn=None, acionavel=False) -> int:
    """Jogos ainda sem descrição — o gargalo de FONTE (o LLM não tem de onde
    gerar). Distinto do backlog de sinopse (que só conta os geráveis).
    acionavel=True: só os que o finder ainda pode tentar (finder_tried=0)."""
    own = conn is None
    if own:
        conn = get_conn()
        ensure_schema(conn)
    extra = "AND COALESCE(finder_tried, 0) = 0" if acionavel else ""
    n = conn.execute(f"""
        SELECT COUNT(*) FROM jogos
        WHERE (descricao IS NULL OR TRIM(descricao) = '')
          AND status_publish = 0
          {extra}
    """).fetchone()[0]
    if own:
        conn.close()
    return n


def _requeue_scrape_sem_descricao():
    """Re-enfileira para scrape os jogos sem descrição, COM BACKOFF.

    Só reentram os que ainda têm tentativas (scrape_attempts <
    MAX_SCRAPE_ATTEMPTS), e cada requeue consome uma. Antes, todo passe
    re-enfileirava TODOS os sem-descrição — centenas de requisições a
    marketplaces que bloqueiam (Amazon 503/captcha, ML account-verification),
    com rendimento próximo de zero e ~20 min de atraso até o trabalho útil.
    Quem esgota as tentativas fica para o finder (LLM), que é quem de fato
    atravessa o bloqueio.
    """
    conn = get_conn()
    ensure_schema(conn)
    cur = conn.execute(f"""
        UPDATE jogos
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

    esgotados = conn.execute(f"""
        SELECT COUNT(*) FROM jogos
        WHERE (descricao IS NULL OR TRIM(descricao) = '')
          AND status_publish = 0
          AND COALESCE(scrape_attempts, 0) >= {MAX_SCRAPE_ATTEMPTS}
    """).fetchone()[0]
    conn.close()

    if n:
        log(f"[JOGOS_SCRAPE] {n} jogo(s) sem descrição re-enfileirado(s) "
            f"(limite {MAX_SCRAPE_ATTEMPTS} tentativas)")
    if esgotados:
        log(f"[JOGOS_SCRAPE] {esgotados} jogo(s) esgotaram as tentativas de "
            f"raspagem — seguem só pelo finder (LLM)")
    return n


def _drain_non_llm():
    """Exaure todo o trabalho não-LLM (idempotente — flags de status impedem
    reprocessamento): seeds novos -> resolver -> scraper -> slugs.

    NÃO re-enfileira scrape aqui: esta função roda a cada <=5 min na espera
    produtiva do loop multijanela — re-raspar os 'sem descrição' nessa
    frequência martelaria o marketplace. O requeue é 1x por passe
    (_requeue_scrape_sem_descricao no início do autopilot/autopilot_j)."""
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
    _requeue_scrape_sem_descricao()
    _drain_non_llm()

    run_finder_batch(max_lotes=max_lotes_llm)
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
    _requeue_scrape_sem_descricao()
    _drain_non_llm()

    # -- 1ª janela LLM: finder (fonte) -> sinopses (geração) ----
    if claude_available():
        run_finder_batch(max_lotes=MAX_LOTES_FINDER)
        run_synopsis_batch(max_lotes=MAX_LOTES_SYNOPSIS)
    else:
        log("[J] claude CLI indisponível — pulando fase LLM (finder e sinopses ficam pendentes).")
    quality_gate()
    publish()

    backlog  = _synopsis_backlog()
    sem_desc = _sem_descricao(acionavel=True)
    pendente_llm = backlog + sem_desc

    if pendente_llm <= 0:
        mortos = _sem_descricao() - sem_desc
        if mortos:
            log(f"[J] Conteúdo gerável drenado. {mortos} jogo(s) sem descrição já "
                f"esgotaram scraper e finder — ficam bloqueados no QG (revisão manual).")
        else:
            log("[J] Backlog de conteúdo (fonte + sinopses) zerado no primeiro passe.")
    elif not claude_available():
        log(f"[J] {backlog} sinopse(s) e {sem_desc} descrição(ões) pendentes, mas "
            f"claude CLI indisponível — encerrando sem loop multijanela.")
    else:
        # -- LOOP MULTIJANELA (modelo G) ------------------------
        log(f"[J] Backlog restante — sinopses: {backlog} | sem descrição "
            f"(finder): {sem_desc} — entrando em loop multijanela "
            f"(drena não-LLM -> aguarda reset -> retoma LLM).")
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

                backlog_antes  = _synopsis_backlog()
                sem_desc_antes = _sem_descricao(acionavel=True)
                if backlog_antes + sem_desc_antes <= 0:
                    log("[J] Backlog de conteúdo zerado — loop multijanela concluído.")
                    break

                # 2) Nova janela LLM (quota restaurada) + publicação.
                log(f"[J] -- Janela LLM (quota restaurada) — sinopses: "
                    f"{backlog_antes} | finder: {sem_desc_antes} --")
                run_finder_batch(max_lotes=MAX_LOTES_FINDER)
                run_synopsis_batch(max_lotes=MAX_LOTES_SYNOPSIS)
                quality_gate()
                publish()

                # 3) Guard anti-giro: janela sem NENHUM progresso (nem descrição
                #    adquirida, nem sinopse gerada) -> para.
                backlog_depois  = _synopsis_backlog()
                sem_desc_depois = _sem_descricao(acionavel=True)
                if backlog_depois >= backlog_antes and sem_desc_depois >= sem_desc_antes:
                    log(f"[J] Janela LLM sem progresso (sinopses {backlog_antes}->"
                        f"{backlog_depois}; finder {sem_desc_antes}->{sem_desc_depois}) "
                        f"— encerrando loop.")
                    break
        except KeyboardInterrupt:
            log("[J] Loop multijanela interrompido pelo usuário.")

    # -- Relatório final ----------------------------------------
    status()
    try:
        w = session_window()
        restante = _synopsis_backlog()
        sem_desc = _sem_descricao()
        if sem_desc:
            log(f"[J] {sem_desc} jogo(s) sem descrição (gargalo de fonte) — "
                f"serão re-raspados no próximo J.")
        if w.get("in_cooldown"):
            log(f"[J] Sessão PRO em cooldown (reset previsto: {w.get('reset_at', '?')}). "
                f"Backlog de sinopses: {restante}.")
        elif restante > 0:
            log(f"[J] Janela disponível e {restante} sinopse(s) pendente(s) — "
                f"re-rode J para avançar.")
    except Exception:
        pass
    log("[J] Passe concluído.")
