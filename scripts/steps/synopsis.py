# ============================================================
# STEP 11 — SYNOPSIS (motor único: batch via Claude CLI)
# Livraria Alexandria
#
# Gera sinopse editorial usando o ÚNICO motor de sinopse do
# pipeline: o agente batch `synopsis_cowork` (Claude CLI).
#
# Fluxo: synopsis_export → run_agent(synopsis_cowork) → synopsis_import
#
# O motor FSM per-item (4 estágios via markdown_executor) foi
# aposentado em favor do batch — ~50x menos chamadas na quota PRO
# e validação determinística no import (synopsis_import.validate_synopsis).
# ============================================================

from core.claude_runner import agent_prompt_path, run_agent
from core.logger import log
from steps import synopsis_export, synopsis_import

# Timeout generoso: o agente gera o lote inteiro numa sessão.
AGENT_TIMEOUT = 900

_LLM_LIMIT_MARKERS = ("CLAUDE_SESSION_LIMIT_REACHED", "limit", "usage limit")


def run(idioma, pacote, book_ids=None):
    """Gera sinopses via o motor batch (agente synopsis_cowork no Claude CLI).

    Args:
        idioma:   idioma do filtro batch (ignorado quando book_ids é dado).
        pacote:   máximo de livros a exportar nesta invocação (cap em 25/lote).
        book_ids: lista opcional de IDs (modo per-livro da ingestão guiada).
    """
    log("[SYNOPSIS] Iniciando geração (motor batch synopsis_cowork)")

    exported = synopsis_export.run(idioma, pacote, book_ids=book_ids)
    if not exported:
        log("[SYNOPSIS] Nada pendente.")
        return

    log(f"[SYNOPSIS] {exported} livro(s) exportado(s) — invocando agente synopsis_cowork…")
    # wait_on_limit=False: não bloquear 5h no menu/ingestão guiada — ao bater o
    # limite, retorna na hora com mensagem (o usuário re-roda após o reset).
    success, output = run_agent(agent_prompt_path("synopsis_cowork"),
                                timeout=AGENT_TIMEOUT, wait_on_limit=False)

    if not success:
        if any(m.lower() in output.lower() for m in _LLM_LIMIT_MARKERS):
            log("[SYNOPSIS] ⚠️ Limite de sessão Claude atingido — livros ficam em "
                "status_synopsis=3 até o próximo ciclo/reclaim reprocessar o input.")
        else:
            log(f"[SYNOPSIS] ✗ Agente falhou: {output[:200]}")
        return

    log("[SYNOPSIS] ✓ Agente concluído — importando resultados…")
    synopsis_import.run()
    log("[SYNOPSIS] Finalizado")
