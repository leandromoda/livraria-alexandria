# ============================================================
# STEP 34 — CATEGORIZE IMPORT
# Livraria Alexandria
#
# Importa categorias geradas pelo agente Claude Batch.
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
BATCH_DIR     = os.path.join(DATA_DIR, "batch")
PROCESSED_DIR  = os.path.join(BATCH_DIR, "processed_categorize")
TAXONOMY_PATH  = os.path.join(DATA_DIR, "taxonomy.json")
BLACKLIST_PATH = os.path.join(DATA_DIR, "blacklist.json")
OUTPUT_PAT     = re.compile(r"^(\d+)_categorize_output\.json$")

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
# REJEIÇÃO
# =========================

def _marcar_rejeitado(cur, conn, livro_id, status, motivo):
    """Registra a rejeição TIRANDO o livro da fila, em vez de devolvê-lo a ela.

    ⚠ Até 2026-08-29 esta função não existia e a rejeição gravava
    `status_categorize = 0` — a MESMA fila de `categorize_export.fetch_pending`,
    e na mesma posição, porque o `ORDER BY priority_score DESC, created_at ASC`
    é determinístico e a rejeição não muda nenhuma das duas colunas. O livro era
    reexportado no lote seguinte e rejeitado de novo, sem teto.

    Medido nos 3 logs de 2026-08-27..29 (n=547 rejeições, contando
    `Rejeitado pelo agente` contra `→ classify: invocando claude CLI`):

    | log | chamadas | OK | rejeitados | % do lote |
    |---|---|---|---|---|
    | 2026-08-27_19-22-47 | 46 | 630 | 420 | 40,0% |
    | 2026-08-29_05-45-10 | 10 | 145 | 105 | 42,0% |
    | 2026-08-29_07-54-02 |  3 |  28 |  22 | 44,0% |

    As 547 rejeições eram de **32 livros distintos**; nove deles apareceram
    **54 vezes cada** (`How to Brew`, `The Essential Woodworker`,
    `Artisan Breads Every Day`…). Com a sinopse em 0 exportáveis, o classify é o
    único ocupante da janela LLM (5-6 chamadas / 5h), então isso era ~40% do
    gargalo do projeto girando em falso.

    A causa de fundo é a taxonomia, não o agente: `taxonomy.json` tem 171
    categorias em 23 grupos, todos de literatura e humanidades, e nenhuma cobre
    cervejaria (214 rejeições), marcenaria (164) ou culinária (144) — 95% do
    total. O agente estava certo em rejeitar. Ver TASK-CLASSIFY-001 e
    TASK-TAX-001.

    O destino é `status_categorize = 2` e não um estado novo porque a máquina de
    retry JÁ EXISTIA e nunca tinha sido ligada: `MAX_CATEGORIZE_ATTEMPTS` e o
    guard de `categorize_attempts` em `categorize.reset_failed()` liam um estado
    que **nada no código escrevia** (grep em todo `scripts/`), e os logs de
    arquivo confirmam — `reset_failed: 0 livro(s)`, sempre. Mesma classe do
    `UNAVAIL_THRESHOLD = 2` que o PR #303 tirou do papel.

    Não seta `qa_quarantine`: o `synopsis_import` seta porque sem sinopse o livro
    trava o Quality Gate, mas falta de categoria temática não bloqueia publicação
    — e `qa_quarantine` também tiraria o livro da fila de sinopse.
    """
    cur.execute(
        """UPDATE livros
           SET status_categorize   = ?,
               categorize_attempts = COALESCE(categorize_attempts, 0) + 1,
               categorize_motivo   = ?,
               updated_at          = CURRENT_TIMESTAMP
           WHERE id = ?""",
        (status, motivo, livro_id),
    )
    conn.commit()


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

        cur.execute("SELECT titulo, autor, status_categorize, is_publishable FROM livros WHERE id = ?", (livro_id,))
        row = cur.fetchone()

        if not row:
            log(f"[CATEGORIZE_IMPORT][{i:03d}] ID não encontrado: {livro_id}")
            erros += 1
            continue

        titulo, autor, status_atual, is_publishable = row

        if status_atual == 1:
            log(f"[CATEGORIZE_IMPORT][{i:03d}] Já processado → {titulo}")
            ja_processados += 1
            continue

        # status_categorize=4 → livro blacklistado; não reverter para 0
        _rejected_status = 4 if not is_publishable else 2

        if status != "CLASSIFIED":
            motivo_str = str(motivo).strip() if motivo else ""
            if not motivo_str or motivo_str.lower() == "none":
                # Rejeição SEM motivo = falha transitória do agente, não veredito.
                # Não toca no banco: o livro continua em status_categorize=0 e
                # volta na próxima exportação. Mesma leitura de
                # synopsis_import._process_file.
                log(f"[CATEGORIZE_IMPORT][{i:03d}] AVISO: agente rejeitou sem motivo "
                    f"— status mantido → {titulo}")
                rejeitados += 1
                continue
            log(f"[CATEGORIZE_IMPORT][{i:03d}] Rejeitado pelo agente ({motivo_str}) → {titulo}")
            _marcar_rejeitado(cur, conn, livro_id, _rejected_status, motivo_str)
            rejeitados += 1
            continue

        valido, razao = validate_categorias(categorias, taxonomy)

        if not valido:
            log(f"[CATEGORIZE_IMPORT][{i:03d}] Rejeitado na validação ({razao}) → {titulo}")
            _marcar_rejeitado(cur, conn, livro_id, _rejected_status, razao)
            rejeitados += 1
            continue

        try:
            save_categories(conn, livro_id, categorias)
            log(f"[CATEGORIZE_IMPORT][{i:03d}] OK → {titulo} ({autor or '?'}) → {categorias}")
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

    output_files = find_output_files(BATCH_DIR)

    if not output_files:
        log("[CATEGORIZE_IMPORT] Nenhum *_categorize_output.json encontrado.")
        log("[CATEGORIZE_IMPORT] Rode a opção 33 (Export) e o agente Claude Batch primeiro.")
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
