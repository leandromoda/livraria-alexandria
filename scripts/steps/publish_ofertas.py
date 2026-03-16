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

def fetch_pendentes(conn):

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
        WHERE offer_status          = 1
          AND status_publish        = 1
          AND status_publish_oferta = 0
          AND offer_url             IS NOT NULL
          AND supabase_id           IS NOT NULL
    """)

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

def run():

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
        "Prefer": "resolution=merge-duplicates,return=representation",
    }

    # on_conflict por livro + marketplace — evita duplicatas se re-rodado
    ofertas_url = f"{supabase_url}/rest/v1/ofertas?on_conflict=livro_id,marketplace"

    rows = fetch_pendentes(conn)

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
            "updated_at":  now,
        }

        ok = upsert(ofertas_url, payload, headers)

        if not ok:
            failed += 1
            log(f"FALHA [{i}/{total}] → {titulo}")
            continue

        mark_published(conn, local_id)
        inserted += 1
        log(f"PUBLICADO [{i}/{total}] → {titulo} ({marketplace})")

    conn.close()

    log(f"Ofertas publicadas: {inserted} | Falhas: {failed}")
