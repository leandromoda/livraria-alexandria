# ============================================================
# STEP 35 — COWORK EXPORT (unificado)
# Livraria Alexandria
#
# Roda synopsis_export + categorize_export em uma única chamada.
# Gera NNN_synopsis_input.json + NNN_classify_input.json (lotes de 25).
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
