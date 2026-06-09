# ============================================================
# STEP 36 — BATCH IMPORT (unificado)
# Livraria Alexandria
#
# Roda synopsis_import + categorize_import + apply_blacklist em uma
# única chamada. Processa todos NNN_synopsis_output.json e
# NNN_classify_output.json disponíveis, movendo cada um para
# processed_synopsis/ ou processed_classify/ após importar.
# ============================================================

from core.logger import log
from steps import synopsis_import
from steps import categorize_import
from steps import apply_blacklist


def run():

    log("[BATCH_IMPORT] Iniciando importação unificada")

    log("[BATCH_IMPORT] --- Synopsis Import ---")
    synopsis_import.run()

    log("[BATCH_IMPORT] --- Categorize Import ---")
    categorize_import.run()

    log("[BATCH_IMPORT] --- Apply Blacklist ---")
    try:
        apply_blacklist.run(dry_run=False)
    except (SystemExit, FileNotFoundError):
        log("[BATCH_IMPORT] Blacklist: arquivo não encontrado (ok, será criado quando necessário)")

    log("[BATCH_IMPORT] Importação unificada concluída")
