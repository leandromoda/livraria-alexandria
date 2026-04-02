# ============================================================
# STEP 20 — PUBLISH CATEGORIAS
# Livraria Alexandria
#
# Publica categorias temáticas (geradas no step 18) no Supabase.
# Lê livros_categorias_tematicas (SQLite) e sincroniza com:
#   - categorias          (upsert por slug)
#   - livros_categorias   (upsert por livro_id + categoria_id)
# ============================================================

import os
import json
import time
import requests

from pathlib import Path
from datetime import datetime
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

TAXONOMY_PATH = Path(__file__).resolve().parents[1] / "data" / "taxonomy.json"


# =========================
# TAXONOMY
# =========================

def load_taxonomy() -> dict[str, str]:
    """Retorna {slug: label} a partir do taxonomy.json."""
    with open(TAXONOMY_PATH, encoding="utf-8") as f:
        items = json.load(f)
    return {item["slug"]: item["label"] for item in items}


# =========================
# FETCH SQLite
# =========================

def fetch_pares(conn) -> list[tuple[str, str]]:
    """
    Retorna lista de (supabase_id, categoria_slug) para
    todos os livros publicados que têm categorias temáticas.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT l.supabase_id, t.categoria_slug
        FROM livros_categorias_tematicas t
        JOIN livros l ON l.id = t.livro_id
        WHERE l.status_publish = 1
          AND l.supabase_id IS NOT NULL
          AND l.supabase_id != ''
        ORDER BY l.supabase_id, t.categoria_slug
    """)
    return cur.fetchall()


# =========================
# HTTP
# =========================

def _headers(key: str) -> dict:
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=representation",
    }


def upsert(url: str, payload: dict | list, headers: dict) -> bool:
    for attempt in range(MAX_RETRIES):
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT)
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


def lookup_categoria_id(supabase_url: str, slug: str, headers: dict) -> str | None:
    """Resolve o UUID da categoria no Supabase pelo slug."""
    try:
        res = requests.get(
            f"{supabase_url}/rest/v1/categorias?slug=eq.{slug}&select=id",
            headers=headers,
            timeout=TIMEOUT,
        )
        data = res.json()
        return data[0]["id"] if data else None
    except Exception as e:
        log(f"LOOKUP CATEGORIA ERRO ({slug}) → {e}")
        return None


# =========================
# RUN
# =========================

def run():
    log("[PUBLISH_CAT] Iniciando")

    supabase_url = os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

    if not supabase_url or not supabase_key:
        log("[PUBLISH_CAT] ERRO: NEXT_PUBLIC_SUPABASE_URL ou SUPABASE_SERVICE_ROLE_KEY não configurados.")
        return

    headers            = _headers(supabase_key)
    categorias_url     = f"{supabase_url}/rest/v1/categorias?on_conflict=slug"
    livros_cat_url     = f"{supabase_url}/rest/v1/livros_categorias?on_conflict=livro_id,categoria_id"

    taxonomy = load_taxonomy()
    log(f"[PUBLISH_CAT] Taxonomia carregada: {len(taxonomy)} categorias")

    conn  = get_conn()
    pares = fetch_pares(conn)
    conn.close()

    if not pares:
        log("[PUBLISH_CAT] Nenhum par livro↔categoria encontrado. Rode o step 18 (Categorizar) primeiro.")
        return

    # Slugs únicos das categorias usadas
    slugs_usados = sorted({slug for _, slug in pares})
    log(f"[PUBLISH_CAT] {len(pares)} pares | {len(slugs_usados)} categorias únicas | {len(set(sid for sid, _ in pares))} livros")

    # ── 1. Upsert categorias ──────────────────────────────────────────────────

    log("[PUBLISH_CAT] Publicando categorias…")
    cat_ok = cat_fail = 0

    for slug in slugs_usados:
        nome = taxonomy.get(slug, slug.replace("-", " ").title())
        payload = {
            "slug": slug,
            "nome": nome,
        }
        if upsert(categorias_url, payload, headers):
            cat_ok += 1
        else:
            cat_fail += 1
            log(f"[PUBLISH_CAT] FALHA categoria → {slug}")

    log(f"[PUBLISH_CAT] Categorias: OK={cat_ok} | Falhas={cat_fail}")

    # ── 2. Upsert livros_categorias ───────────────────────────────────────────

    log("[PUBLISH_CAT] Publicando vínculos livros↔categorias…")
    rel_ok = rel_fail = 0

    # Cache de cat_id por slug para evitar lookups repetidos
    cat_id_cache: dict[str, str | None] = {}

    for i, (livro_supabase_id, cat_slug) in enumerate(pares, 1):

        if cat_slug not in cat_id_cache:
            cat_id_cache[cat_slug] = lookup_categoria_id(supabase_url, cat_slug, headers)

        cat_id = cat_id_cache[cat_slug]

        if not cat_id:
            log(f"[PUBLISH_CAT] SKIP vínculo — categoria não encontrada: {cat_slug}")
            rel_fail += 1
            continue

        payload = {
            "livro_id":     livro_supabase_id,
            "categoria_id": cat_id,
        }

        if upsert(livros_cat_url, payload, headers):
            rel_ok += 1
        else:
            rel_fail += 1

        if i % 50 == 0:
            log(f"[PUBLISH_CAT] Vínculos: {i}/{len(pares)}")

    log(f"[PUBLISH_CAT] Finalizado")
    log(f"Categorias: OK={cat_ok} | Falhas={cat_fail} | Vínculos: OK={rel_ok} | Falhas={rel_fail}")
