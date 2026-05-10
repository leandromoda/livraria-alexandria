"""
Wrapper para invocar o claude CLI local como backend LLM.
Usado pelo llm_orchestrator (opção O) — sem custo de API extra (plano Pro).
"""

import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
AGENTS_DIR = REPO_ROOT / "agents"

ALLOWED_TOOLS = "Bash,Read,Write,Glob,WebSearch,WebFetch"
DEFAULT_TIMEOUT = 600  # 10 min por agente


def claude_available() -> bool:
    return shutil.which("claude") is not None


def run_agent(prompt_path: str | Path, timeout: int = DEFAULT_TIMEOUT) -> tuple[bool, str]:
    """
    Carrega o prompt de `prompt_path` e invoca `claude --print` via subprocess.

    Retorna (sucesso: bool, saída: str).
    O processo roda na raiz do repo para que os paths relativos nos prompts funcionem.
    """
    path = Path(prompt_path)
    if not path.is_file():
        return False, f"Prompt não encontrado: {path}"

    prompt_text = path.read_text(encoding="utf-8")
    env = {**os.environ}

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


def agent_prompt_path(agent_name: str) -> Path:
    return AGENTS_DIR / agent_name / "prompt.md"
