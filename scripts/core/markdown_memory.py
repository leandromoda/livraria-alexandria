```python
"""
Markdown Agent Memory System
Compatible with pipeline_state table.
"""

import json
from datetime import datetime
from pathlib import Path

from core.db import get_connection
from core.logger import log


STEP_NAME = "markdown_memory"


# =========================
# KEY BUILDER
# =========================

def memory_key(agent_name: str) -> str:
    return f"agent::{agent_name}::memory"


# =========================
# LOAD MEMORY
# =========================

def load_memory(agent_name: str) -> str:

    key = memory_key(agent_name)

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT value FROM pipeline_state WHERE key=?",
        (key,),
    )

    row = cur.fetchone()

    if not row:
        log(STEP_NAME, f"No memory found for {agent_name}")
        return ""

    log(STEP_NAME, f"Memory loaded for {agent_name}")

    return row[0]


# =========================
# SAVE MEMORY
# =========================

def save_memory(agent_name: str, memory_text: str):

    key = memory_key(agent_name)

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO pipeline_state (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key)
        DO UPDATE SET
            value=excluded.value,
            updated_at=excluded.updated_at
    """, (
        key,
        memory_text,
        datetime.utcnow().isoformat()
    ))

    conn.commit()

    log(STEP_NAME, f"Memory saved for {agent_name}")


# =========================
# MEMORY UPDATE POLICY
# =========================

def update_memory_from_execution(
    agent_name: str,
    output: str,
    critic_response: str
):
    """
    Extremely conservative updater.
    Only stores stable signals.
    """

    if "APPROVED" not in critic_response.upper():
        return

    existing = load_memory(agent_name)

    snippet = output[:400].replace("\n", " ")

    new_block = f"""
### Approved Pattern ({datetime.utcnow().isoformat()})

Example snippet:
{snippet}

"""

    updated = existing + "\n" + new_block

    save_memory(agent_name, updated)
```