# ============================================================
# STEP 1 — OFFER SEED IMPORT
# Livraria Alexandria
#
# BOOTSTRAP SAFE — gera banco do zero se necessário
# Schema canônico definido aqui. Todos os outros scripts
# dependem deste schema.
#
# Multi-seed: processa todos os arquivos NNN_offer_seeds.json
# de scripts/data/seeds/ em ordem crescente. Arquivos já
# importados são rastreados em seed_imports e movidos para
# scripts/data/seeds/ingested_seeds/ após processamento.
#
# Campos separados:
#   descricao → texto bruto vindo de APIs externas
#   sinopse   → texto gerado pelo pipeline LLM
# ============================================================

import json
import os
import re
import shutil
import sqlite3
from datetime import datetime


# =========================
# CONFIG
# =========================

BASE_DIR  = os.path.dirname(os.path.dirname(__file__))
DATA_DIR  = os.path.join(BASE_DIR, "data")
SEEDS_DIR = os.path.join(DATA_DIR, "seeds")

DB_PATH = os.path.join(DATA_DIR, "books.db")

SEED_PATTERN = re.compile(r"^\d{3}_offer_seeds?\.json$")


# =========================
# LOGGER
# =========================

def log(msg):
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {msg}")


# =========================
# EDITORIAL FILTER
# =========================

EXCLUDED_TERMS = [
    "journal", "report", "census", "proceedings",
    "transactions", "bulletin", "review", "minutes",
    "laws", "legislation", "court", "committee",
    "annual report", "executive summary", "documents",
]


def is_editorial(titulo):

    if not titulo:
        return False

    t = titulo.lower()

    for term in EXCLUDED_TERMS:
        if term in t:
            return False

    return True


# =========================
# LANGUAGE DETECTION
# =========================

ISBN_PREFIX_LANG = {
    ("85", "65", "972"): "PT",
    ("84",):             "ES",
    ("88",):             "IT",
    ("0", "1"):          "EN",
}

TITLE_PATTERNS = {
    "PT": r"(ção|ções|lh|nh|ã|õ)",
    "ES": r"(ñ|¿|¡)",
    "IT": r"(gli|zione)",
    "FR": r"(é|à|è)",
    "DE": r"\b(der|die|das)\b",
}


def detect_lang_by_isbn(isbn):
    if not isbn:
        return None
    for prefixes, lang in ISBN_PREFIX_LANG.items():
        if isbn.startswith(prefixes):
            return lang
    return None


def detect_lang_by_title(titulo):
    if not titulo:
        return None
    t = titulo.lower()
    for lang, pattern in TITLE_PATTERNS.items():
        if re.search(pattern, t):
            return lang
    return None


def resolve_language(idioma_declarado, isbn, titulo):
    if idioma_declarado:
        return idioma_declarado.upper()
    isbn_lang = detect_lang_by_isbn(isbn)
    if isbn_lang:
        return isbn_lang
    title_lang = detect_lang_by_title(titulo)
    if title_lang:
        return title_lang
    return "UNKNOWN"


# =========================
# DB CONNECTION
# =========================

def get_conn():

    os.makedirs(DATA_DIR, exist_ok=True)

    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=60000")

    return conn


# =========================
# TABLE BOOTSTRAP — SCHEMA CANÔNICO
# =========================

def ensure_tables(conn):

    log("Verificando tabela livros (bootstrap)…")

    conn.execute("""
    CREATE TABLE IF NOT EXISTS livros (

        id              TEXT PRIMARY KEY,

        titulo          TEXT NOT NULL,
        slug            TEXT,
        autor           TEXT,
        isbn            TEXT,
        ano_publicacao  INTEGER,
        imagem_url      TEXT,
        idioma          TEXT,
        cluster         TEXT,
        fonte           TEXT,
        categoria       TEXT,

        -- Conteúdo editorial (campos separados)
        descricao       TEXT,
        sinopse         TEXT,

        -- Metadados de curadoria
        is_book             INTEGER DEFAULT 1,
        editorial_score     INTEGER DEFAULT 0,
        is_publishable      INTEGER DEFAULT 1,

        -- Oferta / afiliado
        lookup_query        TEXT,
        marketplace         TEXT,
        offer_url           TEXT,
        offer_status        TEXT    DEFAULT 'active',
        preco               REAL,
        preco_atual         REAL,
        preco_anterior      REAL,
        preco_updated_at    DATETIME,
        reactivation_pending INTEGER DEFAULT 0,
        status_publish_oferta INTEGER DEFAULT 0,

        -- IDs de classificação
        cluster_id          INTEGER,
        nacionalidade_id    INTEGER,
        popularidade_id     INTEGER,

        -- Pipeline status flags
        status_slug         INTEGER DEFAULT 0,
        status_dedup        INTEGER DEFAULT 0,
        status_review       INTEGER DEFAULT 0,
        status_synopsis     INTEGER DEFAULT 0,
        status_cover        INTEGER DEFAULT 0,
        status_enrich       INTEGER DEFAULT 0,
        status_publish      INTEGER DEFAULT 0,
        status_categorize   INTEGER DEFAULT 0,

        -- Supabase sync
        supabase_id         TEXT,

        created_at      DATETIME,
        updated_at      DATETIME
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS seed_imports (
        filename    TEXT PRIMARY KEY,
        imported_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        inserted    INTEGER DEFAULT 0,
        skipped     INTEGER DEFAULT 0
    )
    """)

    conn.commit()
    log("Schema canônico verificado.")


# =========================
# SEED FILES DISCOVERY
# =========================

