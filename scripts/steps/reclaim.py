# ============================================================
# RECLAIM — Recuperação de estados presos
# Livraria Alexandria
#
# Execuções interrompidas (timeout, Ctrl+C, reset de sessão) deixam
# livros em status_*=3 (exportado-não-importado) e arquivos
# *_input.json órfãos em data/batch/. Esses livros ficam INVISÍVEIS
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
BATCH_DIR  = SCRIPTS_DIR / "data" / "batch"

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
    for kind, processed in _INPUT_KINDS:
        if glob.glob(str(BATCH_DIR / f"*_{kind}_input.json")):
            return True
        # Inputs em processed_*/ sem output correspondente são stale:
        # bloqueiam is_queue_busy() mesmo após reclaim resetar o banco.
        proc_dir = BATCH_DIR / processed
        if proc_dir.exists():
            for inp in proc_dir.glob(f"*_{kind}_input.json"):
                nnn = inp.name.split("_")[0]
                has_out = (
                    (proc_dir / f"{nnn}_{kind}_output.json").exists()
                    or (BATCH_DIR / f"{nnn}_{kind}_output.json").exists()
                )
                if not has_out:
                    return True
    for kind, _, _ in _RECOVERABLE:
        if glob.glob(str(BATCH_DIR / f"*_{kind}_output.json")):
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
    if glob.glob(str(BATCH_DIR / "*_synopsis_output.json")):
        from steps.synopsis_import import run as synopsis_import_run
        synopsis_import_run()
        recovered += 1
    if glob.glob(str(BATCH_DIR / "*_categorize_output.json")):
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


def _archive_stale_processed_inputs() -> int:
    """Arquiva inputs em processed_*/ sem output correspondente → processed_*/reclaimed/.

    Cenário: agente interrompido APÓS mover input para processed_*/ mas ANTES
    de gerar output. reclaim reseta status=3→0 no banco mas não move o input
    de processed_*/. Em seguida, is_queue_busy() vê esse input como "em voo"
    e bloqueia toda exportação indefinidamente.

    Segurança: só arquiva inputs SEM output matching (em processed_*/ ou na
    raiz de batch/). Inputs com output correspondente não são tocados — o
    agente concluiu e o import ainda não rodou.
    """
    moved = 0
    for kind, processed in _INPUT_KINDS:
        proc_dir = BATCH_DIR / processed
        if not proc_dir.exists():
            continue
        # Filhos diretos de processed_*/ (glob pathlib não é recursivo aqui)
        inputs = list(proc_dir.glob(f"*_{kind}_input.json"))
        if not inputs:
            continue
        # NNNs com output correspondente — não tocar
        done_nums: set[str] = set()
        for p in proc_dir.glob(f"*_{kind}_output.json"):
            done_nums.add(p.name.split("_")[0])
        for p in BATCH_DIR.glob(f"*_{kind}_output.json"):
            done_nums.add(p.name.split("_")[0])
        reclaimed_dir = proc_dir / "reclaimed"
        for inp_path in inputs:
            nnn = inp_path.name.split("_")[0]
            if nnn in done_nums:
                continue  # tem output — agente concluiu, não arquivar
            os.makedirs(reclaimed_dir, exist_ok=True)
            dest = reclaimed_dir / inp_path.name
            if dest.exists():
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                dest = reclaimed_dir / f"{inp_path.stem}__{stamp}{inp_path.suffix}"
            shutil.move(str(inp_path), str(dest))
            moved += 1
    return moved


def _archive_orphan_inputs() -> int:
    """Move *_input.json órfãos para processed_*/reclaimed/ (nunca processados pelo agente).

    Usa subdiretório `reclaimed/` em vez de `processed_*/` diretamente para
    distinguir lotes abandonados de lotes em voo (agent move input para
    processed_*/ ENQUANTO processa; reclaim move para processed_*/reclaimed/
    APÓS desistir). O guard de fila (batch_guard.py) só verifica filhos
    diretos de processed_*/, então reclaimed/ não gera falso positivo de
    "lote em voo". batch_numbering.py inclui reclaimed/ no scan de números
    para evitar reutilização de NNNs.
    """
    moved = 0
    for kind, processed in _INPUT_KINDS:
        orphans = glob.glob(str(BATCH_DIR / f"*_{kind}_input.json"))
        if not orphans:
            continue
        dest_dir = BATCH_DIR / processed / "reclaimed"
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
    if not BATCH_DIR.exists() or not _has_pending():
        return empty

    log("[RECLAIM] Estados presos detectados — recuperando…")
    recovered = _import_pending_outputs()

    conn = get_conn()
    try:
        reset_counts = _reset_stuck(conn)
    finally:
        conn.close()

    archived_root = _archive_orphan_inputs()
    archived_stale = _archive_stale_processed_inputs()
    archived = archived_root + archived_stale
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
