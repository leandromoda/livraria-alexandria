# ============================================================
# STEP 1 — OFFER SEED IMPORT
# Livraria Alexandria
#
# BOOTSTRAP SAFE — gera banco do zero se necessário
# Schema canônico definido aqui. Todos os outros scripts
# dependem deste schema.
#
# Campos separados:
#   descricao → texto bruto vindo de APIs externas
#   sinopse   → texto gerado pelo pipeline LLM
# ============================================================

import json
import os
import re
import sqlite3
import time
from datetime import datetime


# =========================
# CONFIG
# =========================

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

DB_PATH = os.path.join(DATA_DIR, "books.db")
SEED_PATH = os.path.join(DATA_DIR, "offer_seeds.json")


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
    ("84",): "ES",
    ("88",): "IT",
    ("0", "1"): "EN",
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
        descricao       TEXT,   -- texto bruto vindo de APIs externas
        sinopse         TEXT,   -- sinopse editorial gerada pelo pipeline

        -- Metadados de curadoria
        is_book             INTEGER DEFAULT 1,
        editorial_score     INTEGER DEFAULT 0,
        is_publishable      INTEGER DEFAULT 1,

        -- Oferta / afiliado
        lookup_query        TEXT,
        marketplace         TEXT,
        offer_url           TEXT,
        offer_status        INTEGER DEFAULT 0,
        preco               REAL,
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
        status_publish      INTEGER DEFAULT 0,

        -- Supabase sync
        supabase_id         TEXT,

        created_at      DATETIME,
        updated_at      DATETIME
    )
    """)

    conn.commit()
    log("Schema canônico verificado.")


# =========================
# LOAD SEEDS
# =========================

def load_seeds():

    if not os.path.exists(SEED_PATH):
        log("offer_seeds.json não encontrado.")
        return []

    with open(SEED_PATH, "r", encoding="utf-8") as f:
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
        log(f"[SKIP] Filtro editorial → {titulo}")
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
            ?, ?, 0,
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
# RUN
# =========================

def run():

    log("Iniciando Offer Seed Import...")

    conn = get_conn()

    ensure_tables(conn)

    seeds = load_seeds()

    if not seeds:
        log("Nenhuma seed encontrada.")
        conn.close()
        return

    counts = {"inserted": 0, "duplicate": 0, "filtered": 0, "invalid": 0}

    for seed in seeds:
        try:
            result = insert_seed(conn, seed)
            counts[result] = counts.get(result, 0) + 1
        except Exception as e:
            log(f"Erro ao inserir seed: {e}")

    conn.commit()
    conn.close()

    log(f"Inseridas:  {counts['inserted']}")
    log(f"Duplicatas: {counts['duplicate']}")
    log(f"Filtradas:  {counts['filtered']}")
    log(f"Inválidas:  {counts['invalid']}")
    log("Offer Seed Import finalizado.")
