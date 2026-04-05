# ============================================================
# STEP 32 — SYNOPSIS IMPORT
# Livraria Alexandria
#
# Importa sinopses geradas pelo agente Claude Cowork.
# Input: scripts/data/synopsis_output.json
# Grava em: sinopse + status_synopsis no SQLite
# ============================================================

import json
import os
import re

from core.db import get_conn
from core.logger import log
from steps.quality_gate import check_synopsis_generic


# =========================
# CONFIG
# =========================

INPUT_PATH     = os.path.join(os.path.dirname(__file__), "..", "data", "synopsis_output.json")
BLACKLIST_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "blacklist.json")

MIN_SYNOPSIS_LEN = 400

META_ARTIFACTS = [
    "[SYSTEM]",
    "[PROCESS]",
    "[TASK]",
]


# =========================
# VALIDATION
# =========================

def validate_synopsis(sinopse):
    """Valida sinopse antes de gravar. Retorna (ok, motivo)."""

    if not sinopse or not sinopse.strip():
        return False, "sinopse vazia"

    if len(sinopse) < MIN_SYNOPSIS_LEN:
        return False, f"muito curta ({len(sinopse)} chars, min {MIN_SYNOPSIS_LEN})"

    if check_synopsis_generic(sinopse):
        return False, "marcador genérico detectado"

    for artifact in META_ARTIFACTS:
        if artifact in sinopse:
            return False, f"artefato meta detectado: {artifact}"

    if re.search(r"^#{1,6}\s", sinopse, re.MULTILINE):
        return False, "heading markdown detectado"

    return True, ""


# =========================
# RUN
# =========================

def run():

    log("[SYNOPSIS_IMPORT] Iniciando importação")

    if not os.path.exists(INPUT_PATH):
        log(f"[SYNOPSIS_IMPORT] Arquivo não encontrado: {INPUT_PATH}")
        log("[SYNOPSIS_IMPORT] Rode a opção 31 (Export) e o agente Claude Cowork primeiro.")
        return

    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    resultados = data.get("resultados", [])

    if not resultados:
        log("[SYNOPSIS_IMPORT] Nenhum resultado no arquivo.")
        return

    conn = get_conn()
    cur  = conn.cursor()

    ok = rejeitados = ja_processados = erros = 0

    for i, item in enumerate(resultados, start=1):

        livro_id = item.get("id", "")
        sinopse  = item.get("sinopse", "")
        status   = item.get("status", "")
        motivo   = item.get("motivo", "")

        # Buscar titulo para log
        cur.execute("SELECT titulo, status_synopsis FROM livros WHERE id = ?", (livro_id,))
        row = cur.fetchone()

        if not row:
            log(f"[SYNOPSIS_IMPORT][{i:03d}] ID não encontrado: {livro_id}")
            erros += 1
            continue

        titulo, status_atual = row

        # Idempotência
        if status_atual == 1:
            log(f"[SYNOPSIS_IMPORT][{i:03d}] Já processado → {titulo}")
            ja_processados += 1
            continue

        # Rejeitado pelo Claude
        if status != "APPROVED":
            log(f"[SYNOPSIS_IMPORT][{i:03d}] Rejeitado pelo agente ({motivo}) → {titulo}")
            rejeitados += 1
            continue

        # Validação Python (safety net)
        valido, razao = validate_synopsis(sinopse)

        if not valido:
            log(f"[SYNOPSIS_IMPORT][{i:03d}] Rejeitado na validação ({razao}) → {titulo}")
            rejeitados += 1
            continue

        # Gravar
        try:
            cur.execute("""
                UPDATE livros
                SET sinopse         = ?,
                    status_synopsis = 1,
                    updated_at      = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (sinopse, livro_id))
            conn.commit()

            log(f"[SYNOPSIS_IMPORT][{i:03d}] OK → {titulo}")
            ok += 1

        except Exception as e:
            log(f"[SYNOPSIS_IMPORT][{i:03d}] ERRO → {titulo} | {e}")
            erros += 1

    conn.close()

    # --- Blacklist merge ---
    blacklist_entries = data.get("blacklist", [])
    if blacklist_entries:
        from core.blacklist_merge import merge_blacklist
        added = merge_blacklist(blacklist_entries, BLACKLIST_PATH)
        log(f"[SYNOPSIS_IMPORT] Blacklist: {added} nova(s) entrada(s) adicionada(s)")

    log("[SYNOPSIS_IMPORT] Finalizado")
    log(f"OK: {ok} | Rejeitados: {rejeitados} | Já processados: {ja_processados} | Erros: {erros} | Total: {len(resultados)}")
