# ============================================================
# STEP — PUBLISH AUTORES
# Livraria Alexandria
#
# Publica autores e relações livros_autores no Supabase.
# ============================================================

import os

import requests
import time

from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from core.db import get_conn
from core.logger import log


# =========================
# CONFIG
# =========================

_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=_ENV_PATH)

SUPABASE_URL = os.getenv("NEXT_PUBLIC_SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates,return=representation"
}

TIMEOUT     = 60
MAX_RETRIES = 3


# =========================
# FETCH
# =========================

def fetch_autores_pendentes(conn, pacote):

    cur = conn.cursor()

    cur.execute("""
        SELECT id, nome, slug, nacionalidade, supabase_id
        FROM autores
        WHERE status_publish = 0
        LIMIT ?
    """, (pacote,))

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

def upsert(url, payload, headers):

    for attempt in range(MAX_RETRIES):

        try:
            res = requests.post(
                url,
                headers=headers,
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


def upsert_autor(row, autores_url, headers):

    (local_id, nome, slug, nacionalidade, existing_supabase_id) = row

    now = datetime.utcnow().isoformat()

    payload = {
        "nome":          nome,
        "slug":          slug,
        "nacionalidade": nacionalidade,
        "created_at":    now,
    }

    return upsert(autores_url, payload, headers)


def upsert_relacao(livro_supabase_id, autor_slug, livros_autores_url, headers, supabase_url):
    """Resolve autor_id via slug no Supabase e insere relação."""

    lookup_url = (
        f"{supabase_url}/rest/v1/autores"
        f"?slug=eq.{autor_slug}&select=id"
    )

    try:
        res = requests.get(lookup_url, headers=headers, timeout=TIMEOUT)
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
        "livro_id": livro_supabase_id,
        "autor_id": autor_supabase_id,
    }

    return upsert(livros_autores_url, payload, headers)


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

def run(pacote=100):

    conn = get_conn()

    # Lê credenciais em runtime — garante que o sistema de env do main.py já executou
    supabase_url = os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

    if not supabase_url or not supabase_key:
        log("ERRO: NEXT_PUBLIC_SUPABASE_URL ou SUPABASE_SERVICE_ROLE_KEY não configurados.")
        conn.close()
        return

    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=representation",
    }

    autores_url        = f"{supabase_url}/rest/v1/autores?on_conflict=slug"
    livros_autores_url = f"{supabase_url}/rest/v1/livros_autores?on_conflict=livro_id,autor_id"

    autores = fetch_autores_pendentes(conn, pacote)

    if not autores:
        log("Nenhum autor pendente para publicação.")
        conn.close()
        return

    inserted  = 0
    failed    = 0
    relacoes  = 0
    total     = len(autores)

    for i, row in enumerate(autores, start=1):

        local_id = row["id"]
        slug     = row["slug"]

        ok = upsert_autor(row, autores_url, headers)

        if not ok:
            failed += 1
            log(f"[AUTORES][{i:03d}/{total:03d}] FALHA → {row['nome']}")
            continue

        # Publica relações livros_autores
        livros_rows = fetch_relacoes(conn, local_id)

        for livro_row in livros_rows:
            livro_supabase_id = livro_row["supabase_id"]
            upsert_relacao(livro_supabase_id, slug, livros_autores_url, headers, supabase_url)
            relacoes += 1

        mark_published(conn, local_id)
        inserted += 1
        log(f"[AUTORES][{i:03d}/{total:03d}] OK → {row['nome']}")

    conn.close()

    log(f"Autores publicados: {inserted} | Relações: {relacoes} | Falhas: {failed}")
