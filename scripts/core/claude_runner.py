"""
Wrapper para invocar o claude CLI local como backend LLM.
Usado pelo llm_orchestrator (opção O) — sem custo de API extra (plano Pro).

Integra com claude_usage_tracker para:
  - Contabilizar chamadas por dia / total
  - Detectar erros de limite de sessão no output
  - Aguardar o reset de sessão e repetir automaticamente (1 retry)
"""

import os
import shutil
import subprocess
from pathlib import Path

from core import claude_usage_tracker as _tracker

REPO_ROOT = Path(__file__).parent.parent.parent
AGENTS_DIR = REPO_ROOT / "agents"

ALLOWED_TOOLS = "Bash,Read,Write,Glob,WebSearch,WebFetch"
DEFAULT_TIMEOUT = 600  # 10 min por agente


def claude_available() -> bool:
    return shutil.which("claude") is not None


def _invoke(prompt_text: str, timeout: int, env: dict) -> tuple[bool, str]:
    """Executa claude --print uma única vez. Retorna (sucesso, output)."""
    try:
        result = subprocess.run(
            ["claude", "--print", "--allowedTools", ALLOWED_TOOLS],
            input=prompt_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            cwd=str(REPO_ROOT),
            env=env,
        )
        success = result.returncode == 0
        output = result.stdout.strip()
        if result.stderr.strip():
            output += "\n[stderr] " + result.stderr.strip()
        return success, output

    except subprocess.TimeoutExpired:
        return False, f"Timeout após {timeout}s"
    except FileNotFoundError:
        return False, "claude CLI não encontrado no PATH"
    except Exception as exc:
        return False, str(exc)


def run_agent(prompt_path: str | Path, timeout: int = DEFAULT_TIMEOUT) -> tuple[bool, str]:
    """
    Carrega o prompt de `prompt_path` e invoca `claude --print` via subprocess.

    Retorna (sucesso: bool, saída: str).
    O processo roda na raiz do repo para que os paths relativos nos prompts funcionem.

    Controle de uso:
      - Registra cada chamada em claude_usage.json (calls_today, calls_total).
      - Se o output indicar limite de sessão, aguarda o reset automático e tenta
        uma segunda vez. Se o retry também falhar com limite, retorna falha.
    """
    path = Path(prompt_path)
    if not path.is_file():
        return False, f"Prompt não encontrado: {path}"

    prompt_text = path.read_text(encoding="utf-8")
    env = {**os.environ}

    success, output = _invoke(prompt_text, timeout, env)
    limit_hit = _tracker.record_call(success, output)

    if limit_hit:
        # Aguarda reset de sessão e tenta novamente uma única vez
        _tracker.wait_for_reset(output, log_fn=print)
        success, output = _invoke(prompt_text, timeout, env)
        _tracker.record_call(success, output)

    return success, output


def agent_prompt_path(agent_name: str) -> Path:
    return AGENTS_DIR / agent_name / "prompt.md"
