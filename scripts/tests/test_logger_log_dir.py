"""core/logger.py — criação preguiçosa e escolha do diretório de log.

Fixa duas garantias que a análise de logs de 2026-08-01 motivou:
  1. importar o logger NÃO cria arquivo (28 dos 72 logs da fila tinham 0 byte);
  2. rodar a partir de scripts/tests/ não polui a fila do /analise-logs.

Só stdlib. O módulo é recarregado em subprocesso a cada cenário porque o
caminho é resolvido uma vez por processo (estado de módulo).
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]


def _run(code, env_extra=None, argv0=None):
    """Roda `code` num processo novo com PYTHONPATH=scripts. Devolve stdout."""
    env = {**os.environ, "PYTHONPATH": str(SCRIPTS)}
    env.pop("PIPELINE_LOG_DIR", None)
    if env_extra:
        env.update(env_extra)

    if argv0 is None:
        cmd = [sys.executable, "-c", code]
    else:
        # Grava o script no caminho pedido para exercitar a deteccao por argv[0].
        Path(argv0).write_text(code, encoding="utf-8")
        cmd = [sys.executable, str(argv0)]

    r = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=str(SCRIPTS))
    assert r.returncode == 0, f"subprocesso falhou:\n{r.stdout}\n{r.stderr}"
    return r.stdout


# ── 1. Só importar não cria arquivo ─────────────────────────────────────────
with tempfile.TemporaryDirectory() as d:
    out = _run(
        "from core import logger\n"
        "print('PATH:', logger.log_path())\n",
        {"PIPELINE_LOG_DIR": d},
    )
    assert "PATH: None" in out, f"import criou arquivo: {out}"
    assert not list(Path(d).glob("*.log")), "import deixou .log no diretorio"

# ── 2. A primeira escrita cria o arquivo no diretorio do env ────────────────
with tempfile.TemporaryDirectory() as d:
    out = _run(
        "from core import logger\n"
        "logger.log('linha de teste')\n"
        "print('PATH:', logger.log_path())\n",
        {"PIPELINE_LOG_DIR": d},
    )
    logs = list(Path(d).glob("pipeline_*.log"))
    assert len(logs) == 1, f"esperava 1 log, veio {logs}"
    conteudo = logs[0].read_text(encoding="utf-8")
    assert "linha de teste" in conteudo, conteudo
    assert "PATH: None" not in out, "log_path() devia estar preenchido"

# ── 3. Script rodando de scripts/tests/ nao escreve em data/logs/ ───────────
# Usa um arquivo real dentro de scripts/tests/ para exercitar argv[0].
alvo = SCRIPTS / "tests" / "_tmp_probe_log_dir.py"
try:
    out = _run(
        "from core import logger\n"
        "logger.log('de dentro de tests/')\n"
        "print('DIR:', logger.log_path().parent)\n",
        argv0=str(alvo),
    )
    destino = Path(out.split("DIR:")[1].strip())
    assert destino != SCRIPTS / "data" / "logs", (
        f"teste escreveu na fila real do /analise-logs: {destino}"
    )
    assert destino == Path(tempfile.gettempdir()) / "livraria_alexandria_test_logs", destino
finally:
    alvo.unlink(missing_ok=True)

# ── 4. PIPELINE_LOG_DIR vence a deteccao de teste ───────────────────────────
alvo = SCRIPTS / "tests" / "_tmp_probe_override.py"
with tempfile.TemporaryDirectory() as d:
    try:
        out = _run(
            "from core import logger\n"
            "logger.log('x')\n"
            "print('DIR:', logger.log_path().parent)\n",
            {"PIPELINE_LOG_DIR": d},
            argv0=str(alvo),
        )
        assert Path(out.split("DIR:")[1].strip()) == Path(d), out
    finally:
        alvo.unlink(missing_ok=True)

# ── 5. Uso normal (fora de tests/) continua indo para data/logs/ ────────────
# Nao escreve nada: so confere a resolucao do diretorio, para nao sujar a fila.
out = _run(
    "from core import logger\n"
    "print('DIR:', logger._default_log_dir())\n",
)
assert Path(out.split("DIR:")[1].strip()) == SCRIPTS / "data" / "logs", out

print("test_logger_log_dir OK")
