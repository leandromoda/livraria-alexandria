# ============================================================
# STEP 36 — COWORK IMPORT (unificado)
# Livraria Alexandria
#
# Roda synopsis_import + categorize_import + apply_blacklist
# em uma única chamada.
# ============================================================

from core.logger import log
from steps import synopsis_import
from steps import categorize_import
from steps import apply_blacklist


def run():

    log("[COWORK_IMPORT] Iniciando importação unificada")

    log("[COWORK_IMPORT] --- Synopsis Import ---")
    synopsis_import.run()

    log("[COWORK_IMPORT] --- Categorize Import ---")
    categorize_import.run()

    log("[COWORK_IMPORT] --- Apply Blacklist ---")
    try:
        apply_blacklist.run(dry_run=False)
    except (SystemExit, FileNotFoundError):
        log("[COWORK_IMPORT] Blacklist: arquivo não encontrado (ok, será criado quando necessário)")

    log("[COWORK_IMPORT] Importação unificada concluída")
