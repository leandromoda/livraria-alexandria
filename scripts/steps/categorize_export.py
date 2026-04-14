# ============================================================
# STEP 33 — CATEGORIZE EXPORT
# Livraria Alexandria
#
# Exporta livros pendentes de categorização para JSON numerado.
# Output: scripts/data/NNN_categorize_input.json (lote de até 25)
# Consumido por: agente Claude Cowork (agents/classify_cowork/)
# ============================================================

import json
import os
from datetime import datetime, timezone

from core.cowork_numbering import next_batch_number
from core.db import get_conn
from core.logger import log


# =========================
# CONFIG
# =========================

BATCH_SIZE    = 25
DATA_DIR      = os.path.join(os.path.dirname(__file__), "..", "data")
COWORK_DIR    = os.path.join(DATA_DIR, "cowork")
PROCESSED_DIR = os.path.join(COWORK_DIR, "processed_categorize")

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

    os.makedirs(COWORK_DIR, exist_ok=True)
    os.makedirs(PROCESSED_DIR, exist_ok=True)

    conn = get_conn()

    rows = fetch_pending(conn, min(pacote, BATCH_SIZE))

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

    num = next_batch_number(COWORK_DIR, "categorize")
    output_path = os.path.join(COWORK_DIR, f"{num}_categorize_input.json")

    payload = {
        "meta": {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "batch":       num,
            "total":       len(livros),
        },
        "livros": livros,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # Marca como "em fila para o agente" (3) para que o próximo export
    # não selecione os mesmos livros. O import reverte para 0 se rejeitado.
    ids = [l["id"] for l in livros]
    cur = conn.cursor()
    cur.executemany(
        "UPDATE livros SET status_categorize = 3, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        [(lid,) for lid in ids],
    )
    conn.commit()
    conn.close()

    log(f"[CATEGORIZE_EXPORT] Exportados: {len(livros)}")
    log(f"[CATEGORIZE_EXPORT] Arquivo: {os.path.abspath(output_path)}")
