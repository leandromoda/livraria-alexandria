from difflib import SequenceMatcher

from core.db import get_conn
from core.logger import log

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
        FROM books
        WHERE dedup = 0
        LIMIT ?
    """, (limit,))

    rows = cur.fetchall()
    conn.close()

    return rows


# =========================
# BUSCAR POSSÍVEIS DUPES
# =========================

def find_duplicates(book):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, titulo, slug, isbn,
               descricao, imagem_url,
               ano_publicacao
        FROM books
        WHERE id != ?
    """, (book["id"],))

    rows = cur.fetchall()
    conn.close()

    duplicates = []

    for r in rows:

        # ISBN match
        if book["isbn"] and r[3] == book["isbn"]:
            duplicates.append(r)
            continue

        # slug match
        if book["slug"] and r[2] == book["slug"]:
            duplicates.append(r)
            continue

        # título similar
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

    # copia campos faltantes
    cur.execute("""
        UPDATE books
        SET
            descricao = COALESCE(descricao, ?),
            imagem_url = COALESCE(imagem_url, ?),
            ano_publicacao = COALESCE(ano_publicacao, ?)
        WHERE id = ?
    """, (
        dup_row[4],
        dup_row[5],
        dup_row[6],
        master_id
    ))

    # deleta duplicado
    cur.execute(
        "DELETE FROM books WHERE id = ?",
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
        UPDATE books
        SET dedup = 1
        WHERE id = ?
    """, (book_id,))

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
