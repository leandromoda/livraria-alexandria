"""
Wrapper para invocar o claude CLI local como backend LLM.
Usado pelo llm_orchestrator (opção O) — sem custo de API extra (plano Pro).

Integra com claude_usage_tracker para:
  - Contabilizar chamadas por dia / total
  - Detectar erros de limite de sessão no output
  - Aguardar o reset de sessão e repetir automaticamente (1 retry)

Configuração do executável (em ordem de prioridade):
  1. CLAUDE_BIN em scripts/.env  →  caminho explícito para o executável
  2. shutil.which("claude")      →  claude no PATH do sistema
  3. Glob em caminhos padrão de instalação do Claude Code Desktop (Windows)
"""

import os
import shutil
import subprocess
from pathlib import Path

from dotenv import load_dotenv

_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=_ENV_PATH, override=False)

from core import claude_usage_tracker as _tracker
from core.logger import log as _log

REPO_ROOT = Path(__file__).parent.parent.parent
AGENTS_DIR = REPO_ROOT / "agents"

ALLOWED_TOOLS = "Bash,Read,Write,Glob,WebSearch,WebFetch"
DEFAULT_TIMEOUT = 600  # 10 min por agente

# Globs de fallback para localizar o claude.exe quando não está no PATH.
# Testados com Python glob (Windows native API).
_APPDATA = os.environ.get("APPDATA", "")
_LOCALAPPDATA = os.environ.get("LOCALAPPDATA", "")

_CLAUDE_FALLBACK_GLOBS = [
    str(Path(_APPDATA)  / "Claude" / "claude-code"    / "*" / "claude.exe"),
    str(Path(_LOCALAPPDATA) / "AnthropicClaude"       / "claude.exe"),
    str(Path(_LOCALAPPDATA) / "Programs" / "AnthropicClaude" / "claude.exe"),
]


def _find_claude() -> str | None:
    """
    Retorna o caminho do executável claude, ou None se não encontrado.

    Ordem de busca:
      1. CLAUDE_BIN env var (configurável em scripts/.env)
      2. shutil.which("claude")  — PATH do sistema / npm global
      3. Glob em caminhos padrão do Claude Code Desktop (Windows)
      4. Verificação via 'where.exe' (cmd.exe) como último recurso
    """
    # 1. CLAUDE_BIN explícito no .env
    explicit = os.environ.get("CLAUDE_BIN", "").strip()
    if explicit and os.path.isfile(explicit):
        return explicit

    # 2. PATH do sistema (inclui npm global, venv, etc.)
    if path := shutil.which("claude"):
        return path

    # 3. Caminhos comuns do Claude Code Desktop (Windows)
    import glob as _glob
    for pattern in _CLAUDE_FALLBACK_GLOBS:
        matches = sorted(_glob.glob(pattern))
        if matches:
            return matches[-1]  # versão mais recente (ordenação lexicográfica)

    # 4. Última tentativa via where.exe (cmd.exe pode resolver caminhos que
    #    o Python nativo não vê por virtualização de AppData)
    try:
        r = subprocess.run(
            ["where.exe", "claude"],
            capture_output=True, timeout=5, encoding="utf-8", errors="replace",
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip().splitlines()[0]
    except Exception:
        pass

    return None


def claude_available() -> bool:
    return _find_claude() is not None


def _invoke(prompt_text: str, timeout: int, env: dict) -> tuple[bool, str]:
    """Executa claude --print uma única vez. Retorna (sucesso, output)."""
    claude_bin = _find_claude() or "claude"
    try:
        result = subprocess.run(
            [claude_bin, "--print", "--allowedTools", ALLOWED_TOOLS],
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
        # Aguarda reset de sessão e tenta novamente uma única vez.
        # Usa _log em vez de print para persistir a mensagem no pipeline.log.
        _tracker.wait_for_reset(output, log_fn=_log)
        success, output = _invoke(prompt_text, timeout, env)
        _tracker.record_call(success, output)

    return success, output


def agent_prompt_path(agent_name: str) -> Path:
    return AGENTS_DIR / agent_name / "prompt.md"
