import time
import threading
from datetime import datetime
from pathlib import Path

last_activity = time.time()

# ============================================================
# LOG FILE — scripts/data/logs/pipeline_YYYY-MM-DD_HH-MM-SS.log
# Criado uma vez por sessão ao importar este módulo.
# ============================================================

_LOG_DIR = Path(__file__).resolve().parents[1] / "data" / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

_SESSION_TS  = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
_LOG_PATH    = _LOG_DIR / f"pipeline_{_SESSION_TS}.log"
_log_file    = _LOG_PATH.open("a", encoding="utf-8", buffering=1)  # line-buffered


def _write(line: str) -> None:
    try:
        _log_file.write(line + "\n")
    except Exception:
        pass  # nunca bloquear o pipeline por falha de I/O


def log(msg):

    global last_activity

    now  = datetime.now().strftime("%H:%M:%S")
    line = f"[{now}] {msg}"

    print(line)
    _write(line)

    last_activity = time.time()


def start_heartbeat():

    def beat():

        while True:

            elapsed = int(time.time() - last_activity)
            now     = datetime.now().strftime("%H:%M:%S")
            line    = f"[{now}] Script ativo… último evento há {elapsed}s"

            print(line)
            _write(line)

            time.sleep(30)

    threading.Thread(target=beat, daemon=True).start()
