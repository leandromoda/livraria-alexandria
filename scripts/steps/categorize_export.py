# ============================================================
# STEP 33 — CATEGORIZE EXPORT
# Livraria Alexandria
#
# Exporta livros pendentes de categorização para JSON.
# Output: scripts/data/categorize_input.json
# Consumido por: agente Claude Cowork (agents/classify_cowork/)
# ============================================================

import json
import os
from datetime import datetime, timezone

from core.db import get_conn
from core.logger import log


# =========================
# CONFIG
# =========================

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "categorize_input.json")

MAX_TEXT_LEN = 800


# =========================
# FETCH
# =========================

def fetch_pending(conn, pacote):

    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT id, titulo, slug, autor, descricao, sinopse
            FROM livros
            WHERE status_categorize = 0
              AND status_review     = 1
            ORDER BY priority_score DESC, created_at ASC
            LIMIT ?
        """, (pacote,))
    except Exception:
        cur.execute("""
            SELECT id, titulo, slug, autor, descricao, NULL as sinopse
            FROM livros
            WHERE status_categorize = 0
              AND status_review     = 1
            ORDER BY created_at ASC
            LIMIT ?
        """, (pacote,))

    return cur.fetchall()


# =========================
# RUN
# =========================

def run(pacote):

    log("[CATEGORIZE_EXPORT] Iniciando exportação")

    conn = get_conn()

    rows = fetch_pending(conn, pacote)

    if not rows:
        log("[CATEGORIZE_EXPORT] Nada pendente.")
        conn.close()
        return

    livros = []

    for row in rows:

        livro_id  = row["id"]
        titulo    = row["titulo"]
        slug      = row["slug"]
        autor     = row["autor"]
        descricao = row["descricao"] or ""
        sinopse   = row["sinopse"] if row["sinopse"] else ""

        livros.append({
            "id":        livro_id,
            "slug":      slug or "",
            "titulo":    titulo,
            "autor":     autor or "",
            "descricao": descricao[:MAX_TEXT_LEN],
            "sinopse":   sinopse[:MAX_TEXT_LEN],
        })

    payload = {
        "meta": {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "total":       len(livros),
        },
        "livros": livros,
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    conn.close()

    log(f"[CATEGORIZE_EXPORT] Exportados: {len(livros)}")
    log(f"[CATEGORIZE_EXPORT] Arquivo: {os.path.abspath(OUTPUT_PATH)}")
