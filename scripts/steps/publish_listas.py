# ============================================================
# STEP 19 — PUBLISH LISTAS
# Livraria Alexandria
#
# Publica listas SEO (geradas no step 18) no Supabase.
# Lê listas + listas_livros (SQLite) e sincroniza com:
#   - listas          (upsert por slug)
#   - lista_livros    (upsert por lista_id + livro_id)
# ============================================================

import os
import sqlite3
import time
import requests

from pathlib import Path
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
# SCHEMA MIGRATION
# =========================

def _ensure_columns(conn) -> None:
    """Garante que a tabela listas possui as colunas necessárias.

    Usa PRAGMA table_info para verificar colunas existentes antes de tentar
    ALTER TABLE — evita falhas silenciosas e erros "no such column" downstream.

    Nota: SQLite proíbe expressões (CURRENT_TIMESTAMP) como DEFAULT em
    ALTER TABLE ADD COLUMN — apenas constantes literais são permitidas.
    Por isso updated_at é adicionada sem DEFAULT (ficará NULL para linhas
    antigas; o UPDATE de publicação define o valor explicitamente).
    """
    cur = conn.cursor()

    # Verifica se a tabela existe antes de qualquer ALTER
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='listas'")
    if not cur.fetchone():
        log("[PUBLISH_LISTAS][SCHEMA] Tabela 'listas' não existe. Rode o step 18 primeiro.")
        return

    # Verifica colunas existentes com PRAGMA (evita ALTER desnecessário)
    cur.execute("PRAGMA table_info(listas)")
    existing = {row[1] for row in cur.fetchall()}

    for col, definition in [
        ("status_publish", "INTEGER DEFAULT 0"),
        ("updated_at",     "DATETIME"),          # sem DEFAULT — SQLite não aceita CURRENT_TIMESTAMP aqui
    ]:
        if col not in existing:
            try:
                cur.execute(f"ALTER TABLE listas ADD COLUMN {col} {definition}")
                log(f"[PUBLISH_LISTAS][SCHEMA] Coluna '{col}' adicionada.")
            except sqlite3.OperationalError as e:
                log(f"[PUBLISH_LISTAS][SCHEMA] ERRO ao adicionar coluna '{col}': {e}")

    conn.commit()

    # Verifica que as colunas existem após as ALTERações
    cur.execute("PRAGMA table_info(listas)")
    final_cols = {row[1] for row in cur.fetchall()}
    missing = [c for c in ("status_publish", "updated_at") if c not in final_cols]
    if missing:
        raise RuntimeError(f"[PUBLISH_LISTAS] Colunas ausentes após migração: {missing}")


# =========================
# FETCH SQLite
# =========================

def fetch_listas(conn) -> list[dict]:
    cur = conn.cursor()
    cur.execute("""
        SELECT id, slug, titulo, descricao, categoria_slug
        FROM listas
        WHERE status_publish = 0
        ORDER BY titulo
    """)
    rows = cur.fetchall()
    return [
        {"id": r[0], "slug": r[1], "titulo": r[2], "descricao": r[3], "categoria_slug": r[4]}
        for r in rows
    ]


def fetch_livros_da_lista(conn, lista_id: str) -> list[dict]:
    cur = conn.cursor()
    cur.execute("""
        SELECT ll.livro_id, ll.position, l.supabase_id
        FROM listas_livros ll
        JOIN livros l ON l.id = ll.livro_id
        WHERE ll.lista_id = ?
          AND l.supabase_id IS NOT NULL
          AND l.supabase_id != ''
        ORDER BY ll.position
    """, (lista_id,))
    rows = cur.fetchall()
    return [
        {"livro_id_local": r[0], "position": r[1], "supabase_id": r[2]}
        for r in rows
    ]


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


def upsert(url: str, payload: dict | list, headers: dict) -> list | None:
    for attempt in range(MAX_RETRIES):
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT)
            if res.status_code == 409:
                return []
            if res.status_code not in [200, 201]:
                log(f"SUPABASE ERRO {res.status_code} → {res.text[:200]}")
                time.sleep(2)
                continue
            return res.json()
        except Exception as e:
            log(f"RETRY → {e}")
            time.sleep(2)
    return None


def lookup_lista_id(supabase_url: str, slug: str, headers: dict) -> str | None:
    try:
        res = requests.get(
            f"{supabase_url}/rest/v1/listas?slug=eq.{slug}&select=id",
            headers={**headers, "Prefer": ""},
            timeout=TIMEOUT,
        )
        data = res.json()
        return data[0]["id"] if data else None
    except Exception as e:
        log(f"LOOKUP LISTA ERRO ({slug}) → {e}")
        return None


# =========================
# RUN
# =========================

def run():
    log("[PUBLISH_LISTAS] Iniciando")

    supabase_url = os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

    if not supabase_url or not supabase_key:
        log("[PUBLISH_LISTAS] ERRO: NEXT_PUBLIC_SUPABASE_URL ou SUPABASE_SERVICE_ROLE_KEY não configurados.")
        return

    headers    = _headers(supabase_key)
    listas_url = f"{supabase_url}/rest/v1/listas?on_conflict=slug"
    membros_url = f"{supabase_url}/rest/v1/lista_livros?on_conflict=lista_id,livro_id"

    conn = get_conn()
    _ensure_columns(conn)
    listas = fetch_listas(conn)

    if not listas:
        log("[PUBLISH_LISTAS] Nenhuma lista no SQLite. Rode o step 18 (Listas SEO) primeiro.")
        conn.close()
        return

    log(f"[PUBLISH_LISTAS] {len(listas)} listas encontradas")

    lista_ok = lista_fail = membros_ok = membros_fail = 0

    for i, lista in enumerate(listas, 1):
        log(f"[PUBLISH_LISTAS][{i:03d}/{len(listas):03d}] → {lista['titulo']}")

        payload = {
            "slug":        lista["slug"],
            "titulo":      lista["titulo"],
            "introducao":  lista["descricao"],
            "tipo":        "melhores",
        }

        result = upsert(listas_url, payload, headers)

        if result is None:
            log(f"[PUBLISH_LISTAS] FALHA lista → {lista['slug']}")
            lista_fail += 1
            continue

        # Resolve UUID da lista no Supabase
        supabase_lista_id = None
        if result and isinstance(result, list) and len(result) > 0:
            supabase_lista_id = result[0].get("id")

        if not supabase_lista_id:
            supabase_lista_id = lookup_lista_id(supabase_url, lista["slug"], headers)

        if not supabase_lista_id:
            log(f"[PUBLISH_LISTAS] SKIP membros — UUID não encontrado: {lista['slug']}")
            lista_fail += 1
            continue

        lista_ok += 1
        cur = conn.cursor()
        cur.execute(
            "UPDATE listas SET status_publish = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (lista["id"],)
        )
        conn.commit()

        # Publica membros (lista_livros)
        livros = fetch_livros_da_lista(conn, lista["id"])
        for membro in livros:
            m_payload = {
                "lista_id": supabase_lista_id,
                "livro_id": membro["supabase_id"],
                "posicao":  membro["position"],
            }
            m_result = upsert(membros_url, m_payload, headers)
            if m_result is None:
                membros_fail += 1
            else:
                membros_ok += 1

    conn.close()

    log("[PUBLISH_LISTAS] Finalizado")
    log(f"Listas: OK={lista_ok} | Falhas={lista_fail} | Membros: OK={membros_ok} | Falhas={membros_fail}")
