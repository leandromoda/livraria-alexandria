# ============================================================
# STEP 13 — PUBLISH OFERTAS
# Livraria Alexandria
#
# Publica ofertas de livros no Supabase.
# Requisito: livro já publicado (status_publish=1, supabase_id preenchido)
#            e oferta resolvida (offer_status=1, offer_url preenchida).
# ============================================================

import os
import time

from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

from core.db import get_conn
from core.logger import log


# =========================
# CONFIG
# =========================

_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=_ENV_PATH)

TIMEOUT     = 60
MAX_RETRIES = 3


# =========================
# FETCH
# =========================

def fetch_pendentes(conn, pacote):

    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            titulo,
            supabase_id,
            marketplace,
            offer_url,
            preco
        FROM livros
        WHERE CAST(offer_status AS TEXT) IN ('1', 'active')
          AND status_publish        = 1
          AND status_publish_oferta = 0
          AND offer_url             IS NOT NULL
          AND supabase_id           IS NOT NULL
        LIMIT ?
    """, (pacote,))

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


# =========================
# MIGRAÇÃO: normaliza offer_status='active' → 1 e reseta flag
# =========================

def fix_offer_status(conn=None):
    """Converte offer_status='active' para 1 (inteiro) e reseta status_publish_oferta=0.

    Livros seeds importados com offer_status='active' (texto) nunca eram
    elegíveis para step 17 (exige offer_status=1 inteiro). Esta função
    corrige o estado para que possam ser publicados.
    """
    from core.db import get_conn as _get_conn
    close_conn = conn is None
    if conn is None:
        conn = _get_conn()

    cur = conn.cursor()

    # 1. Normaliza offer_status texto → inteiro e reseta o flag de publicação
    cur.execute("""
        UPDATE livros
        SET offer_status         = 1,
            status_publish_oferta = 0,
            updated_at           = CURRENT_TIMESTAMP
        WHERE offer_status = 'active'
          AND offer_url IS NOT NULL
    """)
    conn.commit()
    com_url = cur.rowcount

    # 2. Reseta flag para livros 'active' sem offer_url (serão resolvidos no step 3)
    cur.execute("""
        UPDATE livros
        SET status_publish_oferta = 0,
            updated_at            = CURRENT_TIMESTAMP
        WHERE offer_status = 'active'
          AND offer_url IS NULL
    """)
    conn.commit()
    sem_url = cur.rowcount

    if close_conn:
        conn.close()

    log(f"[OFERTAS] fix_offer_status: {com_url} offer_status normalizados → 1 (offer_url preenchida)")
    if sem_url:
        log(f"[OFERTAS] fix_offer_status: {sem_url} livros com offer_url vazia — rodar step 3 primeiro")
    return com_url, sem_url


# =========================
# FLAG LOCAL
# =========================

def mark_published(conn, local_id):

    cur = conn.cursor()

    cur.execute("""
        UPDATE livros
        SET status_publish_oferta = 1,
            updated_at            = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (local_id,))

    conn.commit()


# =========================
# RUN
# =========================

def run(pacote=100):

    conn = get_conn()

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
        # upsert por (livro_id, marketplace): cria se não existe, atualiza se já existe
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }

    # on_conflict=(livro_id,marketplace) — requer UNIQUE(livro_id, marketplace) no Supabase
    ofertas_url = f"{supabase_url}/rest/v1/ofertas?on_conflict=livro_id,marketplace"

    rows = fetch_pendentes(conn, pacote)

    if not rows:
        log("Nenhuma oferta pendente para publicação.")
        conn.close()
        return

    inserted = 0
    failed   = 0
    total    = len(rows)

    now = datetime.utcnow().isoformat()

    for i, row in enumerate(rows, start=1):

        local_id, titulo, supabase_id, marketplace, offer_url, preco = row

        payload = {
            "livro_id":    supabase_id,
            "marketplace": marketplace,
            "url_afiliada": offer_url,
            "preco":       preco,
            "ativa":       True,
            "created_at":  now,
        }

        ok = upsert(ofertas_url, payload, headers)

        if not ok:
            failed += 1
            log(f"[OFERTAS][{i:03d}/{total:03d}] FALHA → {titulo}")
            continue

        mark_published(conn, local_id)
        inserted += 1
        log(f"[OFERTAS][{i:03d}/{total:03d}] OK → {titulo} ({marketplace})")

    conn.close()

    log(f"Ofertas publicadas: {inserted} | Falhas: {failed}")
