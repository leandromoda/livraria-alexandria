# ============================================================
# STEP 0 — OFFER SEED IMPORT
# Livraria Alexandria
#
# BOOTSTRAP SAFE:
# - cria database
# - cria tabela livros
# - auto migration colunas
# ============================================================

import json
import os
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
# TABLE BOOTSTRAP
# =========================

def ensure_tables(conn):

    log("Verificando tabela livros (bootstrap)…")

    conn.execute("""
    CREATE TABLE IF NOT EXISTS livros (

        id TEXT PRIMARY KEY,

        titulo TEXT NOT NULL,
        slug TEXT,
        autor TEXT,
        descricao TEXT,
        isbn TEXT,
        ano_publicacao INTEGER,
        imagem_url TEXT,

        idioma TEXT,
        cluster TEXT,
        fonte TEXT,

        status_slug INTEGER DEFAULT 0,
        status_dedup INTEGER DEFAULT 0,
        status_synopsis INTEGER DEFAULT 0,
        status_review INTEGER DEFAULT 0,
        status_cover INTEGER DEFAULT 0,
        status_publish INTEGER DEFAULT 0,

        is_book INTEGER DEFAULT 1,
        editorial_score INTEGER DEFAULT 0,

        created_at DATETIME,
        updated_at DATETIME
    )
    """)

    conn.commit()


# =========================
# AUTO MIGRATION
# =========================

REQUIRED_COLUMNS = {
    "lookup_query": "TEXT",
    "marketplace": "TEXT",
    "offer_url": "TEXT",
    "offer_status": "INTEGER DEFAULT 0",
    "categoria": "TEXT",
    "cluster_id": "INTEGER",
    "nacionalidade_id": "INTEGER",
    "popularidade_id": "INTEGER",
}


def ensure_schema(conn):

    log("Verificando schema (auto-migration)…")

    cur = conn.cursor()

    cur.execute("PRAGMA table_info(livros)")
    existing = {row[1] for row in cur.fetchall()}

    for column, definition in REQUIRED_COLUMNS.items():

        if column not in existing:

            log(f"Criando coluna: {column}")

            for attempt in range(5):
                try:
                    cur.execute(
                        f"ALTER TABLE livros ADD COLUMN {column} {definition}"
                    )
                    conn.commit()
                    break

                except sqlite3.OperationalError as e:
                    if "locked" in str(e):
                        log("DB locked — retry...")
                        time.sleep(1.5)
                    else:
                        raise


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

    titulo = seed.get("titulo")
    autor = seed.get("autor")
    idioma = seed.get("idioma")
    categoria = seed.get("categoria")
    marketplace = seed.get("marketplace")
    lookup_query = seed.get("lookup_query")

    if not titulo or not lookup_query:
        return False

    cur = conn.cursor()

    cur.execute("""
        SELECT id FROM livros
        WHERE titulo = ?
        AND IFNULL(autor,'') = IFNULL(?, '')
        LIMIT 1
    """, (titulo, autor))

    if cur.fetchone():
        return False

    cur.execute("""
        INSERT INTO livros (
            id,
            titulo,
            autor,
            cluster,
            fonte,
            idioma,

            lookup_query,
            marketplace,
            offer_status,
            categoria,
            cluster_id,
            nacionalidade_id,
            popularidade_id,
            ano_publicacao,

            created_at,
            updated_at
        )
        VALUES (
            lower(hex(randomblob(12))),
            ?, ?, ?, 'offer_seed', ?,
            ?, ?, 0, ?, ?, ?, ?, ?,
            ?, ?
        )
    """, (
        titulo,
        autor,
        categoria,
        idioma,
        lookup_query,
        marketplace,
        categoria,
        seed.get("cluster_id"),
        seed.get("nacionalidade_id"),
        seed.get("popularidade_id"),
        seed.get("ano_sorteado"),
        now,
        now
    ))

    return True


# =========================
# RUN
# =========================

def run():

    log("Iniciando Offer Seed Import...")

    conn = get_conn()

    ensure_tables(conn)   # <<< NOVO BOOTSTRAP
    ensure_schema(conn)

    seeds = load_seeds()

    if not seeds:
        log("Nenhuma seed encontrada.")
        return

    inserted = 0
    skipped = 0

    for seed in seeds:

        try:
            if insert_seed(conn, seed):
                inserted += 1
            else:
                skipped += 1

        except Exception as e:
            log(f"Erro ao inserir seed: {e}")

    conn.commit()
    conn.close()

    log(f"Seeds inseridas: {inserted}")
    log(f"Seeds ignoradas: {skipped}")
    log("Offer Seed Import finalizado.")