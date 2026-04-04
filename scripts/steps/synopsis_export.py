# ============================================================
# STEP 31 — SYNOPSIS EXPORT
# Livraria Alexandria
#
# Exporta livros pendentes de sinopse para JSON.
# Output: scripts/data/synopsis_input.json
# Consumido por: agente Claude Cowork (agents/synopsis_cowork/)
# ============================================================

import json
import os
from datetime import datetime, timezone

from core.db import get_conn
from core.logger import log


# =========================
# CONFIG
# =========================

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "synopsis_input.json")


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

    conn = get_conn()

    rows = fetch_pending(conn, idioma, pacote)

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

    payload = {
        "meta": {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "idioma":      idioma,
            "total":       len(livros),
        },
        "livros": livros,
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    conn.close()

    log(f"[SYNOPSIS_EXPORT] Exportados: {len(livros)} | Skipped: {skipped}")
    log(f"[SYNOPSIS_EXPORT] Arquivo: {os.path.abspath(OUTPUT_PATH)}")
    log("")
    log("=== PRÓXIMO PASSO ===")
    log("1. Abra uma sessão Claude Cowork")
    log("2. Peça para ler scripts/data/synopsis_input.json")
    log("3. Aplique as regras de agents/synopsis_cowork/prompt.md")
    log("4. Salve o resultado em scripts/data/synopsis_output.json")
    log("5. Volte ao pipeline e rode a opção 32 (Importar Sinopses)")
