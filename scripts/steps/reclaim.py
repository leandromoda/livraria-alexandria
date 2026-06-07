# ============================================================
# RECLAIM — Recuperação de estados presos
# Livraria Alexandria
#
# Execuções interrompidas (timeout, Ctrl+C, reset de sessão) deixam
# livros em status_*=3 (exportado-não-importado) e arquivos
# *_input.json órfãos em data/cowork/. Esses livros ficam INVISÍVEIS
# aos drains do orquestrador (que selecionam status=0), virando
# backlog oculto.
#
# Esta rotina, chamada no início de cada ação de autopilot (O/A/G),
# é idempotente:
#   1. Importa outputs já prontos (recupera trabalho concluído antes do reset).
#   2. Reseta para 0 os livros ainda em status_*=3 (sem output) — devolve à fila.
#   3. Arquiva inputs órfãos para processed_*/ (mantém a numeração monotônica
#      — next_batch_number varre processed_*/).
# ============================================================

import glob
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from core.db import get_conn
from core.logger import log

SCRIPTS_DIR = Path(__file__).parent.parent
COWORK_DIR  = SCRIPTS_DIR / "data" / "cowork"

# (kind, coluna de status com sentinel 3, pasta de arquivamento)
_RECOVERABLE = [
    ("synopsis",   "status_synopsis",   "processed_synopsis"),
    ("categorize", "status_categorize", "processed_categorize"),
]
# author_bio não usa sentinel 3 (seleciona por descricao IS NULL), mas
# deixa inputs órfãos — só precisam ser arquivados.
_INPUT_KINDS = [
    ("synopsis",   "processed_synopsis"),
    ("categorize", "processed_categorize"),
    ("author_bio", "processed_author_bio"),
]


def _has_pending() -> bool:
    """True se há qualquer artefato/estado preso a tratar."""
    for kind, _ in _INPUT_KINDS:
        if glob.glob(str(COWORK_DIR / f"*_{kind}_input.json")):
            return True
    for kind, _, _ in _RECOVERABLE:
        if glob.glob(str(COWORK_DIR / f"*_{kind}_output.json")):
            return True
    conn = get_conn()
    try:
        cond = " OR ".join(f"{col} = 3" for _, col, _ in _RECOVERABLE)
        return conn.execute(f"SELECT COUNT(*) FROM livros WHERE {cond}").fetchone()[0] > 0
    finally:
        conn.close()


def _import_pending_outputs() -> int:
    """Importa outputs prontos antes de qualquer reset (não perde trabalho feito)."""
    recovered = 0
    if glob.glob(str(COWORK_DIR / "*_synopsis_output.json")):
        from steps.synopsis_import import run as synopsis_import_run
        synopsis_import_run()
        recovered += 1
    if glob.glob(str(COWORK_DIR / "*_categorize_output.json")):
        from steps.categorize_import import run as categorize_import_run
        categorize_import_run()
        recovered += 1
    return recovered


def _reset_stuck(conn) -> dict:
    """Reseta status_*=3 → 0 (livros exportados cujo output nunca chegou)."""
    counts = {}
    cur = conn.cursor()
    for _, col, _ in _RECOVERABLE:
        n = cur.execute(f"SELECT COUNT(*) FROM livros WHERE {col} = 3").fetchone()[0]
        if n:
            cur.execute(
                f"UPDATE livros SET {col} = 0, updated_at = CURRENT_TIMESTAMP WHERE {col} = 3"
            )
        counts[col] = n
    conn.commit()
    return counts


def _archive_orphan_inputs() -> int:
    """Move *_input.json órfãos para processed_*/reclaimed/ (nunca processados pelo agente).

    Usa subdiretório `reclaimed/` em vez de `processed_*/` diretamente para
    distinguir lotes abandonados de lotes em voo (agent move input para
    processed_*/ ENQUANTO processa; reclaim move para processed_*/reclaimed/
    APÓS desistir). O guard de fila (cowork_guard.py) só verifica filhos
    diretos de processed_*/, então reclaimed/ não gera falso positivo de
    "lote em voo". cowork_numbering.py inclui reclaimed/ no scan de números
    para evitar reutilização de NNNs.
    """
    moved = 0
    for kind, processed in _INPUT_KINDS:
        orphans = glob.glob(str(COWORK_DIR / f"*_{kind}_input.json"))
        if not orphans:
            continue
        dest_dir = COWORK_DIR / processed / "reclaimed"
        os.makedirs(dest_dir, exist_ok=True)
        for path in orphans:
            dest = dest_dir / os.path.basename(path)
            if dest.exists():
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                dest = dest_dir / f"{dest.stem}__{stamp}{dest.suffix}"
            shutil.move(path, str(dest))
            moved += 1
    return moved


def run() -> dict:
    """Reclama estados presos de execuções interrompidas. Idempotente.

    Silencioso (sem log) quando não há nada preso.
    """
    empty = {"recovered_imports": 0, "reset": {}, "archived_inputs": 0}
    if not COWORK_DIR.exists() or not _has_pending():
        return empty

    log("[RECLAIM] Estados presos detectados — recuperando…")
    recovered = _import_pending_outputs()

    conn = get_conn()
    try:
        reset_counts = _reset_stuck(conn)
    finally:
        conn.close()

    archived = _archive_orphan_inputs()
    total_reset = sum(reset_counts.values())

    log(
        f"[RECLAIM] outputs importados: {recovered} | "
        f"resetados→0: {total_reset} "
        f"(sinopse {reset_counts.get('status_synopsis', 0)}, "
        f"categoria {reset_counts.get('status_categorize', 0)}) | "
        f"inputs órfãos arquivados: {archived}"
    )
    return {
        "recovered_imports": recovered,
        "reset": reset_counts,
        "archived_inputs": archived,
    }
