# ============================================================
# CLAUDE USAGE TRACKER — Livraria Alexandria
# ============================================================
#
# Rastreia chamadas ao claude CLI feitas pelo llm_orchestrator.
# Detecta erros de limite de sessão no output e aguarda o tempo
# necessário para o reset antes de retomar automaticamente.
#
# Limite de sessão do Claude Code (Pro/Max):
#   Janela rotativa configurável via .env:
#     CLAUDE_SESSION_RESET_MINUTES=300   ← padrão: 5 horas
#
# O arquivo de estado (claude_usage.json) persiste entre sessões
# e reseta automaticamente quando a data UTC muda.
# ============================================================

import json
import os
import re
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv

# ============================================================
# CONFIG
# ============================================================

_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=_ENV_PATH)

# Janela de reset da sessão em minutos (padrão: 5 horas)
SESSION_RESET_MINUTES = int(os.getenv("CLAUDE_SESSION_RESET_MINUTES", "300"))

USAGE_FILE = Path(__file__).resolve().parents[1] / "data" / "claude_usage.json"

_lock = threading.Lock()

# Padrões de texto que indicam limite de sessão atingido no output do claude CLI
LIMIT_PATTERNS = [
    "usage limit",
    "rate limit",
    "too many requests",
    "quota exceeded",
    "limit reached",
    "exceeded your",
    "over the limit",
    "limit has been reached",
    "claude is unavailable",
    "429",                    # HTTP status em stderr
    "unavailable",
]

# Regex para extrair minutos de espera explícitos na mensagem ("try again in X minutes")
_WAIT_MINUTES_RE = re.compile(
    r"(?:try again in|aguard[ea]|wait)\s+(\d+)\s*(?:min|minute)",
    re.IGNORECASE,
)


# ============================================================
# PERSISTÊNCIA
# ============================================================

def _load() -> dict:
    """Carrega estado. Reseta contador diário se data UTC mudou."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if USAGE_FILE.exists():
        try:
            data = json.loads(USAGE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    else:
        data = {}

    if data.get("date") != today:
        data = {
            "date":            today,
            "calls_today":     0,
            "calls_total":     data.get("calls_total", 0),  # acumula entre dias
            "limit_hit_count": data.get("limit_hit_count", 0),
            "limit_hit_at":    data.get("limit_hit_at"),
        }
        _save(data)

    return data


def _save(data: dict) -> None:
    USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    USAGE_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ============================================================
# DETECÇÃO DE LIMITE
# ============================================================

def is_limit_error(output: str) -> bool:
    """Retorna True se o output do claude CLI indica limite de sessão."""
    lower = output.lower()
    return any(pattern in lower for pattern in LIMIT_PATTERNS)


def _parse_wait_minutes(output: str) -> int | None:
    """Tenta extrair minutos de espera explícitos da mensagem de erro."""
    m = _WAIT_MINUTES_RE.search(output)
    return int(m.group(1)) if m else None


# ============================================================
# CONTABILIZAÇÃO
# ============================================================

def record_call(success: bool, output: str) -> bool:
    """
    Registra uma chamada ao claude CLI.
    Deve ser chamado APÓS cada run_agent(), independente do resultado.
    Retorna True se limite de sessão detectado.
    """
    with _lock:
        data = _load()
        data["calls_today"] = data.get("calls_today", 0) + 1
        data["calls_total"] = data.get("calls_total", 0) + 1

        limit_hit = not success and is_limit_error(output)
        if limit_hit:
            data["limit_hit_at"]    = datetime.now(timezone.utc).isoformat()
            data["limit_hit_count"] = data.get("limit_hit_count", 0) + 1

        _save(data)
    return limit_hit


# ============================================================
# ESPERA ATÉ RESET
# ============================================================

def wait_for_reset(output: str = "", log_fn=print) -> None:
    """
    Aguarda o tempo necessário para o reset de limite de sessão.

    Estratégia (em ordem de prioridade):
    1. Minutos explícitos na mensagem de erro do CLI
    2. CLAUDE_SESSION_RESET_MINUTES (padrão: 300 min / 5 horas)

    Loga progresso a cada 5 minutos durante a espera.
    """
    parsed = _parse_wait_minutes(output)
    wait_minutes = (parsed + 1) if parsed else SESSION_RESET_MINUTES  # +1 min de buffer

    reset_at = datetime.now(timezone.utc) + timedelta(minutes=wait_minutes)

    log_fn(
        f"[CLAUDE_USAGE] Limite de sessão atingido. "
        f"Aguardando {wait_minutes} min até {reset_at.strftime('%H:%M UTC')} "
        f"(CLAUDE_SESSION_RESET_MINUTES={SESSION_RESET_MINUTES})."
    )

    remaining_secs = wait_minutes * 60
    while remaining_secs > 0:
        chunk = min(300, remaining_secs)   # acorda a cada 5 min para logar progresso
        time.sleep(chunk)
        remaining_secs -= chunk
        if remaining_secs > 0:
            log_fn(
                f"[CLAUDE_USAGE] Aguardando reset de sessão… "
                f"{remaining_secs // 60} min restantes "
                f"(reset às {reset_at.strftime('%H:%M UTC')})."
            )

    log_fn("[CLAUDE_USAGE] Reset de sessão — retomando orquestrador.")


# ============================================================
# INTERFACE PÚBLICA
# ============================================================

def status() -> dict:
    """Retorna snapshot dos contadores (sem side effects)."""
    with _lock:
        data = _load()
        return {
            "date":            data.get("date"),
            "calls_today":     data.get("calls_today", 0),
            "calls_total":     data.get("calls_total", 0),
            "limit_hit_count": data.get("limit_hit_count", 0),
            "limit_hit_at":    data.get("limit_hit_at"),
            "session_reset_minutes": SESSION_RESET_MINUTES,
        }


def reset_daily() -> None:
    """Força reset do contador diário (útil para testes)."""
    with _lock:
        data = _load()
        data["calls_today"] = 0
        _save(data)
        print("[CLAUDE_USAGE] Contador diário zerado.")
