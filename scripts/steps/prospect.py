# ============================================
# LIVRARIA ALEXANDRIA — PROSPECT
# Compatível com books.db (schema staging)
# ID Strategy: UUID v4 + fallback hash título
# ============================================

import os
import time
import uuid
import hashlib
import sqlite3
import requests

from datetime import datetime
from steps._clusters import CLUSTERS


# ============================================
# CONFIG
# ============================================

DB_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "data",
    "books.db"
)

OPENLIBRARY_URL = "https://openlibrary.org/search.json"
GOOGLE_BOOKS_URL = "https://www.googleapis.com/books/v1/volumes"

HEARTBEAT_INTERVAL = 30


# ============================================
# HEARTBEAT
# ============================================

_last_event = time.time()


def ts():
    return datetime.now().strftime("%H:%M:%S")


def beat(msg="Script ativo…"):
    global _last_event

    now_ts = time.time()

    if now_ts - _last_event >= HEARTBEAT_INTERVAL:
        print(
            f"[{ts()}] {msg} último evento há {int(now_ts - _last_event)}s"
        )

    _last_event = now_ts


# ============================================
# DB
# ============================================

def get_conn():
    return sqlite3.connect(DB_PATH)


def ensure_schema():

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS livros (
        id TEXT PRIMARY KEY,
        titulo TEXT NOT NULL,
        slug TEXT UNIQUE,
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
        created_at DATETIME,
        updated_at DATETIME
    )
    """)

    conn.commit()
    conn.close()


# ============================================
# ID STRATEGY
# ============================================

def generate_id(titulo, isbn):

    if isbn:
        base = isbn
    else:
        base = titulo

    hash_id = hashlib.sha1(
        base.encode("utf-8")
    ).hexdigest()

    return str(uuid.uuid4())[:8] + hash_id[:16]


# ============================================
# INSERT
# ============================================

def exists(titulo):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        "SELECT 1 FROM livros WHERE titulo = ? LIMIT 1",
        (titulo,)
    )

    res = cur.fetchone()
    conn.close()

    return res is not None


def insert_book(data, cluster):

    if exists(data["titulo"]):
        print(f"[{ts()}] SKIP duplicado → {data['titulo']}")
        return False

    livro_id = generate_id(
        data["titulo"],
        data["isbn"]
    )

    now = datetime.utcnow()

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO livros (
            id,
            titulo,
            autor,
            isbn,
            ano_publicacao,
            idioma,
            cluster,
            fonte,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        livro_id,
        data["titulo"],
        data["autor"],
        data["isbn"],
        data["ano"],
        data["idioma"],
        cluster,
        data["fonte"],
        now,
        now
    ))

    conn.commit()
    conn.close()

    return True


# ============================================
# FETCHERS
# ============================================

def fetch_openlibrary(query, idioma, limit=20):

    beat()

    try:
        res = requests.get(
            OPENLIBRARY_URL,
            params={
                "q": query,
                "language": idioma,
                "limit": limit
            },
            timeout=20
        )

        docs = res.json().get("docs", [])

        books = []

        for d in docs:

            titulo = d.get("title")
            autores = ", ".join(d.get("author_name", []))

            isbn_list = d.get("isbn", [])
            isbn = isbn_list[0] if isbn_list else None

            ano = d.get("first_publish_year")

            if not titulo:
                continue

            books.append({
                "titulo": titulo,
                "autor": autores,
                "isbn": isbn,
                "ano": ano,
                "idioma": idioma,
                "fonte": "openlibrary"
            })

        return books

    except Exception as e:
        print(f"[{ts()}] ERRO OL → {e}")
        return []


def fetch_google(query, idioma, limit=20):

    beat()

    try:
        res = requests.get(
            GOOGLE_BOOKS_URL,
            params={
                "q": query,
                "maxResults": limit,
                "langRestrict": idioma
            },
            timeout=20
        )

        items = res.json().get("items", [])

        books = []

        for item in items:

            info = item.get("volumeInfo", {})

            titulo = info.get("title")
            autores = ", ".join(info.get("authors", []))

            industry = info.get("industryIdentifiers", [])

            isbn = None
            for i in industry:
                if "ISBN" in i["type"]:
                    isbn = i["identifier"]
                    break

            ano = info.get("publishedDate", "")[:4]

            if not titulo:
                continue

            books.append({
                "titulo": titulo,
                "autor": autores,
                "isbn": isbn,
                "ano": ano,
                "idioma": idioma,
                "fonte": "google"
            })

        return books

    except Exception as e:
        print(f"[{ts()}] ERRO GOOGLE → {e}")
        return []


# ============================================
# RUN
# ============================================

def run(idioma, pacote):

    ensure_schema()

    inseridos = 0

    for cluster, queries in CLUSTERS.items():

        print(f"[{ts()}] CLUSTER → {cluster}")

        for query in queries:

            if inseridos >= pacote:
                print(f"[{ts()}] Pacote atingido — STOP.")
                return

            print(f"[{ts()}] QUERY → {query}")

            ol_books = fetch_openlibrary(query, idioma)
            g_books = fetch_google(query, idioma)

            for book in ol_books + g_books:

                if inseridos >= pacote:
                    print(f"[{ts()}] Pacote atingido — STOP.")
                    return

                if insert_book(book, cluster):
                    inseridos += 1
                    print(
                        f"[{ts()}] INSERT {inseridos}/{pacote} → {book['titulo']}"
                    )

    print(f"[{ts()}] Fim da prospecção.")


# ============================================
# ENTRYPOINT
# ============================================

if __name__ == "__main__":
    run("pt", 10)
