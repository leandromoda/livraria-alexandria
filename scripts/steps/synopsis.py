# ============================================================
# STEP 7 — SYNOPSIS
# Livraria Alexandria
#
# Gera sinopse editorial via Gemini.
# Lê de: descricao (campo bruto)
# Grava em: sinopse (campo gerado) — NÃO toca em descricao
# Depende de: status_review=1 e is_book=1
# ============================================================

import time

from core.db import get_conn
from core.logger import log
from core.markdown_executor import execute_agent
from steps.quality_gate import check_synopsis_generic


# =========================
# CONFIG
# =========================

AGENT_PATH = "agents/synopsis"


# =========================
# FETCH
# =========================

def fetch_pending(conn, idioma, limit):

    cur = conn.cursor()

    cur.execute("""
        SELECT id, titulo, autor, idioma, descricao
        FROM livros
        WHERE status_synopsis = 0
          AND status_review   = 1
          AND is_book         = 1
          AND idioma          = ?
        LIMIT ?
    """, (idioma, limit))

    return cur.fetchall()


# =========================
# UPDATE — grava em sinopse, não em descricao
# =========================

def update_synopsis(conn, livro_id, sinopse):

    cur = conn.cursor()

    cur.execute("""
        UPDATE livros
        SET sinopse         = ?,
            status_synopsis = 1,
            updated_at      = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (sinopse, livro_id))

    conn.commit()


# =========================
# RUN
# =========================

def run(idioma, pacote):

    log("[SYNOPSIS] Iniciando geração de sinopses")

    conn = get_conn()

    rows = fetch_pending(conn, idioma, pacote)

    if not rows:
        log("[SYNOPSIS] Nada pendente.")
        conn.close()
        return

    total      = len(rows)
    start_time = time.time()

    log(f"[SYNOPSIS] {total} livros encontrados")

    for i, (livro_id, titulo, autor, idioma_livro, descricao) in enumerate(rows, start=1):

        heartbeat = int(time.time() - start_time)

        log(f"[SYNOPSIS][{i:03d}/{total:03d}] {titulo} — heartbeat {heartbeat}s")

        payload = {
            "titulo":        titulo,
            "autor":         autor,
            "idioma":        idioma_livro,
            "descricao_base": descricao or "",
        }

        try:
            result = execute_agent(AGENT_PATH, payload)
        except Exception as e:
            log(f"[SYNOPSIS] ERRO → {titulo} | {e}")
            continue

        sinopse_text = result.get("synopsis", "")

        if not sinopse_text:
            log(f"[SYNOPSIS] Falha (sinopse vazia) → {titulo}")
        elif check_synopsis_generic(sinopse_text):
            log(f"[SYNOPSIS] Rejeitada (template genérico) → {titulo}")
        else:
            log("[SYNOPSIS][TEXT_BEGIN]")
            log(sinopse_text)
            log("[SYNOPSIS][TEXT_END]")
            update_synopsis(conn, livro_id, sinopse_text)
            log(f"[SYNOPSIS] OK → {titulo}")

    conn.close()

    log("[SYNOPSIS] Finalizado")
