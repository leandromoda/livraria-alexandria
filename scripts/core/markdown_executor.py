from pathlib import Path
from datetime import datetime
import json
import subprocess
import uuid
import shutil


# ======================================================
# PATHS
# ======================================================

BASE_DIR = Path(__file__).resolve().parents[2]
AGENTS_DIR = BASE_DIR / "agents"
RUNTIME_DIR = BASE_DIR / "runtime" / "tmp"

RUNTIME_DIR.mkdir(parents=True, exist_ok=True)


# ======================================================
# HEARTBEAT
# ======================================================

def _heartbeat(stage: str):
    now = datetime.utcnow().isoformat()
    print(f"[heartbeat] {now} :: {stage}")


# ======================================================
# FILE HELPERS
# ======================================================

def _read_md(agent_name: str, filename: str) -> str:
    path = AGENTS_DIR / agent_name / filename
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _tmp_path():
    return RUNTIME_DIR / f"tmp_synopsis_{uuid.uuid4().hex}.json"


def _tmp_write(path: Path, data: dict):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _tmp_read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _tmp_delete(path: Path):
    if path.exists():
        path.unlink()


# ======================================================
# MODEL CALL
# ======================================================

def _call_ollama(prompt: str) -> str:

    result = subprocess.run(
        ["ollama", "run", "phi3:mini"],
        input=prompt.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    return result.stdout.decode("utf-8", errors="ignore").strip()


# ======================================================
# PROMPT BUILDER (INPUT SANDBOX)
# ======================================================

def _build_prompt(identity, rules, workflow, task, input_data):

    return f"""
[SYSTEM]
{identity}

{rules}

[PROCESS]
{workflow}

[TASK]
{task}

<INPUT_DATA_BEGIN>
{json.dumps(input_data, ensure_ascii=False)}
</INPUT_DATA_END>
"""


# ======================================================
# STAGE EXECUTION
# ======================================================

def _execute_stage(agent_name, stage_name, payload):

    identity = _read_md(agent_name, "identity.md")
    rules = _read_md(agent_name, "rules.md")
    workflow = _read_md(agent_name, "workflow.md")
    task = _read_md(agent_name, "task.md")

    prompt = _build_prompt(identity, rules, workflow, task, payload)

    _heartbeat(f"{stage_name}_generation_started")

    output = _call_ollama(prompt)

    _heartbeat(f"{stage_name}_generation_finished")

    return output


# ======================================================
# CRITIC
# ======================================================

def _run_critic(agent_name, text):

    critic = _read_md(agent_name, "critic.md")

    prompt = f"""
{critic}

TEXT:
{text}
"""

    _heartbeat("critic_started")

    result = _call_ollama(prompt)

    _heartbeat("critic_finished")

    return result


# ======================================================
# SAFE JSON PARSER
# ======================================================

def _safe_json(text: str):

    try:
        return json.loads(text)
    except Exception:
        return {"synopsis": text.strip()}


# ======================================================
# MAIN EXECUTOR
# ======================================================

def execute_agent(agent_name: str, context: dict):

    print(f"[agent] executing '{agent_name}'")

    _heartbeat("markdown_loaded")

    # ==================================================
    # TEMP FILE CREATE
    # ==================================================

    tmp_file = _tmp_path()

    runtime_state = {
        "titulo": context.get("titulo"),
        "autor": context.get("autor"),
        "collected_synopses": [],
        "collected_reviews": [],
        "brief_description": "",
        "final_synopsis": ""
    }

    _tmp_write(tmp_file, runtime_state)

    _heartbeat("payload_ready")

    # ==================================================
    # STAGE A — COLLECT SIGNALS
    # ==================================================

    stage_payload = _tmp_read(tmp_file)

    collect_output = _execute_stage(
        agent_name,
        "collect",
        stage_payload
    )

    data = _safe_json(collect_output)
    stage_payload.update(data)

    _tmp_write(tmp_file, stage_payload)

    # ==================================================
    # STAGE B — ABSTRACT
    # ==================================================

    abstract_output = _execute_stage(
        agent_name,
        "abstract",
        _tmp_read(tmp_file)
    )

    data = _safe_json(abstract_output)
    stage_payload.update(data)

    _tmp_write(tmp_file, stage_payload)

    # ==================================================
    # STAGE C — SYNTHESIZE
    # ==================================================

    synth_output = _execute_stage(
        agent_name,
        "synthesize",
        _tmp_read(tmp_file)
    )

    data = _safe_json(synth_output)

    synopsis_text = data.get("synopsis", "")

    # ==================================================
    # CRITIC PASS
    # ==================================================

    critic_result = _run_critic(agent_name, synopsis_text)

    if "APPROVED" not in critic_result:
        print("[executor] critic rejected — returning last candidate")

    _heartbeat("finalized")

    # ==================================================
    # CLEANUP
    # ==================================================

    _tmp_delete(tmp_file)

    return {"synopsis": synopsis_text}