# ============================================
# LIVRARIA ALEXANDRIA — PROSPECT (FULL SAFE)
# Language Aware + Cluster Rotation + Editorial Filter
# ============================================

import os
import sys
import time
import uuid
import hashlib
import sqlite3
import requests
import importlib.util
import random
import re

from datetime import datetime


# ============================================
# LOAD CLUSTERS
# ============================================

CURRENT_DIR = os.path.dirname(__file__)

CLUSTERS_PATH = os.path.join(
    CURRENT_DIR,
    "_clusters.py"
)

spec = importlib.util.spec_from_file_location(
    "clusters_module",
    CLUSTERS_PATH
)

clusters_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(clusters_module)

CLUSTERS = clusters_module.CLUSTERS


# ============================================
# DB
# ============================================

SCRIPTS_DIR = os.path.abspath(
    os.path.join(CURRENT_DIR, "..")
)

DATA_DIR = os.path.join(SCRIPTS_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

DB_PATH = os.path.join(DATA_DIR, "books.db")


# ============================================
# CONFIG
# ============================================

OPENLIBRARY_URL = "https://openlibrary.org/search.json"
GOOGLE_BOOKS_URL = "https://www.googleapis.com/books/v1/volumes"

HEARTBEAT_INTERVAL = 30


# ============================================
# EDITORIAL FILTER
# ============================================

EXCLUDED_TERMS = [
    "journal",
    "report",
    "census",
    "proceedings",
    "transactions",
    "bulletin",
    "review",
    "minutes",
    "laws",
    "legislation",
    "court",
    "committee",
    "annual report",
    "executive summary",
    "documents",
]


def is_editorial(title):

    if not title:
        return False

    t = title.lower()

    for term in EXCLUDED_TERMS:
        if term in t:
            return False

    return True


# ============================================
# LANGUAGE HEURISTICS
# ============================================

ISBN_PREFIX_LANG = {
    ("85", "65", "972"): "PT",
    ("84",): "ES",
    ("88",): "IT",
    ("0", "1"): "EN",
}


def detect_lang_by_title(title):

    if not title:
        return None

    t = title.lower()

    patterns = {
        "PT": r"(ção|ções|lh|nh|ã|õ)",
        "ES": r"(ñ|¿|¡)",
        "IT": r"(gli|zione)",
        "FR": r"(é|à|è)",
        "DE": r"\b(der|die|das)\b",
    }

    for lang, pattern in patterns.items():
        if re.search(pattern, t):
            return lang

    return None


def detect_lang_by_isbn(isbn):

    if not isbn:
        return None

    for prefixes, lang in ISBN_PREFIX_LANG.items():
        if isbn.startswith(prefixes):
            return lang

    return None


def resolve_language(api_lang, isbn, title):

    if api_lang:
        return api_lang.upper()

    isbn_lang = detect_lang_by_isbn(isbn)
    if isbn_lang:
        return isbn_lang

    title_lang = detect_lang_by_title(title)
    if title_lang:
        return title_lang

    return "UNKNOWN"


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
# DB SAFE
# ============================================

def get_conn():

    conn = sqlite3.connect(
        DB_PATH,
        timeout=60,
        isolation_level=None
    )

    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")

    return conn


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
# ID
# ============================================

def generate_id(titulo, isbn):

    base = isbn if isbn else titulo

    hash_id = hashlib.sha1(
        base.encode("utf-8")
    ).hexdigest()

    return str(uuid.uuid4())[:8] + hash_id[:16]


# ============================================
# INSERT
# ============================================

def insert_book(data, cluster, idioma_base):

    if not data["titulo"]:
        return False

    if not is_editorial(data["titulo"]):
        return False

    # idioma hard filter
    if data["idioma"] not in [idioma_base, "UNKNOWN"]:
        return False

    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        "SELECT 1 FROM livros WHERE titulo = ?",
        (data["titulo"],)
    )

    if cur.fetchone():
        conn.close()
        return False

    livro_id = generate_id(
        data["titulo"],
        data["isbn"]
    )

    now = datetime.utcnow()

    cur.execute("""
        INSERT INTO livros (
            id, titulo, autor, isbn,
            ano_publicacao, idioma,
            cluster, fonte,
            created_at, updated_at
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

def fetch_google(query):

    beat()

    try:

        res = requests.get(
            GOOGLE_BOOKS_URL,
            params={
                "q": query,
                "maxResults": 20
            },
            timeout=20
        )

        items = res.json().get("items", [])
        books = []

        for item in items:

            info = item.get("volumeInfo", {})

            titulo = info.get("title")
            autores = ", ".join(info.get("authors", []))
            api_lang = info.get("language")

            industry = info.get(
                "industryIdentifiers", []
            )

            isbn = None

            for i in industry:
                if "ISBN" in i["type"]:
                    isbn = i["identifier"]
                    break

            ano = info.get(
                "publishedDate", ""
            )[:4]

            lang_final = resolve_language(
                api_lang,
                isbn,
                titulo
            )

            books.append({
                "titulo": titulo,
                "autor": autores,
                "isbn": isbn,
                "ano": ano,
                "idioma": lang_final,
                "fonte": "google"
            })

        return books

    except Exception as e:
        print(f"[{ts()}] GOOGLE FAIL → {e}")
        return []


def fetch_openlibrary(query):

    beat()

    try:

        res = requests.get(
            OPENLIBRARY_URL,
            params={"q": query, "limit": 20},
            timeout=20
        )

        docs = res.json().get("docs", [])
        books = []

        for d in docs:

            titulo = d.get("title")
            autores = ", ".join(
                d.get("author_name", [])
            )

            langs = d.get("language", [])
            api_lang = langs[0] if langs else None

            isbn_list = d.get("isbn", [])
            isbn = isbn_list[0] if isbn_list else None

            ano = d.get(
                "first_publish_year"
            )

            lang_final = resolve_language(
                api_lang,
                isbn,
                titulo
            )

            books.append({
                "titulo": titulo,
                "autor": autores,
                "isbn": isbn,
                "ano": ano,
                "idioma": lang_final,
                "fonte": "openlibrary"
            })

        return books

    except Exception as e:
        print(f"[{ts()}] OPENLIB FAIL → {e}")
        return []


# ============================================
# CLUSTER ROTATION
# ============================================

def rotate_clusters(idioma):

    idioma = idioma.upper()

    items = list(CLUSTERS.items())
    random.shuffle(items)

    rotated = {}

    for cluster, lang_map in items:

        if idioma not in lang_map:
            continue

        queries = lang_map[idioma].copy()
        random.shuffle(queries)

        rotated[cluster] = queries

    return rotated


# ============================================
# RUN
# ============================================

def run(idioma, pacote):

    idioma = idioma.upper()

    ensure_schema()

    clusters_rotated = rotate_clusters(idioma)

    inseridos = 0

    for cluster, queries in clusters_rotated.items():

        print(f"[{ts()}] CLUSTER → {cluster}")

        for query in queries:

            if inseridos >= pacote:
                print(f"[{ts()}] Pacote atingido — STOP.")
                return

            print(f"[{ts()}] QUERY → {query}")

            books = (
                fetch_google(query) +
                fetch_openlibrary(query)
            )

            for book in books:

                if inseridos >= pacote:
                    print(f"[{ts()}] Pacote atingido — STOP.")
                    return

                if insert_book(book, cluster, idioma):
                    inseridos += 1
                    print(
                        f"[{ts()}] INSERT {inseridos}/{pacote} → {book['titulo']}"
                    )

    print(f"[{ts()}] Fim da prospecção.")


# ============================================
# CLI
# ============================================

if __name__ == "__main__":

    if len(sys.argv) < 3:
        print("Uso: prospect.py <idioma> <pacote>")
        sys.exit(1)

    idioma = sys.argv[1]
    pacote = int(sys.argv[2])

    run(idioma, pacote)
