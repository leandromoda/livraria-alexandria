# ============================================================
# STEP 2 — DESCRIPTION ENRICHMENT
# Livraria Alexandria
#
# Busca descrição no Google Books para todos os livros
# que ainda não possuem descricao preenchida.
# Sem LLM. Apenas REST API.
# Usa GOOGLE_BOOKS_API_KEY se disponível em scripts/.env
# ============================================================

import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv


# =========================
# ENV
# =========================

_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=_ENV_PATH)

GOOGLE_BOOKS_API_KEY = os.getenv("GOOGLE_BOOKS_API_KEY", "")


# =========================
# CONFIG
# =========================

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

DB_PATH = os.path.join(DATA_DIR, "books.db")

GOOGLE_BOOKS_URL = "https://www.googleapis.com/books/v1/volumes"

REQUEST_DELAY = 0.3
MIN_DESC_LENGTH = 50


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
    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=60000")

    return conn


# =========================
# FETCH PENDING
# =========================

def fetch_pending(conn, limit):

    cur = conn.cursor()

    cur.execute("""
        SELECT id, titulo, autor
        FROM livros
        WHERE descricao IS NULL
           OR TRIM(descricao) = ''
        LIMIT ?
    """, (limit,))

    return cur.fetchall()


# =========================
# GOOGLE BOOKS LOOKUP
# =========================

def fetch_descricao(titulo, autor):

    query = f"{titulo} {autor}".strip()

    time.sleep(REQUEST_DELAY)

    params = {"q": query, "maxResults": 3}

    if GOOGLE_BOOKS_API_KEY:
        params["key"] = GOOGLE_BOOKS_API_KEY

    try:
        res = requests.get(
            GOOGLE_BOOKS_URL,
            params=params,
            timeout=15,
        )

        if res.status_code != 200:
            log(f"[ENRICH] HTTP {res.status_code} → {titulo}")
            return None

        items = res.json().get("items", [])

        for item in items:
            info = item.get("volumeInfo", {})
            descricao = info.get("description")
            if descricao and len(descricao.strip()) >= MIN_DESC_LENGTH:
                return descricao.strip()

    except Exception as e:
        log(f"[ENRICH] Falha Google Books → {e}")

    return None


# =========================
# UPDATE
# =========================

def update_descricao(conn, livro_id, descricao):

    cur = conn.cursor()

    cur.execute("""
        UPDATE livros
        SET descricao  = ?,
            updated_at = ?
        WHERE id = ?
    """, (descricao, datetime.utcnow().isoformat(), livro_id))

    conn.commit()


# =========================
# RUN
# =========================

def run(pacote=500):

    log("Iniciando Description Enrichment...")

    if GOOGLE_BOOKS_API_KEY:
        log("[ENRICH] Usando Google Books API Key")
    else:
        log("[ENRICH] AVISO: sem API key — rate limit reduzido")

    if not os.path.exists(DB_PATH):
        log("Banco não encontrado. Execute o step 1 primeiro.")
        return

    conn = get_conn()

    rows = fetch_pending(conn, pacote)

    if not rows:
        log("Nenhum livro pendente de enriquecimento.")
        conn.close()
        return

    total    = len(rows)
    enriched = 0
    failed   = 0

    log(f"{total} livros sem descrição encontrados")

    for i, row in enumerate(rows, start=1):

        livro_id = row["id"]
        titulo   = row["titulo"]
        autor    = row["autor"] or ""

        log(f"[{i}/{total}] {titulo}")

        descricao = fetch_descricao(titulo, autor)

        if descricao:
            update_descricao(conn, livro_id, descricao)
            enriched += 1
            log(f"[OK] → {titulo}")
        else:
            failed += 1
            log(f"[--] Sem descrição → {titulo}")

    conn.close()

    log(f"Finalizado — OK: {enriched} | Sem descrição: {failed}")