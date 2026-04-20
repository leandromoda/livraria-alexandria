# ============================================================
# STEP 6 — REVIEW
# Livraria Alexandria
#
# Classificação editorial e resolução de idioma.
# Roda ANTES de synopsis — synopsis depende de status_review=1.
# ============================================================

import os
import re
import sqlite3
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
# LANGUAGE HEURISTICS
# =========================

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


def resolve_language(current_lang, isbn, title):
    if current_lang and current_lang != "UNKNOWN":
        return current_lang.upper()
    isbn_lang = detect_lang_by_isbn(isbn)
    if isbn_lang:
        return isbn_lang
    title_lang = detect_lang_by_title(title)
    if title_lang:
        return title_lang
    return "UNKNOWN"


# =========================
# EDITORIAL CLASSIFIER
# =========================

NON_BOOK_PATTERNS = [
    # Periódicos e publicações seriadas
    r"\bjournal\b", r"\brevista\b", r"\bmagazine\b",
    r"\bbulletin\b", r"\bannals\b", r"\btransactions\b",
    r"\breport\b", r"\bcensus\b", r"\bdirectory\b",
    r"\byearbook\b", r"\bproceedings\b",
    r"\bannual editions\b",      # "Annual Editions: Macroeconomics 05/06"
    r"\bannual report\b",
    # Documentos jurídicos / institucionais
    r"\bordinance\b", r"\blegislation\b", r"\bdecree\b",
    r"\bcommittee\b",
    # Material acadêmico de pós-graduação
    r"\bthesis\b", r"\bdissertation\b", r"\bmonograph\b",
    # Bibliografias e catálogos de biblioteca
    r"\bbibliograph",            # "bibliographical", "bibliography"
    r"\bcatalogue\b",            # catálogos em inglês britânico
    r"\bmicrofilm\b",            # coleções de microfilme
    # Material didático fora do escopo literário
    r"\bworktext\b",             # "A Worktext in Home Economics"
    r"\bhome economics\b",       # disciplina escolar
    r"\bhandbook of\b",          # "Handbook of Macroeconomics" (sempre acadêmico)
    # Economia acadêmica — textbooks que nunca entram no catálogo literário
    r"\bmacroeconom",            # "Macroeconomics", "Macroeconomic Theory"
    r"\bmicroeconom",            # "Microeconomics", "Microeconomic Theory"
    r"\beconometric",            # "Econometrics", "Econometric Methods"
    r"\bpolitical economy\b",    # "Essay on India Political Economy"
    r"\beconomic policy\b",      # "Economic Policy Review"
    r"\beconomic outlook\b",     # "Regional Economic Outlook"
    r"\beconomic theory\b",      # "Macroeconomic Theory"
]

BOOK_POSITIVE_PATTERNS = [
    r"\bromance\b", r"\bnovel\b",
    r"\bficção\b", r"\bfiction\b",
]


def calculate_editorial_score(titulo, isbn):
    """
    Catálogo curado — seeds são livros por padrão (score base = 1).
    Penaliza apenas quando padrões NON_BOOK batem no título.
    """

    if not titulo:
        return -5

    t = titulo.lower()
    score = 1  # base positiva: seeds são livros curados

    for pattern in NON_BOOK_PATTERNS:
        if re.search(pattern, t):
            score -= 3

    for pattern in BOOK_POSITIVE_PATTERNS:
        if re.search(pattern, t):
            score += 1

    return score


def classify_editorial(score):
    return 1 if score >= 0 else 0


# =========================
# FETCH
# =========================

def fetch_pending(conn, idioma, limit):

    cur = conn.cursor()

    # Roda após dedup, antes de synopsis
    cur.execute("""
        SELECT id, titulo, isbn, idioma
        FROM livros
        WHERE status_dedup = 1
          AND status_review = 0
          AND idioma = ?
        LIMIT ?
    """, (idioma, limit))

    return cur.fetchall()


# =========================
# UPDATE
# =========================

def update_review(conn, book_id, idioma_final, is_book, score):

    cur = conn.cursor()

    cur.execute("""
        UPDATE livros
        SET idioma          = ?,
            is_book         = ?,
            editorial_score = ?,
            status_review   = 1,
            updated_at      = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (idioma_final, is_book, score, book_id))

    conn.commit()


# =========================
# RUN
# =========================

def run(idioma="PT", pacote=20):

    idioma = idioma.upper()

    conn = get_conn()

    rows = fetch_pending(conn, idioma, pacote)

    if not rows:
        log("[REVIEW] Nada pendente.")
        conn.close()
        return

    reviewed = 0
    total    = len(rows)

    for i, (book_id, titulo, isbn, current_lang) in enumerate(rows, start=1):

        idioma_final = resolve_language(current_lang, isbn, titulo)
        score        = calculate_editorial_score(titulo, isbn)
        is_book      = classify_editorial(score)

        update_review(conn, book_id, idioma_final, is_book, score)

        reviewed += 1
        tipo = "BOOK" if is_book else "NON-BOOK"
        log(f"[REVIEW][{i:03d}/{total:03d}] {titulo} → {idioma_final} | {tipo} | score={score}")

    conn.close()

    log(f"[REVIEW] Finalizado → {reviewed}")