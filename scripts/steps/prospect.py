# ============================================
# LIVRARIA ALEXANDRIA — SCRIPT 1
# PROSPECÇÃO MULTI-FONTE INCREMENTAL
# Estratégia B + Estado Salvável
# ============================================

import os
import time
import sqlite3
import requests
from datetime import datetime

from steps._clusters import CLUSTERS


# ============================================
# CONFIG
# ============================================

DB_PATH = os.path.join("data", "livros.db")

OPENLIBRARY_URL = "https://openlibrary.org/search.json"
GOOGLE_BOOKS_URL = "https://www.googleapis.com/books/v1/volumes"

HEARTBEAT_INTERVAL = 30


# ============================================
# HEARTBEAT
# ============================================

_last_event = time.time()


def beat(msg="Script ativo…"):
    global _last_event
    now = time.time()

    if now - _last_event >= HEARTBEAT_INTERVAL:
        print(f"[{ts()}] {msg} último evento há {int(now - _last_event)}s")

    _last_event = now()


def ts():
    return datetime.now().strftime("%H:%M:%S")


# ============================================
# DB
# ============================================

def get_conn():
    os.makedirs("data", exist_ok=True)

    return sqlite3.connect(DB_PATH)


def ensure_schema():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS livros (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        titulo TEXT,
        autor TEXT,
        isbn TEXT,
        ano INTEGER,
        idioma TEXT,
        fonte TEXT,
        criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()
    conn.close()


def count_books():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM livros")
    total = cur.fetchone()[0]

    conn.close()
    return total


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


def insert_book(data):

    if exists(data["titulo"]):
        print(f"[{ts()}] SKIP duplicado → {data['titulo']}")
        return False

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO livros
        (titulo, autor, isbn, ano, idioma, fonte)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        data["titulo"],
        data["autor"],
        data["isbn"],
        data["ano"],
        data["idioma"],
        data["fonte"]
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

    inseridos_total = count_books()
    meta_execucao = inseridos_total + pacote

    print(f"[{ts()}] Já inseridos → {inseridos_total}")
    print(f"[{ts()}] Meta desta execução → {meta_execucao}")

    inseridos_exec = inseridos_total

    for cluster, queries in CLUSTERS.items():

        print(f"[{ts()}] CLUSTER → {cluster}")

        for query in queries:

            if inseridos_exec >= meta_execucao:
                print(f"[{ts()}] Pacote atingido — STOP.")
                return

            print(f"[{ts()}] QUERY → {query}")

            ol_books = fetch_openlibrary(query, idioma)
            g_books = fetch_google(query, idioma)

            for book in ol_books + g_books:

                if inseridos_exec >= meta_execucao:
                    print(f"[{ts()}] Pacote atingido — STOP.")
                    return

                if insert_book(book):
                    inseridos_exec += 1
                    print(
                        f"[{ts()}] INSERT {inseridos_exec}/{meta_execucao} → {book['titulo']}"
                    )

    print(f"[{ts()}] Fim da prospecção.")


# ============================================
# ENTRYPOINT TESTE DIRETO
# ============================================

if __name__ == "__main__":
    run("por", 10)
