import re
import unicodedata
import os
import sqlite3

from datetime import datetime


# =========================
# DB PATH (ALINHADO PROSPECT)
# =========================

DB_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "data",
    "books.db"
)


def get_conn():
    return sqlite3.connect(DB_PATH)


# =========================
# LOGGER SIMPLES
# =========================

def log(msg):
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {msg}")


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
        "SELECT 1 FROM livros WHERE slug = ? LIMIT 1",
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
        FROM livros
        WHERE status_slug = 0
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

    now = datetime.utcnow()

    cur.execute("""
        UPDATE livros
        SET slug = ?,
            status_slug = 1,
            updated_at = ?
        WHERE id = ?
    """, (slug, now, book_id))

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
