# ============================================================
# INTERRUPT — Ctrl+C cooperativo para execuções longas
# Livraria Alexandria
#
# Uso (em loops longos como o Autopilot):
#
#   from core.interrupt import install, uninstall, requested
#
#   install()
#   try:
#       while True:
#           ...
#           if requested():
#               break
#   finally:
#       uninstall()
#
# Primeiro Ctrl+C: sinaliza o pedido de parada (não interrompe a chamada
# HTTP/DB em andamento) — quem está no loop decide o próximo ponto seguro
# para parar, sem crash e sem estado inconsistente.
#
# Segundo Ctrl+C: força a saída imediata levantando KeyboardInterrupt
# normalmente, para o caso do processo estar preso e o usuário realmente
# querer encerrar já.
# ============================================================

import signal
import threading

_interrupted   = threading.Event()
_prev_handler  = None
_installed     = False


def _handler(signum, frame):
    if _interrupted.is_set():
        # Segundo Ctrl+C — força saída imediata (comportamento padrão)
        raise KeyboardInterrupt()

    _interrupted.set()
    try:
        from core.logger import log
        log(
            "[INTERRUPT] Ctrl+C recebido — encerrando com segurança após a "
            "unidade de trabalho atual. Pressione Ctrl+C novamente para forçar "
            "saída imediata."
        )
    except Exception:
        pass


def install():
    """Instala o handler cooperativo. Idempotente."""
    global _prev_handler, _installed
    _interrupted.clear()
    if not _installed:
        _prev_handler = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, _handler)
        _installed = True


def uninstall():
    """Restaura o handler de SIGINT anterior (comportamento padrão do Python)."""
    global _installed
    if _installed and _prev_handler is not None:
        signal.signal(signal.SIGINT, _prev_handler)
    _installed = False


def requested() -> bool:
    """True se o usuário pediu interrupção (primeiro Ctrl+C)."""
    return _interrupted.is_set()


def reset():
    """Limpa o pedido de interrupção sem alterar o handler instalado."""
    _interrupted.clear()
