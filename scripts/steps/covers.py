# ============================================================
# STEP 8 — COVERS
# Livraria Alexandria
#
# Cadeia de fallback:
#   1. Amazon (URL direta por ISBN)
#   2. Google Books API
#   3. OpenLibrary
#
# status_cover:
#   0 = pendente
#   1 = capa encontrada
#   2 = sem capa (não bloqueia o pipeline)
# ============================================================

import os
import sqlite3
import time
from datetime import datetime

import requests
from dotenv import load_dotenv


# =========================
# CONFIG
# =========================

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH  = os.path.join(DATA_DIR, "books.db")

load_dotenv(os.path.join(BASE_DIR, ".env"))
GOOGLE_BOOKS_API_KEY = os.getenv("GOOGLE_BOOKS_API_KEY", "")

AMAZON_COVER      = "https://images-na.ssl-images-amazon.com/images/P/{isbn}.jpg"
GOOGLE_BOOKS_URL  = "https://www.googleapis.com/books/v1/volumes"
OPENLIBRARY_COVER = "https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg"

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; LibraryBot/1.0)"}
TIMEOUT = 15
MIN_IMAGE_BYTES = 5000   # abaixo disso = placeholder


# =========================
# LOGGER
# =========================

def log(msg):
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {msg}", flush=True)


# =========================
# DB
# =========================

def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


# =========================
# FETCHERS
# =========================

def fetch_amazon_cover(isbn):
    """URL direta da Amazon por ISBN — sem API key."""
    if not isbn:
        return None
    url = AMAZON_COVER.format(isbn=isbn)
    try:
        res = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if res.status_code == 200 and len(res.content) > MIN_IMAGE_BYTES:
            return url
    except Exception:
        pass
    return None


def fetch_google_cover(titulo, autor, isbn=None):
    """Google Books API — busca por ISBN primeiro, depois título+autor."""
    try:
        query = f"isbn:{isbn}" if isbn else f"{titulo} {autor}"
        params = {"q": query, "maxResults": 1}
        if GOOGLE_BOOKS_API_KEY:
            params["key"] = GOOGLE_BOOKS_API_KEY

        res = requests.get(GOOGLE_BOOKS_URL, params=params,
                           headers=HEADERS, timeout=TIMEOUT)
        items = res.json().get("items")
        if not items:
            return None

        links = items[0]["volumeInfo"].get("imageLinks", {})
        thumb = (links.get("large")
                 or links.get("medium")
                 or links.get("thumbnail")
                 or links.get("smallThumbnail"))

        if thumb:
            # Força HTTPS e remove zoom baixo
            thumb = thumb.replace("http://", "https://")
            thumb = thumb.replace("&zoom=1", "&zoom=0")
            return thumb

    except Exception:
        pass
    return None


def fetch_openlibrary_cover(isbn):
    """OpenLibrary — fallback final, checa tamanho para evitar placeholder."""
    if not isbn:
        return None
    url = OPENLIBRARY_COVER.format(isbn=isbn)
    try:
        res = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if res.status_code == 200 and len(res.content) > MIN_IMAGE_BYTES:
            return url
    except Exception:
        pass
    return None


# =========================
# FETCH PENDING
# =========================

def fetch_pending(conn, idioma, limit):
    cur = conn.cursor()
    cur.execute("""
        SELECT id, titulo, autor, isbn
        FROM livros
        WHERE status_cover = 0
          AND idioma = ?
        ORDER BY priority_score DESC, created_at ASC
        LIMIT ?
    """, (idioma, limit))
    return cur.fetchall()


# =========================
# UPDATE
# =========================

def update_cover(conn, book_id, url, status):
    cur = conn.cursor()
    cur.execute("""
        UPDATE livros
        SET imagem_url   = ?,
            status_cover = ?,
            updated_at   = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (url, status, book_id))
    conn.commit()


# =========================
# RUN
# =========================

def run(idioma, pacote=10):

    conn = get_conn()
    rows = fetch_pending(conn, idioma, pacote)

    if not rows:
        log(f"Nada pendente para capas [{idioma}].")
        conn.close()
        return

    ok = 0
    amazon_used = 0
    google_used = 0
    openlibrary_used = 0
    failed = 0
    total  = len(rows)

    for i, (book_id, titulo, autor, isbn) in enumerate(rows, start=1):

        log(f"[CAPA][{i:03d}/{total:03d}] → {titulo}")

        cover  = None
        source = None

        # 1. Amazon
        cover = fetch_amazon_cover(isbn)
        if cover:
            source = "amazon"
            amazon_used += 1

        # 2. Google Books
        if not cover:
            cover = fetch_google_cover(titulo, autor, isbn)
            if cover:
                source = "google"
                google_used += 1

        # 3. OpenLibrary
        if not cover:
            cover = fetch_openlibrary_cover(isbn)
            if cover:
                source = "openlibrary"
                openlibrary_used += 1

        if cover:
            update_cover(conn, book_id, cover, status=1)
            ok += 1
            log(f"[CAPA] OK [{source}] → {titulo}")
        else:
            update_cover(conn, book_id, None, status=2)
            failed += 1
            log(f"[CAPA] SEM CAPA → {titulo}")

        time.sleep(0.3)

    conn.close()

    log(f"[CAPA] Finalizado | OK={ok} amazon={amazon_used} google={google_used} "
        f"openlibrary={openlibrary_used} | sem_capa={failed}")
