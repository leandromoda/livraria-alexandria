# ============================================================
# STEP 35 — COWORK EXPORT (unificado)
# Livraria Alexandria
#
# Roda synopsis_export + categorize_export em uma única chamada.
# ============================================================

from core.logger import log
from steps import synopsis_export
from steps import categorize_export


def run(idioma, pacote):

    log("[COWORK_EXPORT] Iniciando exportação unificada")

    log("[COWORK_EXPORT] --- Synopsis Export ---")
    synopsis_export.run(idioma, pacote)

    log("[COWORK_EXPORT] --- Categorize Export ---")
    categorize_export.run(pacote)

    log("[COWORK_EXPORT] Exportação unificada concluída")
    log("")
    log("=== PRÓXIMO PASSO ===")
    log("Execute o agente cowork_autopilot para processar ambos os inputs:")
    log("  Leia agents/cowork_autopilot/prompt.md e execute as instruções.")
