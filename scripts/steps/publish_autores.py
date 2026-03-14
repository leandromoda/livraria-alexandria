# ============================================================
# STEP — PUBLISH AUTORES
# Livraria Alexandria
#
# Publica autores e relações livros_autores no Supabase.
# ============================================================

import requests
import time

from datetime import datetime

from core.db import get_conn
from core.logger import log


# =========================
# CONFIG
# =========================

SUPABASE_URL = "https://ncnexkuiiuzwujqurtsa.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5jbmV4a3VpaXV6d3VqcXVydHNhIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2OTU0MTY2MCwiZXhwIjoyMDg1MTE3NjYwfQ.CacLDlVd0noDzcuVJnxjx3eMr7SjI_19rAsDZeQh6S8"

HEADERS = {
    "apikey": SUPABASE_URL,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates,return=representation"
}

AUTORES_URL          = f"{SUPABASE_URL}/rest/v1/autores?on_conflict=slug"
LIVROS_AUTORES_URL   = f"{SUPABASE_URL}/rest/v1/livros_autores?on_conflict=livro_id,autor_id"

TIMEOUT     = 60
MAX_RETRIES = 3


# =========================
# FETCH
# =========================

def fetch_autores_pendentes(conn):

    cur = conn.cursor()

    cur.execute("""
        SELECT id, nome, slug, nacionalidade, supabase_id
        FROM autores
        WHERE status_publish = 0
    """)

    return cur.fetchall()


def fetch_relacoes(conn, autor_id_local):
    """Retorna supabase_id dos livros relacionados ao autor."""

    cur = conn.cursor()

    cur.execute("""
        SELECT l.supabase_id
        FROM livros_autores la
        JOIN livros l ON l.id = la.livro_id
        WHERE la.autor_id = ?
          AND l.supabase_id IS NOT NULL
    """, (autor_id_local,))

    return cur.fetchall()


# =========================
# UPSERT
# =========================

def upsert(url, payload):

    for attempt in range(MAX_RETRIES):

        try:
            res = requests.post(
                url,
                headers=HEADERS,
                json=payload,
                timeout=TIMEOUT
            )

            if res.status_code == 409:
                return True

            if res.status_code not in [200, 201]:
                log(f"SUPABASE ERRO {res.status_code} → {res.text[:200]}")
                time.sleep(2)
                continue

            return True

        except Exception as e:
            log(f"RETRY → {e}")
            time.sleep(2)

    return False


def upsert_autor(row):

    (local_id, nome, slug, nacionalidade, existing_supabase_id) = row

    now = datetime.utcnow().isoformat()

    payload = {
        "nome":         nome,
        "slug":         slug,
        "nacionalidade": nacionalidade,
        "created_at":   now,
        "updated_at":   now,
    }

    return upsert(AUTORES_URL, payload)


def upsert_relacao(livro_supabase_id, autor_slug):
    """Resolve autor_id via slug no Supabase e insere relação."""

    # Busca autor_id no Supabase pelo slug
    lookup_url = (
        f"{SUPABASE_URL}/rest/v1/autores"
        f"?slug=eq.{autor_slug}&select=id"
    )

    try:
        res = requests.get(lookup_url, headers=HEADERS, timeout=TIMEOUT)
        data = res.json()

        if not data:
            log(f"Autor não encontrado no Supabase: {autor_slug}")
            return False

        autor_supabase_id = data[0]["id"]

    except Exception as e:
        log(f"LOOKUP AUTOR ERRO → {e}")
        return False

    now = datetime.utcnow().isoformat()

    payload = {
        "livro_id":  livro_supabase_id,
        "autor_id":  autor_supabase_id,
        "created_at": now,
    }

    return upsert(LIVROS_AUTORES_URL, payload)


# =========================
# FLAG LOCAL
# =========================

def mark_published(conn, local_id):

    cur = conn.cursor()

    cur.execute("""
        UPDATE autores
        SET status_publish = 1,
            updated_at     = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (local_id,))

    conn.commit()


# =========================
# RUN
# =========================

def run():

    conn = get_conn()

    autores = fetch_autores_pendentes(conn)

    if not autores:
        log("Nenhum autor pendente para publicação.")
        conn.close()
        return

    inserted  = 0
    failed    = 0
    relacoes  = 0

    for row in autores:

        local_id = row["id"]
        slug     = row["slug"]

        ok = upsert_autor(row)

        if not ok:
            failed += 1
            log(f"FALHA → {row['nome']}")
            continue

        # Publica relações livros_autores
        livros_rows = fetch_relacoes(conn, local_id)

        for livro_row in livros_rows:
            livro_supabase_id = livro_row["supabase_id"]
            upsert_relacao(livro_supabase_id, slug)
            relacoes += 1

        mark_published(conn, local_id)
        inserted += 1
        log(f"PUBLICADO → {row['nome']}")

    conn.close()

    log(f"Autores publicados: {inserted} | Relações: {relacoes} | Falhas: {failed}")
