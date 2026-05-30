from pathlib import Path
from datetime import datetime
import json
import os
import re

import requests
from dotenv import load_dotenv
from core.gemini_limiter import acquire as _gemini_acquire

# ======================================================
# ENV
# ======================================================

_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=_ENV_PATH)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL   = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

# Ollama — local
OLLAMA_URL   = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral:7b")

# Provider ativo: "ollama" | "gemini" | "auto"
# "auto" = comportamento original (gemini → ollama fallback)
LLM_PROVIDER    = os.getenv("LLM_PROVIDER", "claude")
_active_provider = LLM_PROVIDER


def set_provider(provider: str) -> None:
    """Define o provider LLM ativo para toda a sessão."""
    global _active_provider
    _active_provider = provider
    print(f"[LLM] Provider ativo: {provider}")

# ======================================================
# PATHS
# ======================================================

BASE_DIR = Path(__file__).resolve().parents[2]
AGENTS_DIR = BASE_DIR / "agents"

# ======================================================
# HEARTBEAT
# ======================================================

def _heartbeat(stage: str):
    now = datetime.utcnow().isoformat()
    print(f"[heartbeat] {now} :: {stage}")

# ======================================================
# FILE HELPERS
# ======================================================

def _read_md_direct(path: Path, filename: str) -> str:
    file_path = path / filename
    if not file_path.exists():
        return ""
    return file_path.read_text(encoding="utf-8")

# ======================================================
# MODEL CALL — GEMINI (primary)
# ======================================================

def _call_gemini(prompt: str) -> str:

    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not set")

    # Controle de tier: throttle RPM + bloqueio RPD
    _gemini_acquire()

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 4096,
        },
    }

    response = requests.post(url, json=payload, timeout=60)

    if response.status_code == 429:
        raise RuntimeError("GEMINI_RATE_LIMIT_EXCEEDED")

    if response.status_code != 200:
        raise RuntimeError(
            f"GEMINI_API_ERROR {response.status_code}: {response.text[:300]}"
        )

    data = response.json()

    try:
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"GEMINI_RESPONSE_PARSE_ERROR: {e}")


# ======================================================
# MODEL CALL — OLLAMA (fallback local)
# ======================================================

def _call_ollama(prompt: str) -> str:

    url = f"{OLLAMA_URL}/api/generate"

    payload = {
        "model":  OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.2,
            "num_predict": 2048,
        },
    }

    try:
        response = requests.post(url, json=payload, timeout=120)
    except requests.exceptions.ConnectionError:
        raise RuntimeError(
            f"OLLAMA_UNAVAILABLE — servidor não encontrado em {OLLAMA_URL}. "
            "Verifique se o Ollama está rodando."
        )

    if response.status_code != 200:
        raise RuntimeError(
            f"OLLAMA_API_ERROR {response.status_code}: {response.text[:300]}"
        )

    data = response.json()

    try:
        return data["response"].strip()
    except KeyError as e:
        raise RuntimeError(f"OLLAMA_RESPONSE_PARSE_ERROR: {e}")


# ======================================================
# MODEL CALL — CLAUDE CLI
# ======================================================

def _call_claude(prompt: str) -> str:
    """Roteia chamada LLM para o claude CLI (--print mode via stdin).

    Requer o Claude Code CLI instalado (claude_runner._find_claude()).
    Levanta RuntimeError("CLAUDE_SESSION_LIMIT_REACHED") se limite atingido.
    """
    from core.claude_runner import run_prompt, claude_available
    from core import claude_usage_tracker as _claude_tracker

    if not claude_available():
        raise RuntimeError(
            "CLAUDE_CLI_NOT_FOUND — instale o Claude Code CLI e tente novamente."
        )

    success, output = run_prompt(prompt, timeout=120)

    if _claude_tracker.is_limit_error(output):
        raise RuntimeError("CLAUDE_SESSION_LIMIT_REACHED")

    if not success:
        raise RuntimeError(f"CLAUDE_CLI_ERROR: {output[:300]}")

    return output


# ======================================================
# MODEL CALL — ROUTER
# ======================================================

