# ============================================================
# STEP 32 — SYNOPSIS IMPORT
# Livraria Alexandria
#
# Importa sinopses geradas pelo agente Claude Cowork.
# Input: scripts/data/NNN_synopsis_output.json (todos disponíveis)
# Grava em: sinopse + status_synopsis no SQLite
# Move processados para: scripts/data/processed_synopsis/
# ============================================================

import json
import os
import re
import shutil

from core.db import get_conn
from core.logger import log
from steps.quality_gate import check_synopsis_generic


# =========================
# CONFIG
# =========================

DATA_DIR       = os.path.join(os.path.dirname(__file__), "..", "data")
COWORK_DIR     = os.path.join(DATA_DIR, "cowork")
PROCESSED_DIR  = os.path.join(COWORK_DIR, "processed_synopsis")
BLACKLIST_PATH = os.path.join(DATA_DIR, "blacklist.json")
OUTPUT_PAT     = re.compile(r"^(\d{3})_synopsis_output\.json$")

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
# FIND OUTPUT FILES
# =========================

def find_output_files(data_dir):
    """Retorna lista de (num_int, filepath) ordenada por número crescente."""
    results = []
    for fname in os.listdir(data_dir):
        m = OUTPUT_PAT.match(fname)
        if m:
            results.append((int(m.group(1)), os.path.join(data_dir, fname)))
    return sorted(results, key=lambda x: x[0])


# =========================
# PROCESS ONE FILE
# =========================

def _process_file(filepath, conn, cur):
    """Processa um arquivo de output. Retorna (ok, rejeitados, ja_processados, erros)."""

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    resultados = data.get("resultados", [])

    if not resultados:
        log(f"[SYNOPSIS_IMPORT] Nenhum resultado em {os.path.basename(filepath)}")
        return 0, 0, 0, 0

    ok = rejeitados = ja_processados = erros = 0

    for i, item in enumerate(resultados, start=1):

        livro_id = item.get("id", "")
        sinopse  = item.get("sinopse", "")
        status   = item.get("status", "")
        motivo   = item.get("motivo", "")

        cur.execute("SELECT titulo, status_synopsis FROM livros WHERE id = ?", (livro_id,))
        row = cur.fetchone()

        if not row:
            log(f"[SYNOPSIS_IMPORT][{i:03d}] ID não encontrado: {livro_id}")
            erros += 1
            continue

        titulo, status_atual = row

        if status_atual == 1:
            log(f"[SYNOPSIS_IMPORT][{i:03d}] Já processado → {titulo}")
            ja_processados += 1
            continue

        if status != "APPROVED":
            log(f"[SYNOPSIS_IMPORT][{i:03d}] Rejeitado pelo agente ({motivo}) → {titulo}")
            cur.execute(
                "UPDATE livros SET status_synopsis = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (livro_id,),
            )
            conn.commit()
            rejeitados += 1
            continue

        valido, razao = validate_synopsis(sinopse)

        if not valido:
            log(f"[SYNOPSIS_IMPORT][{i:03d}] Rejeitado na validação ({razao}) → {titulo}")
            cur.execute(
                "UPDATE livros SET status_synopsis = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (livro_id,),
            )
            conn.commit()
            rejeitados += 1
            continue

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

    # Blacklist merge
    blacklist_entries = data.get("blacklist", [])
    if blacklist_entries:
        from core.blacklist_merge import merge_blacklist
        added = merge_blacklist(blacklist_entries, BLACKLIST_PATH)
        fname = os.path.basename(filepath)
        log(f"[SYNOPSIS_IMPORT] Blacklist de {fname}: {added} nova(s) entrada(s)")

    return ok, rejeitados, ja_processados, erros


# =========================
# RUN
# =========================

def run():

    log("[SYNOPSIS_IMPORT] Iniciando importação")

    os.makedirs(PROCESSED_DIR, exist_ok=True)

    output_files = find_output_files(COWORK_DIR)

    if not output_files:
        log("[SYNOPSIS_IMPORT] Nenhum *_synopsis_output.json encontrado.")
        log("[SYNOPSIS_IMPORT] Rode a opção 31 (Export) e o agente Claude Cowork primeiro.")
        return

    log(f"[SYNOPSIS_IMPORT] {len(output_files)} arquivo(s) encontrado(s)")

    conn = get_conn()
    cur  = conn.cursor()

    total_ok = total_rej = total_ja = total_err = 0

    for _num, filepath in output_files:
        fname = os.path.basename(filepath)
        log(f"[SYNOPSIS_IMPORT] Processando {fname}…")

        ok, rej, ja, err = _process_file(filepath, conn, cur)
        total_ok += ok
        total_rej += rej
        total_ja  += ja
        total_err += err

        dest = os.path.join(PROCESSED_DIR, fname)
        try:
            shutil.move(filepath, dest)
            log(f"[SYNOPSIS_IMPORT] Movido → processed_synopsis/{fname}")
        except Exception as e:
            log(f"[SYNOPSIS_IMPORT] AVISO: falha ao mover {fname}: {e}")

    conn.close()

    log("[SYNOPSIS_IMPORT] Finalizado")
    log(f"OK: {total_ok} | Rejeitados: {total_rej} | Já processados: {total_ja} | Erros: {total_err}")
