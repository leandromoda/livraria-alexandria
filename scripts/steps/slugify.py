import re
import unicodedata

from core.db import get_conn
from core.logger import log

# =========================
# SLUG BASE
# =========================

def base_slug(text):

    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()

    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text)

    return text.strip("-")


# =========================
# CHECK COLISÃO
# =========================

def slug_exists(slug):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        "SELECT 1 FROM books WHERE slug = ? LIMIT 1",
        (slug,)
    )

    exists = cur.fetchone() is not None

    conn.close()

    return exists


def generate_unique_slug(titulo):

    base = base_slug(titulo)

    slug = base
    counter = 2

    while slug_exists(slug):

        slug = f"{base}-{counter}"
        counter += 1

    return slug


# =========================
# FETCH PENDENTES
# =========================

def fetch_pending(limit):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, titulo
        FROM books
        WHERE slugger = 0
        LIMIT ?
    """, (limit,))

    rows = cur.fetchall()
    conn.close()

    return rows


# =========================
# UPDATE
# =========================

def update_slug(book_id, slug):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        UPDATE books
        SET slug = ?,
            slugger = 1
        WHERE id = ?
    """, (slug, book_id))

    conn.commit()
    conn.close()


# =========================
# RUN
# =========================

def run(pacote=10):

    rows = fetch_pending(pacote)

    if not rows:
        log("Nada pendente para slug.")
        return

    processed = 0

    for book_id, titulo in rows:

        slug = generate_unique_slug(titulo)

        update_slug(book_id, slug)

        processed += 1

        log(f"SLUG → {titulo} → {slug}")

    log(f"SLUG CONCLUÍDO → {processed}")
