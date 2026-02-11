import requests
import uuid
from datetime import datetime

from core.db import get_conn
from core.logger import log

# =========================
# CONFIG
# =========================

SUPABASE_URL = "https://SEU-PROJETO.supabase.co"
SUPABASE_KEY = "SUA_SERVICE_ROLE_KEY"

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates"
}

TABLE_URL = f"{SUPABASE_URL}/rest/v1/livros"


# =========================
# FETCH PENDENTES
# =========================

def fetch_pending(limit):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            titulo,
            slug,
            autor,
            descricao_revisada,
            isbn,
            ano_publicacao,
            imagem_url
        FROM books
        WHERE publicado = 0
        LIMIT ?
    """, (limit,))

    rows = cur.fetchall()
    conn.close()

    return rows


# =========================
# PAYLOAD
# =========================

def build_payload(row):

    return {
        "id": row[0],
        "titulo": row[1],
        "slug": row[2],
        "autor": row[3],
        "descricao": row[4],
        "isbn": row[5],
        "ano_publicacao": row[6],
        "imagem_url": row[7],
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }


# =========================
# UPSERT
# =========================

def upsert_book(payload):

    res = requests.post(
        TABLE_URL,
        headers=HEADERS,
        json=payload
    )

    return res.status_code in [200, 201]


# =========================
# FLAG PUBLICADO
# =========================

def mark_published(book_id):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        UPDATE books
        SET publicado = 1
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
        log("Nada pendente para publicação.")
        return

    inserted = 0
    failed = 0

    for row in rows:

        payload = build_payload(row)

        ok = upsert_book(payload)

        if not ok:
            failed += 1
            log(f"FALHA → {row[1]}")
            continue

        mark_published(row[0])

        inserted += 1
        log(f"PUBLICADO → {row[1]}")

    log(
        f"PUBLICAÇÃO CONCLUÍDA → {inserted} | falhas {failed}"
    )
