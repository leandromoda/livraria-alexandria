# ============================================================
# STEP 34 — CATEGORIZE IMPORT
# Livraria Alexandria
#
# Importa categorias geradas pelo agente Claude Cowork.
# Input: scripts/data/categorize_output.json
# Grava em: livros_categorias_tematicas + status_categorize
# ============================================================

import json
import os

from core.db import get_conn
from core.logger import log


# =========================
# CONFIG
# =========================

BASE_DIR       = os.path.dirname(os.path.dirname(__file__))
INPUT_PATH     = os.path.join(BASE_DIR, "data", "categorize_output.json")
TAXONOMY_PATH  = os.path.join(BASE_DIR, "data", "taxonomy.json")
BLACKLIST_PATH = os.path.join(BASE_DIR, "data", "blacklist.json")

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
# RUN
# =========================

def run():

    log("[CATEGORIZE_IMPORT] Iniciando importação")

    if not os.path.exists(INPUT_PATH):
        log(f"[CATEGORIZE_IMPORT] Arquivo não encontrado: {INPUT_PATH}")
        log("[CATEGORIZE_IMPORT] Rode a opção 33 (Export) e o agente Claude Cowork primeiro.")
        return

    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    resultados = data.get("resultados", [])

    if not resultados:
        log("[CATEGORIZE_IMPORT] Nenhum resultado no arquivo.")
        return

    taxonomy = load_taxonomy()
    conn     = get_conn()
    cur      = conn.cursor()

    ok = rejeitados = ja_processados = erros = 0

    for i, item in enumerate(resultados, start=1):

        livro_id   = item.get("id", "")
        categorias = item.get("categorias", [])
        status     = item.get("status", "")
        motivo     = item.get("motivo", "")

        # Buscar titulo para log
        cur.execute("SELECT titulo, status_categorize FROM livros WHERE id = ?", (livro_id,))
        row = cur.fetchone()

        if not row:
            log(f"[CATEGORIZE_IMPORT][{i:03d}] ID não encontrado: {livro_id}")
            erros += 1
            continue

        titulo, status_atual = row

        # Idempotência
        if status_atual == 1:
            log(f"[CATEGORIZE_IMPORT][{i:03d}] Já processado → {titulo}")
            ja_processados += 1
            continue

        # Rejeitado pelo Claude
        if status != "CLASSIFIED":
            log(f"[CATEGORIZE_IMPORT][{i:03d}] Rejeitado pelo agente ({motivo}) → {titulo}")
            rejeitados += 1
            continue

        # Validação Python (safety net)
        valido, razao = validate_categorias(categorias, taxonomy)

        if not valido:
            log(f"[CATEGORIZE_IMPORT][{i:03d}] Rejeitado na validação ({razao}) → {titulo}")
            rejeitados += 1
            continue

        # Gravar
        try:
            save_categories(conn, livro_id, categorias)
            log(f"[CATEGORIZE_IMPORT][{i:03d}] OK → {titulo} → {categorias}")
            ok += 1

        except Exception as e:
            log(f"[CATEGORIZE_IMPORT][{i:03d}] ERRO → {titulo} | {e}")
            erros += 1

    conn.close()

    # --- Blacklist merge ---
    blacklist_entries = data.get("blacklist", [])
    if blacklist_entries:
        from core.blacklist_merge import merge_blacklist
        added = merge_blacklist(blacklist_entries, BLACKLIST_PATH)
        log(f"[CATEGORIZE_IMPORT] Blacklist: {added} nova(s) entrada(s) adicionada(s)")

    log("[CATEGORIZE_IMPORT] Finalizado")
    log(f"OK: {ok} | Rejeitados: {rejeitados} | Já processados: {ja_processados} | Erros: {erros} | Total: {len(resultados)}")
