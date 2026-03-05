from pathlib import Path
from datetime import datetime
import json
import subprocess
import uuid

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
# MODEL CALL
# ======================================================

def _call_ollama(prompt: str):

    result = subprocess.run(
        ["ollama", "run", "phi3:mini"],
        input=prompt.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    return result.stdout.decode("utf-8", errors="ignore").strip()

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
        "ambientacao",
        "contexto_social",
        "conflito_central",
        "personagens_mencionados",
        "temas_explicitos",
    }

    if set(data.keys()) != required_keys:
        raise RuntimeError("INVALID_FACT_SCHEMA_KEYS")

    if not isinstance(data["ambientacao"], str):
        raise RuntimeError("INVALID_FACT_SCHEMA_TYPE")

    if not isinstance(data["contexto_social"], str):
        raise RuntimeError("INVALID_FACT_SCHEMA_TYPE")

    if not isinstance(data["conflito_central"], str):
        raise RuntimeError("INVALID_FACT_SCHEMA_TYPE")

    if not isinstance(data["personagens_mencionados"], list):
        raise RuntimeError("INVALID_FACT_SCHEMA_TYPE")

    if not isinstance(data["temas_explicitos"], list):
        raise RuntimeError("INVALID_FACT_SCHEMA_TYPE")

# ======================================================
# PROMPT BUILDER
# ======================================================

def _build_prompt(identity, rules, task, input_data, stage):

    return f"""
EXECUTION_STAGE: {stage}
STRICT_JSON_OUTPUT: TRUE
NO_META_TEXT: TRUE

[SYSTEM]
{identity}

{rules}

[TASK]
{task}

<INPUT_DATA_BEGIN>
{json.dumps(input_data, ensure_ascii=False)}
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

    raw_output = _call_ollama(prompt)

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

    identity = _read_md(DOMAIN, stage, "identity.md")
    rules = _read_md(DOMAIN, stage, "rules.md")
    task = _read_md(DOMAIN, stage, "task.md")

    prompt = _build_prompt(identity, rules, task, state, stage)

    _heartbeat(f"{stage}_generation_started")

    raw_output = _call_ollama(prompt)

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
        "reference_synopses": [],
        "reader_signals": [],
        "abstract": "",
        "synopsis": "",
    }

    _tmp_write(tmp_file, state)

    _heartbeat("payload_ready")

    for stage in PIPELINE_STAGES:

        state = _tmp_read(tmp_file)

        result = _execute_stage(stage, state)

        state.update(result)

        _tmp_write(tmp_file, state)

        if stage == "synopsis_validator":

            if result.get("status") != "APPROVED":
                raise RuntimeError("SYNOPSIS_VALIDATION_FAILED")

    _heartbeat("finalized")

    final_state = _tmp_read(tmp_file)

    _tmp_delete(tmp_file)

    return {
        "synopsis": final_state.get("synopsis", "")
    }