# ============================================================
# STEP 3 — OFFER RESOLVER
# Livraria Alexandria
#
# Gera URLs de afiliado a partir de lookup_query + marketplace
# ============================================================

import os
import sqlite3
import time
from pathlib import Path
from urllib.parse import quote_plus


# =========================
# CONFIG
# =========================

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "books.db")


# =========================
# LOG
# =========================

def log(msg):
    now = time.strftime("%H:%M:%S")
    print(f"[{now}] {msg}")


# =========================
# DB CONNECTION
# =========================

def get_conn():

    conn = sqlite3.connect(DB_PATH, timeout=30)

    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    return conn


# =========================
# URL BUILDERS
# =========================

def build_amazon_url(query: str) -> str:
    q = quote_plus(query)
    return f"https://www.amazon.com.br/s?k={q}"


def build_mercadolivre_url(query: str) -> str:
    q = quote_plus(query)
    return f"https://lista.mercadolivre.com.br/{q}"


def resolve_offer(marketplace: str, lookup_query: str):

    if not lookup_query:
        return None

    if marketplace == "amazon":
        return build_amazon_url(lookup_query)

    if marketplace == "mercado_livre":
        return build_mercadolivre_url(lookup_query)

    return None


# =========================
# FETCH PENDING
# =========================

def fetch_pending(conn, idioma, limit):

    cur = conn.cursor()

    cur.execute("""
        SELECT id, titulo, autor, marketplace, lookup_query
        FROM livros
        WHERE idioma = ?
          AND lookup_query IS NOT NULL
          AND (offer_status IS NULL OR offer_status = 0)
        LIMIT ?
    """, (idioma, limit))

    return cur.fetchall()


# =========================
# UPDATE
# =========================

def update_offer(conn, book_id, offer_url, success):

    cur = conn.cursor()

    cur.execute("""
        UPDATE livros
        SET offer_url    = ?,
            offer_status = ?,
            updated_at   = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (offer_url, 1 if success else -1, book_id))

    conn.commit()


# =========================
# RUN
# =========================

def run(idioma, pacote):

    log("Iniciando Offer Resolver...")

    conn = get_conn()

    rows = fetch_pending(conn, idioma, pacote)

    total    = len(rows)
    resolved = 0
    failed   = 0

    log(f"{total} seeds pendentes")

    for row in rows:

        book_id, titulo, autor, marketplace, lookup_query = row

        try:
            offer_url = resolve_offer(marketplace, lookup_query)

            if offer_url:
                update_offer(conn, book_id, offer_url, True)
                resolved += 1
            else:
                update_offer(conn, book_id, None, False)
                failed += 1

        except Exception as e:
            log(f"Erro → '{titulo}': {e}")
            update_offer(conn, book_id, None, False)
            failed += 1

    conn.close()

    log(f"Resolvidas: {resolved} | Falhas: {failed}")
    log("Offer Resolver finalizado.")