def discover_seed_files():
    """Retorna lista de (filename, filepath) em ordem crescente."""

    if not os.path.exists(SEEDS_DIR):
        return []

    files = [
        f for f in os.listdir(SEEDS_DIR)
        if SEED_PATTERN.match(f)
    ]

    files.sort()

    return [(f, os.path.join(SEEDS_DIR, f)) for f in files]


def already_imported(conn, filename):
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM seed_imports WHERE filename = ? LIMIT 1", (filename,))
    return cur.fetchone() is not None


def mark_imported(conn, filename, inserted, skipped):
    conn.execute("""
        INSERT OR REPLACE INTO seed_imports (filename, imported_at, inserted, skipped)
        VALUES (?, CURRENT_TIMESTAMP, ?, ?)
    """, (filename, inserted, skipped))
    conn.commit()


def move_to_ingested(filepath, filename):
    ingested_dir = os.path.join(SEEDS_DIR, "ingested_seeds")
    os.makedirs(ingested_dir, exist_ok=True)
    dest = os.path.join(ingested_dir, filename)
    try:
        shutil.move(filepath, dest)
        log(f"Arquivo movido → ingested_seeds/{filename}")
    except Exception as e:
        log(f"[AVISO] Falha ao mover {filename}: {e} — arquivo permanece em seeds/")


# =========================
# LOAD SEEDS
# =========================

def load_seeds(filepath):

    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


# =========================
# INSERT SEED
# =========================

def insert_seed(conn, seed):

    now = datetime.utcnow().isoformat()

    titulo       = seed.get("titulo")
    autor        = seed.get("autor")
    idioma       = seed.get("idioma")
    isbn         = seed.get("isbn")
    categoria    = seed.get("categoria")
    marketplace  = seed.get("marketplace")
    lookup_query = seed.get("lookup_query")
    preco        = seed.get("preco")

    if not titulo or not lookup_query:
        return "invalid"

    if not is_editorial(titulo):
        return "filtered"

    idioma_resolved = resolve_language(idioma, isbn, titulo)

    cur = conn.cursor()

    cur.execute("""
        SELECT id FROM livros
        WHERE titulo = ?
        AND IFNULL(autor,'') = IFNULL(?, '')
        LIMIT 1
    """, (titulo, autor))

    if cur.fetchone():
        return "duplicate"

    cur.execute("""
        INSERT INTO livros (
            id, titulo, autor, isbn,
            cluster, fonte, idioma, categoria,
            lookup_query, marketplace, offer_status,
            preco,
            cluster_id, nacionalidade_id, popularidade_id,
            ano_publicacao,
            created_at, updated_at
        )
        VALUES (
            lower(hex(randomblob(12))),
            ?, ?, ?,
            ?, 'offer_seed', ?, ?,
            ?, ?, 'active',
            ?,
            ?, ?, ?,
            ?,
            ?, ?
        )
    """, (
        titulo, autor, isbn,
        categoria, idioma_resolved, categoria,
        lookup_query, marketplace,
        preco,
        seed.get("cluster_id"),
        seed.get("nacionalidade_id"),
        seed.get("popularidade_id"),
        seed.get("ano_sorteado"),
        now, now
    ))

    return "inserted"


# =========================
# PROCESS ONE FILE
# =========================

def process_file(conn, filename, filepath):

    log(f"Processando {filename}…")

    try:
        seeds = load_seeds(filepath)
    except Exception as e:
        log(f"[ERRO] Falha ao carregar {filename}: {e}")
        log(f"[ERRO] Arquivo ignorado — corrija o conteúdo e execute novamente.")
        return None, None

    total  = len(seeds)
    counts = {"inserted": 0, "duplicate": 0, "filtered": 0, "invalid": 0, "error": 0}

    for i, seed in enumerate(seeds, start=1):
        titulo_log = seed.get("titulo", "?")
        print(f"[SEED][{i:03d}/{total:03d}] → {titulo_log}")

        try:
            result = insert_seed(conn, seed)
            counts[result] = counts.get(result, 0) + 1
        except Exception as e:
            log(f"[ERRO] {titulo_log}: {e}")
            counts["error"] += 1

    conn.commit()

    inserted = counts["inserted"]
    skipped  = counts["duplicate"] + counts["filtered"] + counts["invalid"]

    log(
        f"[SEED] {filename} → "
        f"OK: {inserted} | "
        f"Falhas: {counts['error']} | "
        f"Pulados: {skipped} | "
        f"Total: {total}"
    )

    return inserted, skipped


# =========================
# RUN
# =========================

def run():

    log("Iniciando Offer Seed Import...")

    conn = get_conn()

    ensure_tables(conn)

    seed_files = discover_seed_files()

    if not seed_files:
        log("Nenhum arquivo de seed encontrado em scripts/data/seeds/")
        log("Padrão esperado: NNN_offer_seeds.json (ex: 001_offer_seeds.json)")
        conn.close()
        return

    total_inserted = 0
    total_skipped  = 0
    processed      = 0

    for filename, filepath in seed_files:

        if already_imported(conn, filename):
            log(f"[SKIP] {filename} — já importado anteriormente")
            continue

        inserted, skipped = process_file(conn, filename, filepath)

        if inserted is None:
            log(f"[SKIP] {filename} não marcado como importado — arquivo permanece em seeds/ para correção.")
            continue

        mark_imported(conn, filename, inserted, skipped)
        move_to_ingested(filepath, filename)

        total_inserted += inserted
        total_skipped  += skipped
        processed      += 1

    conn.close()

    if processed == 0:
        log("Nenhum arquivo novo para importar.")
    else:
        log(f"Importação concluída → {processed} arquivo(s)")
        log(f"Total inseridos: {total_inserted} | Total pulados: {total_skipped}")
