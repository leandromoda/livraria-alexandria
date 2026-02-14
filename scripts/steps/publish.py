import requests
import uuid
from datetime import datetime

from core.db import get_conn
from core.logger import log

# =========================
# CONFIG
# =========================

SUPABASE_URL = "https://ncnexkuiiuzwujqurtsa.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5jbmV4a3VpaXV6d3VqcXVydHNhIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2OTU0MTY2MCwiZXhwIjoyMDg1MTE3NjYwfQ.CacLDlVd0noDzcuVJnxjx3eMr7SjI_19rAsDZeQh6S8"

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates"
}

TABLE_URL = f"{SUPABASE_URL}/rest/v1/livros"


# =========================
# FETCH
# =========================

def fetch_pending(limit):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            titulo,
            slug,
            autor,
            descricao,
            isbn,
            ano_publicacao,
            imagem_url,
            id
        FROM livros
        WHERE status_publish = 0
        AND status_review = 1
        LIMIT ?
    """, (limit,))

    rows = cur.fetchall()
    conn.close()

    return rows


# =========================
# PAYLOAD
# =========================

def build_payload(row):

    now = datetime.utcnow().isoformat()

    return {
        "id": str(uuid.uuid4()),   # ← UUID válido
        "titulo": row[0],
        "slug": row[1],
        "autor": row[2],
        "descricao": row[3],
        "isbn": row[4],
        "ano_publicacao": row[5],
        "imagem_url": row[6],
        "created_at": now,
        "updated_at": now,
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

    if res.status_code not in [200, 201]:
        print("STATUS:", res.status_code)
        print("BODY:", res.text)

    return res.status_code in [200, 201]


# =========================
# FLAG
# =========================

def mark_published(local_id):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        UPDATE livros
        SET
            status_publish = 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (local_id,))

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
            log(f"FALHA → {row[0]}")
            continue

        mark_published(row[7])

        inserted += 1
        log(f"PUBLICADO → {row[0]}")

    log(
        f"PUBLICAÇÃO CONCLUÍDA → {inserted} | falhas {failed}"
    )
