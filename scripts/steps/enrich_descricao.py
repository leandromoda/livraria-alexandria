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
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
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
TITLE_SIMILARITY_THRESHOLD = 0.5  # mínimo de similaridade entre título buscado e retornado


# =========================
# TITLE VALIDATION
# =========================

def _normalize_title(s: str) -> str:
    """Normaliza título para comparação: NFKD → ASCII → minúsculas."""
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode("ascii").lower().strip()


def _title_matches(expected: str, returned: str) -> bool:
    """
    Retorna True se o título retornado pelo Google Books é compatível com o
    título que estava sendo buscado. Evita aceitar descrições de livros errados.

    Critérios (qualquer um satisfatório):
    1. O título buscado é substring do título retornado (ex: "Sapiens" em "Sapiens: A Brief History")
    2. O título retornado é substring do título buscado (ex: edição abreviada)
    3. Similaridade SequenceMatcher >= TITLE_SIMILARITY_THRESHOLD
    """
    n_expected = _normalize_title(expected)
    n_returned = _normalize_title(returned)

    if not n_returned:
        return False

    if n_expected in n_returned or n_returned in n_expected:
        return True

    ratio = SequenceMatcher(None, n_expected, n_returned).ratio()
    return ratio >= TITLE_SIMILARITY_THRESHOLD


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
        WHERE status_descricao = 0
        LIMIT ?
    """, (limit,))

    return cur.fetchall()


# =========================
# GOOGLE BOOKS LOOKUP
# =========================

def fetch_descricao(titulo, autor):

    query = f"{titulo} {autor}".strip()

    time.sleep(REQUEST_DELAY)

    params = {"q": query, "maxResults": 5}

    if GOOGLE_BOOKS_API_KEY:
        params["key"] = GOOGLE_BOOKS_API_KEY

    for tentativa in range(2):
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
                returned_title = info.get("title", "")

                # Rejeita resultado cujo título não corresponde ao livro buscado
                if not _title_matches(titulo, returned_title):
                    continue

                descricao = info.get("description")
                if descricao and len(descricao.strip()) >= MIN_DESC_LENGTH:
                    return descricao.strip()

            return None  # sem resultado compatível — não adianta retry

        except requests.RequestException as e:
            log(f"[ENRICH] Falha de rede (tentativa {tentativa + 1}/2) → {e}")
            if tentativa == 0:
                time.sleep(3)

        except Exception as e:
            log(f"[ENRICH] Erro inesperado → {e}")
            return None

    return None


# =========================
# UPDATE
# =========================

def update_descricao(conn, livro_id, descricao, status_descricao):

    cur = conn.cursor()

    cur.execute("""
        UPDATE livros
        SET descricao         = COALESCE(?, descricao),
            status_descricao  = ?,
            updated_at        = ?
        WHERE id = ?
    """, (descricao, status_descricao, datetime.utcnow().isoformat(), livro_id))

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
            update_descricao(conn, livro_id, descricao, status_descricao=1)
            enriched += 1
            log(f"[OK] → {titulo}")
        else:
            update_descricao(conn, livro_id, None, status_descricao=2)
            failed += 1
            log(f"[--] Sem descrição → {titulo}")

    conn.close()

    log(f"Finalizado — OK: {enriched} | Sem descrição: {failed}")