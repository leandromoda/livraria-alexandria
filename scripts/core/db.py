import sqlite3
from pathlib import Path

DB_PATH = Path("scripts/data/books.db")


def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_db():

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS books (

        id TEXT PRIMARY KEY,

        titulo TEXT,
        autor TEXT,

        isbn TEXT,
        ano_publicacao INTEGER,

        descricao TEXT,
        descricao_revisada TEXT,

        slug TEXT,

        imagem_url TEXT,

        idioma TEXT,

        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

        -- estado pipeline
        prospectado INTEGER DEFAULT 0,
        slugger INTEGER DEFAULT 0,
        dedup INTEGER DEFAULT 0,
        sinopse INTEGER DEFAULT 0,
        revisado INTEGER DEFAULT 0,
        capa INTEGER DEFAULT 0,
        publicado INTEGER DEFAULT 0
    );
    """)

    conn.commit()
    conn.close()