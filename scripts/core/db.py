import sqlite3
from pathlib import Path

# path absoluto garantido
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "books.db"


def get_conn():

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)

    ensure_schema(conn)

    return conn


# =========================
# SCHEMA
# =========================

def ensure_schema(conn):

    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS livros (

        id TEXT PRIMARY KEY,

        titulo TEXT,
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

        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """)

    conn.commit()
