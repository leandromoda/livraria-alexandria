# ============================================
# LIVRARIA ALEXANDRIA — PUBLISH
# Path Safe + Retry Safe + Roundtrip Safe
# ============================================

import requests
import uuid
import time

from datetime import datetime

from core.db import get_conn
from core.logger import log


# =========================
# CONFIG
# =========================

SUPABASE_URL = "https://ncnexkuiiuzwujqurtsa.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5jbmV4a3VpaXV6d3VqcXVydHNhIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2OTU0MTY2MCwiZXhwIjoyMDg1MTE3NjYwfQ.CacLDlVd0noDzcuVJnxjx3eMr7SjI_19rAsDZeQh6S8"

TABLE_URL = f"{SUPABASE_URL}/rest/v1/livros"

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation,resolution=merge-duplicates"
}

TIMEOUT = 60
MAX_RETRIES = 3

# namespace fixo → UUID determinístico
UUID_NAMESPACE = uuid.UUID("11111111-2222-3333-4444-555555555555")


# =========================
# SCHEMA GUARD
# =========================

def ensure_publish_schema():

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("PRAGMA table_info(livros)")
    columns = [row[1] for row in cur.fetchall()]

    # supabase_id
    if "supabase_id" not in columns:

        log("Schema update → adicionando coluna supabase_id")

        cur.execute("""
            ALTER TABLE livros
            ADD COLUMN supabase_id TEXT
        """)

        conn.commit()

        log("Coluna supabase_id criada com sucesso.")

    # is_publishable
    if "is_publishable" not in columns:

        log("Schema update → adicionando coluna is_publishable")

        cur.execute("""
            ALTER TABLE livros
            ADD COLUMN is_publishable INTEGER DEFAULT 1
        """)

        conn.commit()

        log("Coluna is_publishable criada com sucesso.")

    conn.close()


# =========================
# FETCH
# =========================

def fetch_pending(idioma, limit):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            titulo,
            slug,
            autor,
            descricao,
            isbn,
            ano_publicacao,
            imagem_url,
            supabase_id
        FROM livros
        WHERE status_publish = 0
        AND status_review = 1
        AND is_publishable = 1
        AND idioma = ?
        LIMIT ?
    """, (idioma, limit))

    rows = cur.fetchall()
    conn.close()

    return rows


# =========================
# UUID RESOLUTION
# =========================

def resolve_uuid(local_id, existing_supabase_id):

    if existing_supabase_id:
        return existing_supabase_id

    deterministic_uuid = uuid.uuid5(
        UUID_NAMESPACE,
        str(local_id)
    )

    return str(deterministic_uuid)


# =========================
# PAYLOAD
# =========================

def build_payload(row):

    now = datetime.utcnow().isoformat()

    local_id = row[0]
    existing_supabase_id = row[8]

    supabase_uuid = resolve_uuid(local_id, existing_supabase_id)

    return {
        "id": supabase_uuid,
        "titulo": row[1],
        "slug": row[2],
        "autor": row[3],
        "descricao": row[4],
        "isbn": row[5],
        "ano_publicacao": row[6],
        "imagem_url": row[7],
        "created_at": now,
        "updated_at": now,
    }


# =========================
# UPSERT
# =========================

def upsert_book(payload):

    for attempt in range(MAX_RETRIES):

        try:

            res = requests.post(
                TABLE_URL,
                headers=HEADERS,
                json=payload,
                timeout=TIMEOUT
            )

            if res.status_code not in [200, 201]:

                log(
                    f"SUPABASE ERRO {res.status_code} → "
                    f"{res.text[:200]}"
                )

                time.sleep(2)
                continue

            data = res.json()

            if isinstance(data, list) and data:
                return data[0]["id"]

            return payload["id"]

        except Exception as e:

            log(f"RETRY SUPABASE → {e}")
            time.sleep(2)

    return None


# =========================
# FLAG LOCAL
# =========================

def mark_published(local_id, supabase_id):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        UPDATE livros
        SET
            status_publish = 1,
            supabase_id = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (supabase_id, local_id))

    conn.commit()
    conn.close()


# =========================
# RUN
# =========================

def run(idioma, pacote=10):

    # garante compatibilidade de schema
    ensure_publish_schema()

    rows = fetch_pending(idioma, pacote)

    if not rows:
        log(
            f"Nada pendente para publicação "
            f"no idioma [{idioma}]."
        )
        return

    inserted = 0
    failed = 0

    for row in rows:

        payload = build_payload(row)

        supabase_id = upsert_book(payload)

        if not supabase_id:
            failed += 1
            log(f"FALHA → {row[1]}")
            continue

        mark_published(row[0], supabase_id)

        inserted += 1
        log(f"PUBLICADO → {row[1]}")

    log(
        f"PUBLICAÇÃO CONCLUÍDA [{idioma}] → "
        f"{inserted} | falhas {failed}"
    )