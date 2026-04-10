# ============================================================
# STEP 31 — SYNOPSIS EXPORT
# Livraria Alexandria
#
# Exporta livros pendentes de sinopse para JSON numerado.
# Output: scripts/data/NNN_synopsis_input.json (lote de até 25)
# Consumido por: agente Claude Cowork (agents/synopsis_cowork/)
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
PROCESSED_DIR = os.path.join(DATA_DIR, "processed_synopsis")


# =========================
# FETCH
# =========================

def fetch_pending(conn, idioma, limit):

    cur = conn.cursor()

    cur.execute("""
        SELECT id, titulo, slug, autor, idioma, descricao
        FROM livros
        WHERE status_synopsis = 0
          AND status_review   = 1
          AND is_book         = 1
          AND idioma          = ?
        ORDER BY priority_score DESC, created_at ASC
        LIMIT ?
    """, (idioma, limit))

    return cur.fetchall()


# =========================
# RUN
# =========================

def run(idioma, pacote):

    log("[SYNOPSIS_EXPORT] Iniciando exportação")

    os.makedirs(PROCESSED_DIR, exist_ok=True)

    conn = get_conn()

    rows = fetch_pending(conn, idioma, min(pacote, BATCH_SIZE))

    if not rows:
        log("[SYNOPSIS_EXPORT] Nada pendente.")
        conn.close()
        return

    livros = []
    skipped = 0

    for livro_id, titulo, slug, autor, idioma_livro, descricao in rows:

        if not descricao or not descricao.strip():
            log(f"[SYNOPSIS_EXPORT] Skip (descricao vazia) → {titulo}")
            skipped += 1
            continue

        livros.append({
            "id":        livro_id,
            "slug":      slug or "",
            "titulo":    titulo,
            "autor":     autor or "",
            "idioma":    idioma_livro,
            "descricao": descricao,
        })

    if not livros:
        log("[SYNOPSIS_EXPORT] Nenhum livro com descricao válida.")
        conn.close()
        return

    num = next_batch_number(DATA_DIR, "synopsis")
    output_path = os.path.join(DATA_DIR, f"{num}_synopsis_input.json")

    payload = {
        "meta": {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "idioma":      idioma,
            "batch":       num,
            "total":       len(livros),
        },
        "livros": livros,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    conn.close()

    log(f"[SYNOPSIS_EXPORT] Exportados: {len(livros)} | Skipped: {skipped}")
    log(f"[SYNOPSIS_EXPORT] Arquivo: {os.path.abspath(output_path)}")
