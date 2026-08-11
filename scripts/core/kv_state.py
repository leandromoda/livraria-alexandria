"""Chave/valor persistente sobre a tabela `pipeline_state`.

Existe para estado que precisa **sobreviver ao processo**. O caso que motivou:
o cursor do rodízio do slot secundário (`steps/llm_orchestrator._slot_secundario`).
Um contador em memória reiniciaria a cada `python main.py` e, como o limite da
sessão PRO bate no Ciclo 1 (medido em 2026-08-09 nos logs de 08-04/05/06: 5-6
chamadas por janela), o primeiro da fila ganharia o slot SEMPRE e os demais
nunca rodariam. É a mesma armadilha já documentada duas vezes no projeto — o
seed de `repair_synced_ids` em `steps/autopilot.py` e os guards do autopilot
zerados a cada re-invocação (ver `core/drain_loop.py`).

`core/markdown_memory.py` usa a mesma tabela, mas prefixa a chave por agente
(`memory_key`) e loga a cada leitura — serve para memória de agente LLM, não
para estado de controle. Aqui as chaves são livres e as operações, silenciosas.
"""

from datetime import datetime

from core.db import get_conn


def _ensure(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pipeline_state (
            key        TEXT PRIMARY KEY,
            value      TEXT,
            updated_at DATETIME
        )
    """)


def get(key: str, default=None, conn=None):
    """Lê `key`. Devolve `default` se ausente. Nunca levanta."""
    own = conn is None
    if own:
        conn = get_conn()
    try:
        _ensure(conn)
        row = conn.execute(
            "SELECT value FROM pipeline_state WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else default
    except Exception:
        return default
    finally:
        if own:
            conn.close()


def set(key: str, value, conn=None) -> None:
    """Grava `key` (upsert). Falha de I/O não pode derrubar o pipeline."""
    own = conn is None
    if own:
        conn = get_conn()
    try:
        _ensure(conn)
        conn.execute("""
            INSERT INTO pipeline_state (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value      = excluded.value,
                updated_at = excluded.updated_at
        """, (key, str(value), datetime.utcnow().isoformat()))
        conn.commit()
    except Exception:
        pass
    finally:
        if own:
            conn.close()