def _call_llm(prompt: str) -> str:
    """
    Roteia chamada LLM conforme _active_provider:
      "claude" -> Claude via CLI (padrão)
      "gemini" -> Gemini cloud
      "ollama" -> Ollama local
      "auto"   -> Gemini -> Ollama fallback (comportamento legado)
    """

    provider = _active_provider

    if provider == "claude":
        result = _call_claude(prompt)
        print("[LLM] Provider: claude")
        return result

    if provider == "gemini":
        result = _call_gemini(prompt)
        print("[LLM] Provider: gemini")
        return result

    if provider == "ollama":
        result = _call_ollama(prompt)
        print(f"[LLM] Provider: ollama ({OLLAMA_MODEL})")
        return result

    # "auto" -- gemini -> ollama fallback
    if GEMINI_API_KEY:
        try:
            result = _call_gemini(prompt)
            print("[LLM] Provider: gemini")
            return result

        except RuntimeError as e:
            reason = str(e)
            print(f"[LLM] Gemini falhou ({reason[:80]}) -- tentando Ollama...")

    result = _call_ollama(prompt)
    print(f"[LLM] Provider: ollama ({OLLAMA_MODEL})")
    return result

# ======================================================
# ROBUST JSON EXTRACTOR
# ======================================================

def _extract_json(text: str):

    text = text.replace("```json", "")
    text = text.replace("```", "")

    candidates = []

    brace_stack = 0
    start_index = None

    for i, char in enumerate(text):
        if char == "{":
            if brace_stack == 0:
                start_index = i
            brace_stack += 1

        elif char == "}":
            brace_stack -= 1
            if brace_stack == 0 and start_index is not None:
                candidates.append(text[start_index:i+1])
                start_index = None

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except Exception:
            continue

    raise RuntimeError("INVALID_AGENT_OUTPUT")

# ======================================================
# PROMPT BUILDER
# ======================================================

def _build_prompt(identity, rules, task, input_data, stage):

    memory_section = ""
    if "agent_memory" in input_data:
        memory_section = f"\n[AGENT_MEMORY]\n{input_data['agent_memory']}\n"

    clean_input = {k: v for k, v in input_data.items() if k != "agent_memory"}

    return f"""
EXECUTION_STAGE: {stage}
STRICT_JSON_OUTPUT: TRUE
NO_META_TEXT: TRUE

[SYSTEM]
{identity}

{rules}
{memory_section}
[TASK]
{task}

<INPUT_DATA_BEGIN>
{json.dumps(clean_input, ensure_ascii=False)}
</INPUT_DATA_END>
"""

# ======================================================
# SINGLE AGENT EXECUTION
# ======================================================

def _execute_single_agent(agent_path: Path, context: dict):

    identity = _read_md_direct(agent_path, "identity.md")
    rules = _read_md_direct(agent_path, "rules.md")
    task = _read_md_direct(agent_path, "task.md")

    stage_name = agent_path.name

    prompt = _build_prompt(identity, rules, task, context, stage_name)

    _heartbeat(f"{stage_name}_generation_started")

    raw_output = _call_llm(prompt)

    _heartbeat(f"{stage_name}_generation_finished")

    print(f"[{stage_name.upper()}][RAW_OUTPUT_BEGIN]")
    print(raw_output)
    print(f"[{stage_name.upper()}][RAW_OUTPUT_END]")

    data = _extract_json(raw_output)

    return data

# ======================================================
# MAIN EXECUTOR — MODE 1 (single agent)
# ======================================================

def execute_agent(agent_name: str, context: dict):
    """Executa um agente de estágio único (agents/<name>/task.md).

    Usado por author_bio e offer_finder. O motor FSM de sinopse (MODE 2,
    pipeline de 4 estágios) foi aposentado — a geração de sinopse agora usa
    exclusivamente o agente batch `synopsis_cowork` via claude_runner.run_agent.
    """

    print(f"[agent] executing '{agent_name}'")

    _heartbeat("markdown_loaded")

    agent_path = BASE_DIR / agent_name

    if not (agent_path / "task.md").exists():
        raise RuntimeError(
            f"AGENT_NOT_SINGLE_STAGE: '{agent_name}' não tem task.md. "
            "O pipeline FSM multi-estágio foi removido; use o motor batch."
        )

    _heartbeat("payload_ready")

    result = _execute_single_agent(agent_path, context)

    _heartbeat("finalized")

    return result