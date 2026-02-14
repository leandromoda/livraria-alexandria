from difflib import SequenceMatcher
from datetime import datetime
import os
import sqlite3


# =========================
# DB PATH
# =========================

DB_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "data",
    "books.db"
)


def get_conn():
    return sqlite3.connect(DB_PATH, timeout=30)


def log(msg):
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {msg}")


SIMILARITY_THRESHOLD = 0.92


# =========================
# SIMILARIDADE
# =========================

def similar(a, b):
    return SequenceMatcher(None, a, b).ratio()


# =========================
# FETCH PENDENTES
# =========================

def fetch_pending(limit):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, titulo, slug, isbn
        FROM livros
        WHERE status_dedup = 0
        LIMIT ?
    """, (limit,))

    rows = cur.fetchall()
    conn.close()

    return rows


# =========================
# BUSCAR DUPLICADOS
# =========================

def find_duplicates(book):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, titulo, slug, isbn,
               descricao, imagem_url,
               ano_publicacao
        FROM livros
        WHERE id != ?
    """, (book["id"],))

    rows = cur.fetchall()
    conn.close()

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

def merge_books(master_id, dup_row):

    conn = get_conn()
    cur = conn.cursor()

    dup_id = dup_row[0]

    cur.execute("""
        UPDATE livros
        SET
            descricao = COALESCE(descricao, ?),
            imagem_url = COALESCE(imagem_url, ?),
            ano_publicacao = COALESCE(ano_publicacao, ?),
            updated_at = ?
        WHERE id = ?
    """, (
        dup_row[4],
        dup_row[5],
        dup_row[6],
        datetime.utcnow(),
        master_id
    ))

    cur.execute(
        "DELETE FROM livros WHERE id = ?",
        (dup_id,)
    )

    conn.commit()
    conn.close()

    log(f"MERGE → {dup_id} → {master_id}")


# =========================
# FLAG PROCESSADO
# =========================

def mark_processed(book_id):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        UPDATE livros
        SET status_dedup = 1,
            updated_at = ?
        WHERE id = ?
    """, (
        datetime.utcnow(),
        book_id
    ))

    conn.commit()
    conn.close()


# =========================
# RUN
# =========================

def run(pacote=10):

    rows = fetch_pending(pacote)

    if not rows:
        log("Nada pendente para dedup.")
        return

    processed = 0
    removed = 0

    for r in rows:

        book = {
            "id": r[0],
            "titulo": r[1],
            "slug": r[2],
            "isbn": r[3],
        }

        duplicates = find_duplicates(book)

        for dup in duplicates:
            merge_books(book["id"], dup)
            removed += 1

        mark_processed(book["id"])

        processed += 1
        log(f"DEDUP OK → {book['titulo']}")

    log(
        f"DEDUP CONCLUÍDO → processados {processed} | removidos {removed}"
    )
