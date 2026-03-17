# ============================================================
# GEMINI RATE LIMITER — Livraria Alexandria
# ============================================================
#
# Controla o uso da API Gemini para evitar custos no tier
# gratuito. Persiste contadores em data/gemini_usage.json.
#
# Tier Gratuito (gemini-2.0-flash / gemini-2.5-flash):
#   RPM_LIMIT  = 15 req/min  → padrão conservador: 12
#   RPD_LIMIT  = 1500 req/dia → padrão conservador: 1400
#   TPM_LIMIT  = 1.000.000 tokens/min (não monitorado aqui)
#
# Variáveis .env opcionais para sobrescrever:
#   GEMINI_RPM_LIMIT=12
#   GEMINI_RPD_LIMIT=1400
#   GEMINI_RPD_WARN=1200    ← aviso ao atingir esse valor
# ============================================================

import json
import os
import time
import threading
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# ============================================================
# CONFIG
# ============================================================

_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=_ENV_PATH)

RPM_LIMIT  = int(os.getenv("GEMINI_RPM_LIMIT", "12"))   # req/min (limite real: 15)
RPD_LIMIT  = int(os.getenv("GEMINI_RPD_LIMIT", "1400"))  # req/dia (limite real: 1500)
RPD_WARN   = int(os.getenv("GEMINI_RPD_WARN",  "1200"))  # aviso ao atingir

USAGE_FILE = Path(__file__).resolve().parents[1] / "data" / "gemini_usage.json"

_lock = threading.Lock()


# ============================================================
# PERSISTÊNCIA
# ============================================================

def _load() -> dict:
    """Carrega contadores. Reseta se data mudou."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if USAGE_FILE.exists():
        try:
            data = json.loads(USAGE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    else:
        data = {}

    # Reset diário automático
    if data.get("date") != today:
        data = {
            "date":            today,
            "requests_today":  0,
            "minute_window":   [],   # lista de timestamps (epoch float)
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
# CONTROLE RPM  (janela deslizante de 60 segundos)
# ============================================================

def _prune_minute_window(window: list, now: float) -> list:
    """Remove timestamps com mais de 60 segundos."""
    return [t for t in window if now - t < 60.0]


def _rpm_wait_if_needed(data: dict) -> dict:
    """
    Se a janela de 1 minuto já tem >= RPM_LIMIT chamadas,
    dorme até a mais antiga sair da janela.
    Retorna data atualizado.
    """
    now = time.time()
    window = _prune_minute_window(data.get("minute_window", []), now)

    if len(window) >= RPM_LIMIT:
        oldest = window[0]
        wait_s = 61.0 - (now - oldest)
        if wait_s > 0:
            print(
                f"[GEMINI LIMITER] RPM atingido ({len(window)}/{RPM_LIMIT}). "
                f"Aguardando {wait_s:.1f}s..."
            )
            time.sleep(wait_s)
            now = time.time()
            window = _prune_minute_window(window, now)

    data["minute_window"] = window
    return data


# ============================================================
# CONTROLE RPD
# ============================================================

def _rpd_check(data: dict) -> None:
    """
    Avisa ou levanta erro se o limite diário for atingido.
    """
    n = data.get("requests_today", 0)

    if n >= RPD_LIMIT:
        raise RuntimeError(
            f"GEMINI_DAILY_LIMIT_REACHED — {n}/{RPD_LIMIT} req hoje. "
            "Reinicie amanhã ou eleve GEMINI_RPD_LIMIT no .env."
        )

    if n >= RPD_WARN:
        print(
            f"[GEMINI LIMITER] AVISO: {n}/{RPD_LIMIT} requisições hoje. "
            f"Aproximando do limite diário."
        )


# ============================================================
# INTERFACE PÚBLICA
# ============================================================

def acquire() -> None:
    """
    Deve ser chamado ANTES de cada requisição à API Gemini.
    - Checa e aplica throttle de RPM (dorme se necessário)
    - Checa limite diário (levanta RuntimeError se atingido)
    - Registra a requisição nos contadores
    """
    with _lock:
        data = _load()

        # 1. Verifica/espera RPM
        data = _rpm_wait_if_needed(data)

        # 2. Verifica RPD (antes de registrar)
        _rpd_check(data)

        # 3. Registra chamada
        now = time.time()
        data["minute_window"].append(now)
        data["requests_today"] = data.get("requests_today", 0) + 1

        _save(data)

        n = data["requests_today"]
        rpm_now = len(data["minute_window"])
        print(
            f"[GEMINI LIMITER] req #{n}/{RPD_LIMIT} hoje  |  "
            f"RPM: {rpm_now}/{RPM_LIMIT}"
        )


def status() -> dict:
    """Retorna snapshot dos contadores atuais (não bloqueia, não registra)."""
    with _lock:
        data = _load()
        now = time.time()
        window = _prune_minute_window(data.get("minute_window", []), now)
        return {
            "date":            data.get("date"),
            "requests_today":  data.get("requests_today", 0),
            "rpm_last_minute": len(window),
            "rpm_limit":       RPM_LIMIT,
            "rpd_limit":       RPD_LIMIT,
            "rpd_remaining":   max(0, RPD_LIMIT - data.get("requests_today", 0)),
        }


def reset_daily() -> None:
    """
    Força reset do contador diário (útil para testes ou
    quando a data mudou mas o processo ainda está rodando).
    """
    with _lock:
        data = _load()
        data["requests_today"] = 0
        data["minute_window"] = []
        _save(data)
        print("[GEMINI LIMITER] Contador diário zerado.")
