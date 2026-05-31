# ============================================================
# WS3 — MEDIÇÃO DE BATCH_SIZE (timeout × throughput)
# Livraria Alexandria
#
# Para cada tarefa (synopsis/classify) e tamanho de lote, exporta um
# batch, mede o tempo de run_agent (claude CLI), importa e conta quantos
# itens foram concluídos com sucesso. Registra cada medição em JSONL.
#
# Uso (a partir de scripts/):
#   python tools/measure_batch.py
#   python tools/measure_batch.py synopsis:5,10,15 classify:10,20,25
#
# CONSOME a janela da sessão Claude PRO (cada batch = 1 chamada CLI).
# Resultados: data/batch_measure_results.jsonl
# ============================================================

import glob
import json
import os
import sys
import time
from datetime import datetime, timezone

# Console pode ser cp1252 (Windows) — forçar UTF-8 para os logs com '→' etc.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from core.claude_runner import agent_prompt_path, run_agent
from core.db import get_conn
from core.logger import log

DATA_DIR   = os.path.join(SCRIPTS_DIR, "data")
COWORK_DIR = os.path.join(DATA_DIR, "cowork")
RESULTS    = os.path.join(DATA_DIR, "batch_measure_results.jsonl")
AGENT_TIMEOUT = 1200

# task → (status_col, export_module, export_fn, import_module, agent, input_glob)
TASKS = {
    "synopsis": {
        "status_col": "status_synopsis",
        "agent":      "synopsis_cowork",
        "input_glob": "*_synopsis_input.json",
    },
    "classify": {
        "status_col": "status_categorize",
        "agent":      "classify_cowork",
        "input_glob": "*_categorize_input.json",
    },
}


def _clear_stuck(status_col):
    """Reverte qualquer status=3 preso para 0 antes de medir (batch limpo)."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"UPDATE livros SET {status_col} = 0 WHERE {status_col} = 3")
    conn.commit()
    n = cur.rowcount
    conn.close()
    return n


def _export(task, size, idioma):
    if task == "synopsis":
        from steps import synopsis_export
        return synopsis_export.run(idioma, size)
    else:
        from steps import categorize_export
        return categorize_export.run(size)


def _import(task):
    if task == "synopsis":
        from steps import synopsis_import
        synopsis_import.run()
    else:
        from steps import categorize_import
        categorize_import.run()


def _newest_input_ids(input_glob):
    files = glob.glob(os.path.join(COWORK_DIR, input_glob))
    if not files:
        return []
    newest = max(files, key=os.path.getmtime)
    with open(newest, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [l["id"] for l in data.get("livros", [])]


def _count_done(status_col, ids):
    if not ids:
        return 0
    conn = get_conn()
    cur = conn.cursor()
    placeholders = ",".join("?" * len(ids))
    cur.execute(
        f"SELECT COUNT(*) FROM livros WHERE {status_col} = 1 AND id IN ({placeholders})",
        ids,
    )
    n = cur.fetchone()[0]
    conn.close()
    return n


def measure(task, size, idioma="PT"):
    cfg = TASKS[task]
    status_col = cfg["status_col"]

    _clear_stuck(status_col)

    exported = _export(task, size, idioma)
    if not exported:
        log(f"[MEASURE] {task} size={size}: nada pendente — pulando")
        return None

    ids = _newest_input_ids(cfg["input_glob"])

    t0 = time.monotonic()
    success, output = run_agent(agent_prompt_path(cfg["agent"]), timeout=AGENT_TIMEOUT)
    wall = time.monotonic() - t0

    timed_out = (not success) and ("timeout" in output.lower() or wall >= AGENT_TIMEOUT - 5)

    done = 0
    if success:
        _import(task)
        done = _count_done(status_col, ids)

    result = {
        "ts":         datetime.now(timezone.utc).isoformat(),
        "task":       task,
        "size":       size,
        "exported":   exported,
        "agent_ok":   bool(success),
        "timed_out":  bool(timed_out),
        "wall_s":     round(wall, 1),
        "done":       done,
        "s_per_item": round(wall / exported, 1) if exported else None,
        "s_per_done": round(wall / done, 1) if done else None,
        "output_tail": output[-200:] if not success else "",
    }

    with open(RESULTS, "a", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")

    log(f"[MEASURE] {task} size={size} → wall={wall:.0f}s exported={exported} "
        f"done={done} ok={success} timeout={timed_out}")
    return result


def _parse_sweep(argv):
    if not argv:
        return [("synopsis", [5, 10, 15]), ("classify", [10, 20, 25])]
    sweep = []
    for token in argv:
        task, sizes = token.split(":")
        sweep.append((task, [int(s) for s in sizes.split(",")]))
    return sweep


def main():
    sweep = _parse_sweep(sys.argv[1:])
    log(f"[MEASURE] Iniciando sweep: {sweep}")
    log(f"[MEASURE] Resultados → {RESULTS}")
    for task, sizes in sweep:
        for size in sizes:
            try:
                measure(task, size)
            except Exception as e:
                log(f"[MEASURE] ERRO {task} size={size}: {e}")
    log("[MEASURE] Sweep concluído.")


if __name__ == "__main__":
    main()
