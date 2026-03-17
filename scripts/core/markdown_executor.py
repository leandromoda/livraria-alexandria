from pathlib import Path
from datetime import datetime
import json
import os
import re
import uuid

import requests
from dotenv import load_dotenv
from core.markdown_memory import load_memory
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
LLM_PROVIDER    = os.getenv("LLM_PROVIDER", "ollama")
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
RUNTIME_DIR = BASE_DIR / "runtime" / "tmp"

RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

# ======================================================
# PIPELINE CONFIG (DETERMINÍSTICO)
# ======================================================

DOMAIN = "synopsis"

PIPELINE_STAGES = [
    "fact_extractor",
    "abstract_structurer",
    "synopsis_writer",
    "synopsis_validator",
]

# ======================================================
# HEARTBEAT
# ======================================================

def _heartbeat(stage: str):
    now = datetime.utcnow().isoformat()
    print(f"[heartbeat] {now} :: {stage}")

# ======================================================
# FILE HELPERS
# ======================================================

def _read_md(domain: str, stage: str, filename: str) -> str:
    path = AGENTS_DIR / domain / stage / filename
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")

def _read_md_direct(path: Path, filename: str) -> str:
    file_path = path / filename
    if not file_path.exists():
        return ""
    return file_path.read_text(encoding="utf-8")

def _tmp_path():
    return RUNTIME_DIR / f"tmp_synopsis_{uuid.uuid4().hex}.json"

def _tmp_write(path: Path, data: dict):
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

def _tmp_read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))

def _tmp_delete(path: Path):
    if path.exists():
        path.unlink()

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
# MODEL CALL — ROUTER (Gemini → Ollama fallback)
# ======================================================

def _call_llm(prompt: str) -> str:
    """
    Roteia chamada LLM conforme _active_provider:
      "ollama" -> Ollama local (padrao)
      "gemini" -> Gemini cloud
      "auto"   -> Gemini -> Ollama fallback (comportamento legado)
    """

    provider = _active_provider

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
# FACT EXTRACTOR SCHEMA VALIDATION
# ======================================================

def _validate_fact_schema(data: dict):

    required_keys = {
        "tema_central",
        "abordagem",
        "conceitos_chave",
        "publico_alvo",
        "proposta_valor",
    }

    if set(data.keys()) != required_keys:
        raise RuntimeError("INVALID_FACT_SCHEMA_KEYS")

    if not isinstance(data["tema_central"], str):
        raise RuntimeError("INVALID_FACT_SCHEMA_TYPE")

    if not isinstance(data["abordagem"], str):
        raise RuntimeError("INVALID_FACT_SCHEMA_TYPE")

    if not isinstance(data["conceitos_chave"], list):
        raise RuntimeError("INVALID_FACT_SCHEMA_TYPE")

    if not isinstance(data["publico_alvo"], str):
        raise RuntimeError("INVALID_FACT_SCHEMA_TYPE")

    if not isinstance(data["proposta_valor"], str):
        raise RuntimeError("INVALID_FACT_SCHEMA_TYPE")

# ======================================================
# ABSTRACT STRUCTURER — PYTHON PURO (SEM LLM)
# ======================================================

def _run_abstract_structurer(state: dict) -> dict:
    """
    Remap determinístico: fact_extractor → abstract_structurer.
    Substitui chamada LLM por transformação Python pura.
    """

    _heartbeat("abstract_structurer_started")

    conceitos = state.get("conceitos_chave", [])

    result = {
        "contexto":         state.get("tema_central", ""),
        "situacao_central": state.get("abordagem", ""),
        "temas":            conceitos,
        "escopo_narrativo": state.get("publico_alvo", ""),
        "proposta_valor":   state.get("proposta_valor", ""),
    }

    _heartbeat("abstract_structurer_finished")

    print("[ABSTRACT_STRUCTURER][PYTHON_REMAP]")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    return result

# ======================================================
# SYNOPSIS VALIDATOR — PYTHON PURO (SEM LLM)
# ======================================================

_META_ARTIFACTS = [
    "[SYSTEM]",
    "[PROCESS]",
    "[TASK]",
    "INPUT_DATA_BEGIN",
    "INPUT_DATA_END",
    "EXECUTION_STAGE",
]

_LANGUAGE_MARKERS = {
    "PT": ["o ", "a ", "os ", "as ", "de ", "que ", "em ", "um ", "uma ", "com ", "para "],
    "EN": ["the ", "and ", "of ", "to ", "in ", "a ", "is ", "that ", "it ", "for "],
    "ES": ["el ", "la ", "los ", "las ", "de ", "que ", "en ", "un ", "una ", "con ", "para "],
    "IT": ["il ", "la ", "i ", "le ", "di ", "che ", "in ", "un ", "una ", "con ", "per "],
}

def _detect_language(text: str, expected_idioma: str) -> bool:
    """
    Heurística leve: verifica se o texto contém marcadores do idioma esperado.
    Retorna True se compatível.
    """

    text_lower = text.lower()
    markers = _LANGUAGE_MARKERS.get(expected_idioma.upper(), [])

    if not markers:
        return True

    hits = sum(1 for m in markers if m in text_lower)

    return hits >= 3

def _run_synopsis_validator(state: dict) -> dict:
    """
    Validação determinística: substitui chamada LLM por regras Python puras.
    Aplica as mesmas regras do synopsis_validator original.
    """

    _heartbeat("synopsis_validator_started")

    synopsis = state.get("synopsis", "")
    idioma = state.get("idioma_resolved", "PT").upper()

    # R1 — Synopsis não pode ser vazia
    if not synopsis or not synopsis.strip():
        _heartbeat("synopsis_validator_finished")
        return {"status": "REWRITE_REQUIRED"}

    # R2 — Detecção de meta artifacts
    synopsis_upper = synopsis.upper()
    for artifact in _META_ARTIFACTS:
        if artifact.upper() in synopsis_upper:
            print(f"[VALIDATOR] Meta artifact detectado: {artifact}")
            _heartbeat("synopsis_validator_finished")
            return {"status": "REWRITE_REQUIRED"}

    # R3 — Markdown headings
    if re.search(r"^#{1,6}\s", synopsis, re.MULTILINE):
        print("[VALIDATOR] Markdown heading detectado")
        _heartbeat("synopsis_validator_finished")
        return {"status": "REWRITE_REQUIRED"}

    # R4 — Contagem de palavras (90–160)
    word_count = len(synopsis.split())
    if word_count < 80 or word_count > 160:
        print(f"[VALIDATOR] Word count fora do range: {word_count}")
        _heartbeat("synopsis_validator_finished")
        return {"status": "REWRITE_REQUIRED"}

    # R5 — Integridade estrutural: deve terminar com pontuação
    stripped = synopsis.strip()
    if stripped and stripped[-1] not in ".!?":
        print("[VALIDATOR] Sinopse não termina com pontuação")
        _heartbeat("synopsis_validator_finished")
        return {"status": "REWRITE_REQUIRED"}

    # R6 — Verificação de idioma
    if not _detect_language(synopsis, idioma):
        print(f"[VALIDATOR] Idioma divergente. Esperado: {idioma}")
        _heartbeat("synopsis_validator_finished")
        return {"status": "REWRITE_REQUIRED"}

    # R7 — Tom promocional
    promotional_patterns = [
        r"\bimperdível\b",
        r"\bmust.read\b",
        r"\bcompre\b",
        r"\badquira\b",
        r"\bclique\b",
        r"\bgaranta\b",
        r"\bincrível\b",
        r"\bfantástico\b",
    ]
    for pattern in promotional_patterns:
        if re.search(pattern, synopsis, re.IGNORECASE):
            print(f"[VALIDATOR] Tom promocional detectado: {pattern}")
            _heartbeat("synopsis_validator_finished")
            return {"status": "REWRITE_REQUIRED"}

    _heartbeat("synopsis_validator_finished")

    print(f"[VALIDATOR] APPROVED — {word_count} palavras")

    return {"status": "APPROVED"}

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

    # ===============================================
    # FACT SCHEMA VALIDATION
    # ===============================================

    if stage_name == "fact_extractor":
        _validate_fact_schema(data)

    return data

# ======================================================
# PIPELINE STAGE EXECUTION
# ======================================================

def _execute_stage(stage: str, state: dict):

    # -----------------------------------------------
    # ESTÁGIOS PYTHON PURO — SEM CHAMADA LLM
    # -----------------------------------------------

    if stage == "abstract_structurer":
        return _run_abstract_structurer(state)

    if stage == "synopsis_validator":
        return _run_synopsis_validator(state)

    # -----------------------------------------------
    # ESTÁGIOS LLM
    # -----------------------------------------------

    identity = _read_md(DOMAIN, stage, "identity.md")
    rules = _read_md(DOMAIN, stage, "rules.md")
    task = _read_md(DOMAIN, stage, "task.md")

    prompt = _build_prompt(identity, rules, task, state, stage)

    _heartbeat(f"{stage}_generation_started")

    raw_output = _call_llm(prompt)

    _heartbeat(f"{stage}_generation_finished")

    print(f"[{stage.upper()}][RAW_OUTPUT_BEGIN]")
    print(raw_output)
    print(f"[{stage.upper()}][RAW_OUTPUT_END]")

    data = _extract_json(raw_output)

    return data

# ======================================================
# MAIN EXECUTOR
# ======================================================

def execute_agent(agent_name: str, context: dict):

    print(f"[agent] executing '{agent_name}'")

    _heartbeat("markdown_loaded")

    agent_path = BASE_DIR / agent_name

    # ==================================================
    # MODE 1 — SINGLE AGENT
    # ==================================================

    if (agent_path / "task.md").exists():

        _heartbeat("payload_ready")

        result = _execute_single_agent(agent_path, context)

        _heartbeat("finalized")

        return result

    # ==================================================
    # MODE 2 — PIPELINE EXECUTION
    # ==================================================

    tmp_file = _tmp_path()

    state = {
        "titulo": context.get("titulo"),
        "autor": context.get("autor"),
        "idioma_resolved": context.get("idioma", "PT"),
        "descricao_base": context.get("descricao_base", ""),
        "reference_synopses": [],
        "reader_signals": [],
        "abstract": "",
        "synopsis": "",
    }

    agent_memory = load_memory("synopsis")
    if agent_memory:
        state["agent_memory"] = agent_memory
        print(f"[MEMORY] Memória do agente synopsis carregada ({len(agent_memory)} chars)")

    _tmp_write(tmp_file, state)

    _heartbeat("payload_ready")

    for stage in PIPELINE_STAGES:

        state = _tmp_read(tmp_file)

        result = _execute_stage(stage, state)

        state.update(result)

        _tmp_write(tmp_file, state)

        if stage == "synopsis_validator":

            if result.get("status") != "APPROVED":
                # Log and return empty synopsis — caller decides what to do
                print(f"[VALIDATOR] REJECTED — returning empty synopsis")
                return {"synopsis": ""}

    _heartbeat("finalized")

    final_state = _tmp_read(tmp_file)

    _tmp_delete(tmp_file)

    return {
        "synopsis": final_state.get("synopsis", "")
    }