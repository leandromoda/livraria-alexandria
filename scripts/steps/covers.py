import requests
import time

from core.db import get_conn
from core.logger import log

# =========================
# CONFIG
# =========================

OPENLIBRARY_COVER = "https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg"
GOOGLE_BOOKS_URL = "https://www.googleapis.com/books/v1/volumes"

TIMEOUT = 60


# =========================
# OPENLIBRARY
# =========================

def fetch_openlibrary_cover(isbn):

    if not isbn:
        return None

    url = OPENLIBRARY_COVER.format(isbn=isbn)

    try:
        res = requests.get(url, timeout=TIMEOUT)

        if res.status_code == 200 and res.content:
            return url

    except:
        pass

    return None


# =========================
# GOOGLE
# =========================

def fetch_google_cover(titulo, autor):

    query = f"{titulo} {autor}"

    try:

        res = requests.get(
            GOOGLE_BOOKS_URL,
            params={"q": query, "maxResults": 1},
            timeout=TIMEOUT
        )

        items = res.json().get("items")

        if not items:
            return None

        links = items[0]["volumeInfo"].get(
            "imageLinks", {}
        )

        thumb = (
            links.get("thumbnail")
            or links.get("smallThumbnail")
        )

        if thumb:
            return thumb.replace(
                "http://",
                "https://"
            )

    except:
        pass

    return None


# =========================
# FETCH PENDENTES
# =========================

def fetch_pending(limit):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, titulo, autor, isbn
        FROM livros
        WHERE status_cover = 0
        LIMIT ?
    """, (limit,))

    rows = cur.fetchall()
    conn.close()

    return rows


# =========================
# UPDATE
# =========================

def update_cover(book_id, url):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        UPDATE livros
        SET
            imagem_url = ?,
            status_cover = 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (url, book_id))

    conn.commit()
    conn.close()


# =========================
# RUN
# =========================

def run(pacote=10):

    rows = fetch_pending(pacote)

    if not rows:
        log("Nada pendente para capas.")
        return

    processed = 0
    fallback_used = 0
    failed = 0

    for book_id, titulo, autor, isbn in rows:

        log(f"CAPA → {titulo}")

        # 1️⃣ OpenLibrary
        cover = fetch_openlibrary_cover(isbn)

        # 2️⃣ Google fallback
        if not cover:

            cover = fetch_google_cover(
                titulo,
                autor
            )

            if cover:
                fallback_used += 1

        # 3️⃣ Falha
        if not cover:

            failed += 1
            log(f"SEM CAPA → {titulo}")
            continue

        update_cover(book_id, cover)

        processed += 1
        log(f"CAPA OK → {titulo}")

        time.sleep(0.2)

    log(
        f"CAPAS CONCLUÍDO → {processed} | fallback {fallback_used} | falhas {failed}"
    )
