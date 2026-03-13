# ============================================================
# STEP 4 — SLUGIFY
# Livraria Alexandria
# ============================================================

import os
import re
import sqlite3
import unicodedata
from datetime import datetime


# =========================
# CONFIG
# =========================

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "books.db")


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

    conn = sqlite3.connect(DB_PATH, timeout=60)

    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=60000")

    return conn


# =========================
# SLUG
# =========================

def base_slug(text):

    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text)

    return text.strip("-")


def slug_exists(conn, slug):

    cur = conn.cursor()
    cur.execute("SELECT 1 FROM livros WHERE slug = ? LIMIT 1", (slug,))
    return cur.fetchone() is not None


def generate_unique_slug(conn, titulo):

    base = base_slug(titulo)
    slug = base
    counter = 2

    while slug_exists(conn, slug):
        slug = f"{base}-{counter}"
        counter += 1

    return slug


# =========================
# FETCH
# =========================

def fetch_pending(conn, idioma, limit):

    cur = conn.cursor()

    cur.execute("""
        SELECT id, titulo
        FROM livros
        WHERE status_slug = 0
          AND idioma = ?
        LIMIT ?
    """, (idioma, limit))

    return cur.fetchall()


# =========================
# UPDATE
# =========================

def update_slug(conn, book_id, slug):

    cur = conn.cursor()

    cur.execute("""
        UPDATE livros
        SET slug = ?,
            status_slug = 1,
            updated_at = ?
        WHERE id = ?
    """, (slug, datetime.utcnow().isoformat(), book_id))

    conn.commit()


# =========================
# RUN
# =========================

def run(idioma, pacote=10):

    conn = get_conn()

    rows = fetch_pending(conn, idioma, pacote)

    if not rows:
        log(f"Nada pendente para slug [{idioma}].")
        conn.close()
        return

    processed = 0

    for book_id, titulo in rows:

        slug = generate_unique_slug(conn, titulo)
        update_slug(conn, book_id, slug)
        processed += 1
        log(f"SLUG → {titulo} → {slug}")

    conn.close()

    log(f"Slugs gerados: {processed}")
