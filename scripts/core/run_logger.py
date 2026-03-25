# ============================================================
# RUN LOGGER — Registro de execução de steps do pipeline
# Livraria Alexandria
#
# Uso:
#   from core.run_logger import StepRun
#
#   with StepRun("enrich_descricao", idioma="PT", pacote=50):
#       enrich_descricao.run(50)
#
# Persiste em pipeline_runs (SQLite). Captura início, fim,
# duração e erros automaticamente via context manager.
# ============================================================

import traceback
import uuid
from datetime import datetime, timezone

from core.db import get_conn


class StepRun:
    """Context manager que grava início e fim de um step em pipeline_runs."""

    def __init__(
        self,
        step_name: str,
        idioma: str = None,
        pacote: int = None,
        invocado_por: str = "manual",
    ):
        self._id          = uuid.uuid4().hex[:16]
        self._step_name   = step_name
        self._idioma      = idioma
        self._pacote      = pacote
        self._invocado_por = invocado_por
        self._started_at  = None

    def __enter__(self) -> "StepRun":
        self._started_at = datetime.now(timezone.utc)
        try:
            conn = get_conn()
            conn.execute(
                """
                INSERT INTO pipeline_runs
                    (id, step_name, idioma, pacote, started_at, status, invocado_por)
                VALUES (?, ?, ?, ?, ?, 'running', ?)
                """,
                (
                    self._id,
                    self._step_name,
                    self._idioma,
                    self._pacote,
                    self._started_at.isoformat(),
                    self._invocado_por,
                ),
            )
            conn.close()
        except Exception:
            pass  # log nunca deve bloquear o pipeline
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        finished_at = datetime.now(timezone.utc)
        duracao     = (finished_at - self._started_at).total_seconds()
        status      = "error" if exc_type else "success"
        erro_msg    = (
            "".join(traceback.format_exception(exc_type, exc_val, exc_tb))
            if exc_type
            else None
        )
        try:
            conn = get_conn()
            conn.execute(
                """
                UPDATE pipeline_runs
                SET finished_at = ?,
                    duracao_s   = ?,
                    status      = ?,
                    erro_msg    = ?
                WHERE id = ?
                """,
                (finished_at.isoformat(), duracao, status, erro_msg, self._id),
            )
            conn.close()
        except Exception:
            pass  # log nunca deve bloquear o pipeline
        return False  # não suprime exceções


def recent_runs(n: int = 20) -> list[dict]:
    """Retorna as últimas N execuções de steps registradas."""
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        """
        SELECT step_name, idioma, pacote, started_at, duracao_s, status, erro_msg, invocado_por
        FROM pipeline_runs
        ORDER BY started_at DESC
        LIMIT ?
        """,
        (n,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows
