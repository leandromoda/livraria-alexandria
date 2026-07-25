"""
Wrapper para invocar o claude CLI local como backend LLM.
Usado pelo llm_orchestrator (opção O) — sem custo de API extra (plano Pro).

Integra com claude_usage_tracker para:
  - Contabilizar chamadas por dia / total
  - Detectar erros de limite de sessão no output
  - Aguardar o reset de sessão, confirmar via probe, e repetir (até MAX_QUOTA_PROBES ciclos)

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

# ======================================================
# MODELO POR AGENTE
# ======================================================
#
# Sem --model, o CLI usa o modelo padrão da sessão (hoje Opus) para TUDO.
# Como o gargalo de publicação é a quota da janela de 5h (publicação ≡ sinopse
# ≡ quota — ver CLAUDE.md), rodar as tarefas fechadas no modelo mais caro reduz
# diretamente quantos livros saem por janela.
#
# Vão para o modelo rápido as tarefas de transformação FECHADA, onde o prompt já
# carrega todo o critério e o modelo não precisa de conhecimento externo:
#   - sinopse      → descricao ⇒ 90-160 palavras, proibido usar conhecimento externo
#   - categorização → escolher 3-5 slugs de uma taxonomia fixa, regras no prompt
#
# Ficam no modelo padrão (forte) as tarefas que dependem de conhecimento factual
# ou de julgamento aberto, onde um modelo menor alucina mais:
#   author_bio (fatos sobre pessoas reais), jogos_finder_batch (busca na web),
#   title_auditor / audit_batch / consistency_review / log_analysis_batch.
FAST_MODEL = os.getenv("CLAUDE_MODEL_FAST", "sonnet").strip()

AGENT_MODELS = {
    "synopsis_batch":          FAST_MODEL,
    "synopsis_jogos_batch":    FAST_MODEL,
    "synopsis_infantis_batch": FAST_MODEL,
    "classify_batch":          FAST_MODEL,
}


def model_for_agent(agent_name: str) -> str | None:
    """Modelo a usar para `agent_name`, ou None para o padrão da sessão.

    Override por agente via env: CLAUDE_MODEL_<AGENTE_EM_MAIÚSCULAS>.
    Valor vazio ou "default" força o padrão do CLI.
    """
    override = os.getenv(f"CLAUDE_MODEL_{agent_name.upper()}", "").strip()
    if override:
        return None if override.lower() == "default" else override

    return AGENT_MODELS.get(agent_name) or None

# Prompt mínimo usado para confirmar que a quota foi restaurada antes do retry real.
_PROBE_PROMPT = "Responda apenas com: ok"
_PROBE_TIMEOUT = 45    # segundos — suficiente para uma resposta trivial
_PROBE_INITIAL_WAIT = 10   # minutos antes da primeira probe (espera mínima)
_PROBE_INTERVAL    = 5    # minutos entre probes subsequentes
MAX_QUOTA_PROBES   = 72   # cobre até 6h de espera (10 + 71×5 min)

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


def _invoke(prompt_text: str, timeout: int, env: dict,
            model: str | None = None) -> tuple[bool, str]:
    """Executa claude --print uma única vez. Retorna (sucesso, output)."""
    claude_bin = _find_claude() or "claude"
    cmd = [claude_bin, "--print", "--allowedTools", ALLOWED_TOOLS]
    if model:
        cmd += ["--model", model]
    try:
        result = subprocess.run(
            cmd,
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


def _wait_and_probe(limit_output: str, env: dict, model: str | None = None) -> bool:
    """Aguarda o reset de quota e confirma via probe antes do retry real.

    Não depende do SESSION_RESET_MINUTES para definir quando começar a sondar —
    isso resolvia o dessincronismo onde a janela real (ex: 38 min) era muito
    menor que o timer estimado (5h a partir do hit).

    Estratégia:
      1. Dorme _PROBE_INITIAL_WAIT min (espera mínima obrigatória).
      2. Faz probe mínima para verificar restauração real.
      3. Se OK → retorna True.
      4. Se ainda limitado → dorme _PROBE_INTERVAL min e repete.
      5. Após MAX_QUOTA_PROBES probes sem sucesso → retorna False.
    """
    import time as _time

    # Tenta extrair espera explícita da mensagem de erro; senão usa o mínimo.
    parsed = _tracker._parse_wait_minutes(limit_output)
    initial_wait = max(_PROBE_INITIAL_WAIT, (parsed + 1) if parsed else _PROBE_INITIAL_WAIT)

    _log(
        f"[CLAUDE_RUNNER] Limite de quota detectado. "
        f"Primeira probe em {initial_wait} min — sondando a cada {_PROBE_INTERVAL} min."
    )
    _time.sleep(initial_wait * 60)

    for attempt in range(1, MAX_QUOTA_PROBES + 1):
        _log(f"[CLAUDE_RUNNER] Probe {attempt}/{MAX_QUOTA_PROBES}: verificando restauração de quota…")
        # Sonda com o MESMO modelo da chamada real: as quotas são por modelo, e
        # sondar com o padrão manteria a espera mesmo com o modelo rápido livre.
        probe_ok, probe_out = _invoke(_PROBE_PROMPT, _PROBE_TIMEOUT, env, model)
        probe_limit = _tracker.record_call(probe_ok, probe_out)

        if not probe_limit:
            _log("[CLAUDE_RUNNER] Probe OK — quota restaurada. Retomando chamada real.")
            return True

        if attempt < MAX_QUOTA_PROBES:
            _log(
                f"[CLAUDE_RUNNER] Probe {attempt}/{MAX_QUOTA_PROBES} ainda limitada. "
                f"Nova tentativa em {_PROBE_INTERVAL} min…"
            )
            _time.sleep(_PROBE_INTERVAL * 60)

    _log(
        f"[CLAUDE_RUNNER] Quota não restaurada após {MAX_QUOTA_PROBES} probes "
        f"({initial_wait + (MAX_QUOTA_PROBES - 1) * _PROBE_INTERVAL} min total). "
        f"Abortando retry."
    )
    return False


def run_agent(prompt_path: str | Path, timeout: int = DEFAULT_TIMEOUT,
              wait_on_limit: bool = True,
              model: str | None = None) -> tuple[bool, str]:
    """
    Carrega o prompt de `prompt_path` e invoca `claude --print` via subprocess.

    Retorna (sucesso: bool, saída: str).
    O processo roda na raiz do repo para que os paths relativos nos prompts funcionem.

    Controle de uso:
      - Registra cada chamada em claude_usage.json (calls_today, calls_total).
      - `wait_on_limit=True` (padrão): se o output indicar limite de sessão,
        aguarda o reset (bloqueante) e tenta uma 2ª vez.
      - `wait_on_limit=False`: NÃO bloqueia — retorna o limite imediatamente para
        que o chamador (orquestrador) decida o fallback (ex: rodar Autopilot A
        não-LLM e só então aguardar/retomar). O limite continua registrado no
        tracker (session_window reflete o cooldown).

    Modelo:
      - `model=None` (padrão): resolvido por `model_for_agent()` a partir do nome
        do diretório do agente (`agents/<nome>/prompt.md`). Todos os call sites
        passam por aqui, então a política de modelo fica num lugar só.
      - `model="..."`: força um modelo específico nesta chamada.
    """
    path = Path(prompt_path)
    if not path.is_file():
        return False, f"Prompt não encontrado: {path}"

    if model is None:
        model = model_for_agent(path.parent.name)

    prompt_text = path.read_text(encoding="utf-8")
    env = {**os.environ}

    if model:
        _log(f"[CLAUDE_RUNNER] {path.parent.name} → modelo: {model}")

    success, output = _invoke(prompt_text, timeout, env, model)
    limit_hit = _tracker.record_call(success, output)

    if limit_hit and wait_on_limit:
        if _wait_and_probe(output, env, model):
            success, output = _invoke(prompt_text, timeout, env, model)
            _tracker.record_call(success, output)
        else:
            # Probe falhou em todos os ciclos — mantém a saída de limite como resultado.
            success = False

    return success, output


def run_prompt(prompt_text: str, timeout: int = 120,
               wait_on_limit: bool = True,
               model: str | None = None) -> tuple[bool, str]:
    """Invoca claude --print com o prompt passado diretamente via stdin.

    Para chamadas LLM pontuais (não baseadas em arquivo de agente).
    Integra com claude_usage_tracker para detecção de limite de sessão.
    `wait_on_limit` segue a mesma semântica de run_agent.

    Retorna (sucesso: bool, saída: str).
    """
    env = {**os.environ}
    success, output = _invoke(prompt_text, timeout, env, model)
    limit_hit = _tracker.record_call(success, output)

    if limit_hit and wait_on_limit:
        if _wait_and_probe(output, env, model):
            success, output = _invoke(prompt_text, timeout, env, model)
            _tracker.record_call(success, output)
        else:
            success = False

    return success, output


def agent_prompt_path(agent_name: str) -> Path:
    return AGENTS_DIR / agent_name / "prompt.md"
