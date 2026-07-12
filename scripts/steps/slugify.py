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


def generate_unique_slug(conn, titulo, book_id=None):

    base = base_slug(titulo)

    # Títulos 100% não-ASCII (cirílico, grego, CJK, árabe...) viram string vazia
    # após o encode('ascii','ignore') em base_slug. Um slug vazio deixa o livro
    # permanentemente impublicável (o Quality Gate exige slug) e invisível ao
    # reprocessamento. Fallback determinístico e não-vazio baseado no id do livro.
    if not base:
        base = f"livro-{book_id[:12]}" if book_id else "livro"

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

    # Slugs são language-agnostic — todos os livros precisam de slug
    # independente do idioma. Filtrar por idioma aqui causaria Progresso=0
    # para livros de outros idiomas que o autopilot nunca processa.
    #
    # Inclui também livros já marcados (status_slug=1) porém com slug vazio/NULL:
    # registros presos por um slug vazio antigo (título não-ASCII) precisam ser
    # curados — do contrário nunca reentram no processamento (status_slug já = 1).
    cur.execute("""
        SELECT id, titulo
        FROM livros
        WHERE status_slug = 0
           OR slug IS NULL
           OR slug = ''
        LIMIT ?
    """, (limit,))

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
        log("Nada pendente para slug.")
        conn.close()
        return

    processed = 0
    total     = len(rows)

    for i, (book_id, titulo) in enumerate(rows, start=1):

        slug = generate_unique_slug(conn, titulo, book_id)
        update_slug(conn, book_id, slug)
        processed += 1
        log(f"[SLUG][{i:03d}/{total:03d}] → {titulo} | {slug}")

    conn.close()

    log(f"[SLUG] Finalizado | Slugs gerados: {processed}")
