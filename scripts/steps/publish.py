# ============================================================
# STEP 10 — PUBLISH
# Livraria Alexandria
#
# Publica livros no Supabase.
# Envia sinopse (campo gerado), não descricao (campo bruto).
# ============================================================

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
    "Prefer": "resolution=merge-duplicates,return=representation"
}

# URL com on_conflict para upsert por slug
TABLE_URL_UPSERT = f"{TABLE_URL}?on_conflict=slug"

TIMEOUT    = 60
MAX_RETRIES = 3

UUID_NAMESPACE = uuid.UUID("11111111-2222-3333-4444-555555555555")


# =========================
# FETCH
# =========================

def fetch_pending(conn, idioma, limit):

    cur = conn.cursor()

    cur.execute("""
        SELECT
            id, titulo, slug, autor,
            sinopse, isbn, ano_publicacao,
            imagem_url, supabase_id,
            is_publishable, editorial_score,
            is_book, updated_at,
            preco_atual, offer_status
        FROM livros
        WHERE status_publish  = 0
          AND status_review   = 1
          AND is_publishable  = 1
          AND status_synopsis = 1
          AND sinopse IS NOT NULL
          AND sinopse != ''
          AND idioma          = ?
        LIMIT ?
    """, (idioma, limit))

    return cur.fetchall()


# =========================
# UUID
# =========================

def resolve_uuid(local_id, existing_supabase_id):

    if existing_supabase_id:
        return existing_supabase_id

    return str(uuid.uuid5(UUID_NAMESPACE, str(local_id)))


# =========================
# PAYLOAD — envia sinopse como descricao para o Supabase
# =========================

def build_payload(row):

    now = datetime.utcnow().isoformat()

    (local_id, titulo, slug, autor,
     sinopse, isbn, ano_publicacao,
     imagem_url, existing_supabase_id,
     is_publishable, editorial_score,
     is_book, local_updated_at,
     preco_atual, offer_status) = row

    supabase_uuid = resolve_uuid(local_id, existing_supabase_id)

    payload = {
        "id":                 supabase_uuid,
        "titulo":             titulo,
        "slug":               slug,
        "autor":              autor,
        "descricao":          sinopse,      # campo no Supabase recebe a sinopse gerada
        "isbn":               isbn,
        "ano_publicacao":     ano_publicacao,
        "imagem_url":         imagem_url,
        "is_publishable":     bool(is_publishable) if is_publishable is not None else False,
        "quality_score":      editorial_score,
        "is_book":            bool(is_book) if is_book is not None else True,
        "last_quality_check": now,
        "publish_blockers":   None,
        "created_at":         now,
        "updated_at":         now,
    }

    # Campos de preço e status de oferta (requerem migrations Supabase)
    if preco_atual is not None:
        payload["preco_atual"] = preco_atual
    if offer_status:
        payload["offer_status"] = offer_status

    return payload


# =========================
# UPSERT
# =========================

def upsert_book(payload):

    for attempt in range(MAX_RETRIES):

        try:
            res = requests.post(
                TABLE_URL_UPSERT,
                headers=HEADERS,
                json=payload,
                timeout=TIMEOUT
            )

            if res.status_code == 409:
                # Duplicata — já existe no Supabase, marcar como publicado localmente
                log(f"UPSERT (já existe) → {payload['slug']}")
                return payload["id"]

            if res.status_code not in [200, 201]:
                log(f"SUPABASE ERRO {res.status_code} → {res.text[:200]}")
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

def mark_published(conn, local_id, supabase_id):

    cur = conn.cursor()

    cur.execute("""
        UPDATE livros
        SET status_publish = 1,
            supabase_id    = ?,
            updated_at     = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (supabase_id, local_id))

    conn.commit()


# =========================
# RUN
# =========================

def run(idioma, pacote=10):

    conn = get_conn()

    rows = fetch_pending(conn, idioma, pacote)

    if not rows:
        log(f"Nada pendente para publicação [{idioma}].")
        conn.close()
        return

    inserted = 0
    failed   = 0
    total    = len(rows)

    for i, row in enumerate(rows, start=1):

        payload    = build_payload(row)
        supabase_id = upsert_book(payload)

        if not supabase_id:
            failed += 1
            log(f"[PUBLISH][{i:03d}/{total:03d}] FALHA → {row[1]}")
            continue

        mark_published(conn, row[0], supabase_id)
        inserted += 1
        log(f"[PUBLISH][{i:03d}/{total:03d}] OK → {row[1]}")

    conn.close()

    log(f"Publicados: {inserted} | Falhas: {failed}")
