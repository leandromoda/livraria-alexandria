# ============================================================
# STEP 10 — CATEGORIZE (motor único: batch via Claude CLI)
# Livraria Alexandria
#
# Classifica cada livro em até 5 categorias temáticas da
# taxonomy.json usando o ÚNICO motor de categorização do
# pipeline: o agente batch `classify_cowork` (Claude CLI).
#
# Fluxo: categorize_export → run_agent(classify_cowork) → categorize_import
#
# O caminho per-item (_call_llm + prompt inline) foi aposentado em
# favor do batch (WS2) — menos chamadas na quota PRO e um único prompt
# de taxonomia (sem divergência com classify_cowork).
#
# Funções de manutenção (reset_failed, reset_wrong_category) são
# preservadas — usadas pelo menu (opções 10/10R).
# ============================================================

import os

from core.claude_runner import agent_prompt_path, run_agent
from core.db import get_conn
from core.logger import log
from steps import categorize_export, categorize_import

MAX_CATEGORIZE_ATTEMPTS = int(os.getenv("MAX_CATEGORIZE_ATTEMPTS", "3"))

# Timeout generoso: o agente classifica o lote inteiro numa sessão.
AGENT_TIMEOUT = 900

_LLM_LIMIT_MARKERS = ("CLAUDE_SESSION_LIMIT_REACHED", "limit", "usage limit")


# =========================
# RESET FAILED
# =========================

def reset_failed(conn=None):
    """Reseta livros com status_categorize=2 para 0, respeitando MAX_CATEGORIZE_ATTEMPTS."""
    close_conn = conn is None
    if conn is None:
        conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        UPDATE livros
        SET status_categorize = 0,
            updated_at        = CURRENT_TIMESTAMP
        WHERE status_categorize = 2
          AND COALESCE(categorize_attempts, 0) < ?
    """, (MAX_CATEGORIZE_ATTEMPTS,))
    conn.commit()
    affected = cur.rowcount

    cur.execute("""
        SELECT COUNT(*) FROM livros
        WHERE status_categorize = 2
          AND COALESCE(categorize_attempts, 0) >= ?
    """, (MAX_CATEGORIZE_ATTEMPTS,))
    exhausted = cur.fetchone()[0]

    if close_conn:
        conn.close()

    log(f"[CATEGORIZE] reset_failed: {affected} livro(s) revertidos para status_categorize=0")
    if exhausted:
        log(f"[CATEGORIZE] reset_failed: {exhausted} livro(s) ignorados (>= {MAX_CATEGORIZE_ATTEMPTS} tentativas sem categoria)")
    return affected


# =========================
# RESET WRONG CATEGORY
# =========================

def reset_wrong_category(conn, categoria_slug):
    """Remove todas as categorizações com o slug errado e reseta status_categorize=0.

    Retorna lista de livro_ids afetados.
    """
    cur = conn.cursor()
    cur.execute(
        "SELECT DISTINCT livro_id FROM livros_categorias_tematicas WHERE categoria_slug = ?",
        (categoria_slug,)
    )
    livro_ids = [r[0] for r in cur.fetchall()]

    if not livro_ids:
        return []

    placeholders = ",".join("?" * len(livro_ids))
    cur.execute(
        f"DELETE FROM livros_categorias_tematicas WHERE livro_id IN ({placeholders})",
        livro_ids
    )
    cur.execute(
        f"""UPDATE livros
            SET status_categorize  = 0,
                status_publish_cat = 0,
                updated_at         = CURRENT_TIMESTAMP
            WHERE id IN ({placeholders})""",
        livro_ids
    )
    conn.commit()
    return livro_ids


# =========================
# RUN — motor batch
# =========================

def run(idioma=None, pacote=50, book_ids=None):
    """Categoriza livros via o motor batch (agente classify_cowork no Claude CLI).

    Args:
        idioma:   não usado no filtro, mantido por compatibilidade.
        pacote:   máximo de livros a exportar nesta invocação (cap em 25/lote).
        book_ids: lista opcional de IDs (modo per-livro da ingestão guiada).
    """
    log("[CATEGORIZE] Iniciando classificação (motor batch classify_cowork)")

    exported = categorize_export.run(pacote, book_ids=book_ids)
    if not exported:
        log("[CATEGORIZE] Nada pendente.")
        return

    log(f"[CATEGORIZE] {exported} livro(s) exportado(s) — invocando agente classify_cowork…")
    # wait_on_limit=False: não bloquear 5h no menu/ingestão guiada (re-roda após reset).
    success, output = run_agent(agent_prompt_path("classify_cowork"),
                                timeout=AGENT_TIMEOUT, wait_on_limit=False)

    if not success:
        if any(m.lower() in output.lower() for m in _LLM_LIMIT_MARKERS):
            log("[CATEGORIZE] ⚠️ Limite de sessão Claude atingido — livros ficam em "
                "status_categorize=3 até o próximo ciclo/reclaim reprocessar o input.")
        else:
            log(f"[CATEGORIZE] ✗ Agente falhou: {output[:200]}")
        return

    log("[CATEGORIZE] ✓ Agente concluído — importando resultados…")
    categorize_import.run()
    log("[CATEGORIZE] Finalizado")
