import os
import sys
import time
import tempfile
import threading
from datetime import datetime
from pathlib import Path

last_activity = time.time()

# ============================================================
# LOG FILE — <log_dir>/pipeline_YYYY-MM-DD_HH-MM-SS.log
#
# O arquivo é criado na PRIMEIRA escrita, não no import. Antes ele nascia junto
# com o módulo, então qualquer processo que só importasse `core.logger` já
# deixava um `pipeline_*.log` vazio na fila do /analise-logs — abrir o menu e
# sair, um tool que não loga nada, um teste. Medido em 2026-08-01: dos 72 logs
# da fila, **28 tinham 0 byte** (39%), todos dessa origem.
#
# `data/logs/` guarda TAMBÉM os relatórios `NNNN_audit_<mode>.json`, que têm
# escritor próprio (`core/audit_report.REPORT_DIR`) e não passam por aqui —
# redirecionar o log da sessão não move relatório de auditoria.
# ============================================================

_SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
_SESSION_TS = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

_lock = threading.Lock()
_log_file = None
_log_path = None


def _default_log_dir() -> Path:
    """Onde gravar o log desta sessão.

    `PIPELINE_LOG_DIR` tem precedência sobre tudo (escape hatch explícito).

    Sem ele, um script rodando a partir de `scripts/tests/` grava num diretório
    temporário: a suíte usa steps de verdade, que logam de verdade, e antes disso
    cada execução dos testes deixava `pipeline_*.log` indistinguíveis de execução
    real na fila do /analise-logs (medido em 2026-08-01: rodar `scripts/tests/`
    criou 4 arquivos, de 0 a 3.133 bytes). A detecção é pelo entry point e não
    por env var justamente para que um teste NOVO não precise lembrar de nada.
    """
    override = os.environ.get("PIPELINE_LOG_DIR")
    if override:
        return Path(override)

    try:
        entry = Path(sys.argv[0]).resolve()
        if entry.parent == _SCRIPTS_ROOT / "tests":
            return Path(tempfile.gettempdir()) / "livraria_alexandria_test_logs"
    except Exception:
        pass  # sys.argv[0] pode ser '' (-c, REPL) — cai no padrão

    return _SCRIPTS_ROOT / "data" / "logs"


def _ensure_file():
    """Abre o arquivo de log na primeira escrita. Devolve None se não der."""
    global _log_file, _log_path
    if _log_file is not None:
        return _log_file
    with _lock:
        if _log_file is None:                    # re-checa sob o lock
            d = _default_log_dir()
            d.mkdir(parents=True, exist_ok=True)
            _log_path = d / f"pipeline_{_SESSION_TS}.log"
            _log_file = _log_path.open("a", encoding="utf-8", buffering=1)
    return _log_file


def log_path():
    """Caminho do log desta sessão, ou None se nada foi escrito ainda."""
    return _log_path


def _write(line: str) -> None:
    try:
        f = _ensure_file()
        if f is not None:
            f.write(line + "\n")
    except Exception:
        pass  # nunca bloquear o pipeline por falha de I/O


def log(msg):

    global last_activity

    now  = datetime.now().strftime("%H:%M:%S")
    line = f"[{now}] {msg}"

    try:
        print(line)
    except UnicodeEncodeError:
        # Console cp1252 (padrão no Windows) não encoda "→", "—" nem emoji, e
        # os logs deste projeto usam os três. O `main.py` faz
        # sys.stdout.reconfigure(encoding="utf-8") na inicialização e mascara o
        # problema, mas qualquer step chamado fora dele — teste, tools/, `python
        # -c` — morria com UnicodeEncodeError NA LINHA DE LOG, não no trabalho.
        # Degrada só o console; o arquivo continua utf-8 e íntegro.
        print(line.encode("ascii", "replace").decode("ascii"))

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
