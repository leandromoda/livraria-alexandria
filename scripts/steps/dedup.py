# ============================================================
# STEP 5 — DEDUP
# Livraria Alexandria
#
# Deduplicação por ISBN, slug e similaridade de título.
# Merge conserva descricao via COALESCE.
# ============================================================

import os
import sqlite3
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher


# =========================
# CONFIG
# =========================

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "books.db")

SIMILARITY_THRESHOLD = 0.92


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
    conn.execute("PRAGMA synchronous=NORMAL")

    return conn


# =========================
# SIMILARITY
# =========================

def _norm(s):
    """Normaliza texto para comparação: NFKD → ASCII → minúsculas."""
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii").lower()


def similar(a, b):
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def accent_score(s):
    """Conta caracteres com acento/diacrítico (perdidos na conversão ASCII)."""
    if not s:
        return 0
    return len(s) - len(s.encode("ascii", "ignore").decode("ascii"))


# =========================
# FETCH
# =========================

def fetch_pending(conn, idioma, limit):

    cur = conn.cursor()

    cur.execute("""
        SELECT id, titulo, slug, isbn, autor
        FROM livros
        WHERE status_dedup = 0
          AND idioma = ?
        LIMIT ?
    """, (idioma, limit))

    return cur.fetchall()


# =========================
# FIND DUPLICATES
# =========================

def find_duplicates(conn, book, idioma):

    cur = conn.cursor()

    cur.execute("""
        SELECT id, titulo, slug, isbn,
               descricao, imagem_url, ano_publicacao, autor
        FROM livros
        WHERE id != ?
          AND idioma = ?
    """, (book["id"], idioma))

    rows = cur.fetchall()
    duplicates = []

    for r in rows:

        if book["isbn"] and r[3] == book["isbn"]:
            duplicates.append(r)
            continue

        if book["slug"] and r[2] == book["slug"]:
            duplicates.append(r)
            continue

        if similar(book["titulo"], r[1]) >= SIMILARITY_THRESHOLD:
            duplicates.append(r)

    return duplicates


# =========================
# MERGE
# =========================

def merge_books(conn, master, dup_row):

    cur = conn.cursor()

    master_id  = master["id"]
    dup_id     = dup_row[0]
    dup_titulo = dup_row[1]
    dup_autor  = dup_row[7]

    # Prefere o título/autor com mais acentos (grafia mais completa)
    melhor_titulo = dup_titulo if accent_score(dup_titulo or "") > accent_score(master["titulo"] or "") else None
    melhor_autor  = dup_autor  if accent_score(dup_autor  or "") > accent_score(master["autor"]  or "") else None

    cur.execute("""
        UPDATE livros
        SET titulo         = COALESCE(?, titulo),
            autor          = COALESCE(?, autor),
            descricao      = COALESCE(descricao, ?),
            imagem_url     = COALESCE(imagem_url, ?),
            ano_publicacao = COALESCE(ano_publicacao, ?),
            updated_at     = ?
        WHERE id = ?
    """, (
        melhor_titulo,
        melhor_autor,
        dup_row[4],
        dup_row[5],
        dup_row[6],
        datetime.utcnow().isoformat(),
        master_id,
    ))

    cur.execute("DELETE FROM livros WHERE id = ?", (dup_id,))

    conn.commit()

    titulo_final = melhor_titulo or master["titulo"]
    log(f"MERGE | {dup_id} → {master_id} | título: {titulo_final!r}")


# =========================
# FLAG
# =========================

def mark_processed(conn, book_id):

    cur = conn.cursor()

    cur.execute("""
        UPDATE livros
        SET status_dedup = 1,
            updated_at = ?
        WHERE id = ?
    """, (datetime.utcnow().isoformat(), book_id))

    conn.commit()


# =========================
# RUN
# =========================

def run(idioma, pacote=10):

    conn = get_conn()

    rows = fetch_pending(conn, idioma, pacote)

    if not rows:
        log(f"Nada pendente para dedup [{idioma}].")
        conn.close()
        return

    processed = 0
    removed   = 0
    total     = len(rows)

    for i, r in enumerate(rows, start=1):

        book = {"id": r[0], "titulo": r[1], "slug": r[2], "isbn": r[3], "autor": r[4]}

        duplicates = find_duplicates(conn, book, idioma)

        for dup in duplicates:
            merge_books(conn, book, dup)
            removed += 1

        mark_processed(conn, book["id"])
        processed += 1

        log(f"[DEDUP][{i:03d}/{total:03d}] OK → {book['titulo']}")

    conn.close()

    log(f"[DEDUP] Finalizado | Processados: {processed} | Removidos: {removed}")
