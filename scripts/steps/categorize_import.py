# ============================================================
# STEP 34 — CATEGORIZE IMPORT
# Livraria Alexandria
#
# Importa categorias geradas pelo agente Claude Cowork.
# Input: scripts/data/NNN_categorize_output.json (todos disponíveis)
# Grava em: livros_categorias_tematicas + status_categorize
# Move processados para: scripts/data/processed_categorize/
# ============================================================

import json
import os
import re
import shutil

from core.db import get_conn
from core.logger import log


# =========================
# CONFIG
# =========================

DATA_DIR       = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
PROCESSED_DIR  = os.path.join(DATA_DIR, "processed_categorize")
TAXONOMY_PATH  = os.path.join(DATA_DIR, "taxonomy.json")
BLACKLIST_PATH = os.path.join(DATA_DIR, "blacklist.json")
OUTPUT_PAT     = re.compile(r"^(\d{3})_categorize_output\.json$")

MAX_CATEGORIES = 5


# =========================
# LOAD TAXONOMY
# =========================

def load_taxonomy():
    with open(TAXONOMY_PATH, "r", encoding="utf-8") as f:
        items = json.load(f)
    return {item["slug"]: item for item in items}


# =========================
# VALIDATION
# =========================

def validate_categorias(categorias, taxonomy):
    """Valida lista de slugs. Retorna (ok, motivo)."""

    if not categorias or not isinstance(categorias, list):
        return False, "categorias vazia ou inválida"

    if len(categorias) > MAX_CATEGORIES:
        return False, f"excede máximo ({len(categorias)}, max {MAX_CATEGORIES})"

    invalid = [s for s in categorias if s not in taxonomy]
    if invalid:
        return False, f"slugs inválidos: {invalid}"

    return True, ""


# =========================
# SAVE (reutiliza lógica de categorize.py)
# =========================

def save_categories(conn, livro_id, slugs):
    """Insere em livros_categorias_tematicas com confidence decrescente."""

    for i, slug in enumerate(slugs[:MAX_CATEGORIES]):
        primary    = 1 if i == 0 else 0
        confidence = round(1.0 - i * 0.1, 1)

        conn.execute("""
            INSERT OR IGNORE INTO livros_categorias_tematicas
                (livro_id, categoria_slug, confidence, primary_cat, created_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (livro_id, slug, confidence, primary))

    conn.execute("""
        UPDATE livros
        SET status_categorize = 1,
            updated_at        = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (livro_id,))

    conn.commit()


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

def _process_file(filepath, taxonomy, conn, cur):
    """Processa um arquivo de output. Retorna (ok, rejeitados, ja_processados, erros)."""

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    resultados = data.get("resultados", [])

    if not resultados:
        log(f"[CATEGORIZE_IMPORT] Nenhum resultado em {os.path.basename(filepath)}")
        return 0, 0, 0, 0

    ok = rejeitados = ja_processados = erros = 0

    for i, item in enumerate(resultados, start=1):

        livro_id   = item.get("id", "")
        categorias = item.get("categorias", [])
        status     = item.get("status", "")
        motivo     = item.get("motivo", "")

        cur.execute("SELECT titulo, status_categorize FROM livros WHERE id = ?", (livro_id,))
        row = cur.fetchone()

        if not row:
            log(f"[CATEGORIZE_IMPORT][{i:03d}] ID não encontrado: {livro_id}")
            erros += 1
            continue

        titulo, status_atual = row

        if status_atual == 1:
            log(f"[CATEGORIZE_IMPORT][{i:03d}] Já processado → {titulo}")
            ja_processados += 1
            continue

        if status != "CLASSIFIED":
            log(f"[CATEGORIZE_IMPORT][{i:03d}] Rejeitado pelo agente ({motivo}) → {titulo}")
            cur.execute(
                "UPDATE livros SET status_categorize = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (livro_id,),
            )
            conn.commit()
            rejeitados += 1
            continue

        valido, razao = validate_categorias(categorias, taxonomy)

        if not valido:
            log(f"[CATEGORIZE_IMPORT][{i:03d}] Rejeitado na validação ({razao}) → {titulo}")
            cur.execute(
                "UPDATE livros SET status_categorize = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (livro_id,),
            )
            conn.commit()
            rejeitados += 1
            continue

        try:
            save_categories(conn, livro_id, categorias)
            log(f"[CATEGORIZE_IMPORT][{i:03d}] OK → {titulo} → {categorias}")
            ok += 1

        except Exception as e:
            log(f"[CATEGORIZE_IMPORT][{i:03d}] ERRO → {titulo} | {e}")
            erros += 1

    # Blacklist merge
    blacklist_entries = data.get("blacklist", [])
    if blacklist_entries:
        from core.blacklist_merge import merge_blacklist
        added = merge_blacklist(blacklist_entries, BLACKLIST_PATH)
        fname = os.path.basename(filepath)
        log(f"[CATEGORIZE_IMPORT] Blacklist de {fname}: {added} nova(s) entrada(s)")

    return ok, rejeitados, ja_processados, erros


# =========================
# RUN
# =========================

def run():

    log("[CATEGORIZE_IMPORT] Iniciando importação")

    os.makedirs(PROCESSED_DIR, exist_ok=True)

    output_files = find_output_files(DATA_DIR)

    if not output_files:
        log("[CATEGORIZE_IMPORT] Nenhum *_categorize_output.json encontrado.")
        log("[CATEGORIZE_IMPORT] Rode a opção 33 (Export) e o agente Claude Cowork primeiro.")
        return

    log(f"[CATEGORIZE_IMPORT] {len(output_files)} arquivo(s) encontrado(s)")

    taxonomy = load_taxonomy()
    conn     = get_conn()
    cur      = conn.cursor()

    total_ok = total_rej = total_ja = total_err = 0

    for _num, filepath in output_files:
        fname = os.path.basename(filepath)
        log(f"[CATEGORIZE_IMPORT] Processando {fname}…")

        ok, rej, ja, err = _process_file(filepath, taxonomy, conn, cur)
        total_ok += ok
        total_rej += rej
        total_ja  += ja
        total_err += err

        dest = os.path.join(PROCESSED_DIR, fname)
        try:
            shutil.move(filepath, dest)
            log(f"[CATEGORIZE_IMPORT] Movido → processed_categorize/{fname}")
        except Exception as e:
            log(f"[CATEGORIZE_IMPORT] AVISO: falha ao mover {fname}: {e}")

    conn.close()

    log("[CATEGORIZE_IMPORT] Finalizado")
    log(f"OK: {total_ok} | Rejeitados: {total_rej} | Já processados: {total_ja} | Erros: {total_err}")
