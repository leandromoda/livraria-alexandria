# ============================================
# LIVRARIA ALEXANDRIA — REVIEW
# Idioma Resolver + Editorial Classifier
# SCORE PERSISTIDO
# ============================================

import re
from datetime import datetime

from core.db import get_conn


# ============================================
# LANGUAGE HEURISTICS
# ============================================

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


# ============================================
# EDITORIAL CLASSIFIER
# ============================================

NON_BOOK_PATTERNS = [

    r"\bjournal\b",
    r"\brevista\b",
    r"\bmagazine\b",
    r"\bbulletin\b",
    r"\bannals\b",
    r"\btransactions\b",

    r"\breport\b",
    r"\bcensus\b",
    r"\bdirectory\b",
    r"\byearbook\b",
    r"\bproceedings\b",

    r"\blaw\b",
    r"\bact\b",
    r"\bordinance\b",
    r"\blegislation\b",
    r"\bdecree\b",

    r"\bthesis\b",
    r"\bdissertation\b",

    r"\bannual report\b",
    r"\bcommittee\b",
]


BOOK_POSITIVE_PATTERNS = [
    r"\bromance\b",
    r"\bnovel\b",
    r"\bficção\b",
    r"\bfiction\b",
]


def calculate_editorial_score(title, isbn):

    if not title:
        return -5

    t = title.lower()

    score = 0

    # negativos
    for pattern in NON_BOOK_PATTERNS:
        if re.search(pattern, t):
            score -= 3

    # positivos
    for pattern in BOOK_POSITIVE_PATTERNS:
        if re.search(pattern, t):
            score += 2

    # ISBN
    if isbn:
        score += 1
    else:
        score -= 1

    return score


def classify_editorial(score):

    return 1 if score >= 0 else 0


# ============================================
# SCHEMA SAFETY
# ============================================

def ensure_columns():

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("PRAGMA table_info(livros)")
    cols = [c[1] for c in cur.fetchall()]

    if "is_book" not in cols:
        cur.execute("""
            ALTER TABLE livros
            ADD COLUMN is_book INTEGER DEFAULT 1
        """)

    if "editorial_score" not in cols:
        cur.execute("""
            ALTER TABLE livros
            ADD COLUMN editorial_score INTEGER DEFAULT 0
        """)

    conn.commit()
    conn.close()


# ============================================
# FETCH
# ============================================

def fetch_pending(limit):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, titulo, isbn, idioma
        FROM livros
        WHERE status_synopsis = 1
        AND status_review = 0
        LIMIT ?
    """, (limit,))

    rows = cur.fetchall()
    conn.close()

    return rows


# ============================================
# UPDATE
# ============================================

def update_review(
    book_id,
    idioma_final,
    is_book,
    score
):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        UPDATE livros
        SET idioma = ?,
            is_book = ?,
            editorial_score = ?,
            status_review = 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (
        idioma_final,
        is_book,
        score,
        book_id
    ))

    conn.commit()
    conn.close()


# ============================================
# RUN
# ============================================

def run(idioma="PT", pacote=20):

    idioma = idioma.upper()

    ensure_columns()

    rows = fetch_pending(pacote)

    if not rows:
        print("[REVIEW] Nada pendente.")
        return

    reviewed = 0

    for book_id, titulo, isbn, current_lang in rows:

        idioma_final = resolve_language(
            current_lang,
            isbn,
            titulo
        )

        score = calculate_editorial_score(
            titulo,
            isbn
        )

        is_book = classify_editorial(score)

        update_review(
            book_id,
            idioma_final,
            is_book,
            score
        )

        reviewed += 1

        tipo = "BOOK" if is_book else "NON-BOOK"

        print(
            f"[REVIEW] {titulo} → "
            f"{idioma_final} | "
            f"{tipo} | "
            f"score={score}"
        )

    print(
        f"[REVIEW] Concluído → {reviewed}"
    )
