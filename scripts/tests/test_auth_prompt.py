"""Pedido de credencial visivel: abre janela sem travar o pipeline.

Fixa o pedido do Leandro em 2026-08-29: "nao adianta o G so avisar, tem que
abrir uma janela para logar quando necessario". O G roda desacompanhado por
horas — o log de 2026-08-24 durou ~23h —, entao aviso em arquivo nao resolve.

As tres propriedades que este teste protege sao justamente as que, se
quebrarem, transformam a ajuda em problema:
  1. NAO bloqueia (senao a rodada de madrugada para esperando input)
  2. UMA vez por processo por servico (senao abre dezenas de abas em 23h)
  3. Desligavel por ABRIR_LOGIN=0 (headless/CI)

    PYTHONPATH=. python tests/test_auth_prompt.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from core import auth_prompt  # noqa: E402

ABERTAS = []
auth_prompt.webbrowser = type("W", (), {  # stub: nenhum navegador de verdade
    "open": staticmethod(lambda url, new=0: ABERTAS.append(url) or True)})()

ARGS = dict(url="https://exemplo.invalido/devcenter", motivo="m",
            como_resolver="r")


# ── 1. Abre na primeira vez ─────────────────────────────────────────────────
auth_prompt.resetar(); ABERTAS.clear()
os.environ.pop("ABRIR_LOGIN", None)
assert auth_prompt.pedir(servico="svc-A", **ARGS) is True
assert ABERTAS == ["https://exemplo.invalido/devcenter"], ABERTAS
print("[OK] abre a janela na primeira vez")

# ── 2. NAO reabre para o mesmo servico ──────────────────────────────────────
# Em 23h de laco, sem esta guarda, o G abriria uma aba por ciclo.
for _ in range(5):
    assert auth_prompt.pedir(servico="svc-A", **ARGS) is False
assert len(ABERTAS) == 1, f"reabriu: {ABERTAS}"
print("[OK] nao reabre para o mesmo servico no mesmo processo")

# ── 3. Servico DIFERENTE abre ───────────────────────────────────────────────
# ML e Claude CLI sao credenciais distintas; uma nao pode calar a outra.
assert auth_prompt.pedir(servico="svc-B", **ARGS) is True
assert len(ABERTAS) == 2, ABERTAS
print("[OK] servico diferente abre a propria janela")

# ── 4. ABRIR_LOGIN=0 nao abre nada ──────────────────────────────────────────
auth_prompt.resetar(); ABERTAS.clear()
os.environ["ABRIR_LOGIN"] = "0"
try:
    assert auth_prompt.habilitado() is False
    assert auth_prompt.pedir(servico="svc-C", **ARGS) is False
    assert ABERTAS == [], ABERTAS
finally:
    os.environ.pop("ABRIR_LOGIN", None)
print("[OK] ABRIR_LOGIN=0 nao abre navegador")

# ── 5. Navegador que explode NAO derruba o pipeline ─────────────────────────
# Servidor headless levanta excecao no webbrowser.open. Isso nao pode virar
# falha do passe: a credencial e um acessorio, o pipeline tem trabalho a fazer.
auth_prompt.resetar(); ABERTAS.clear()


def _explode(url, new=0):
    raise RuntimeError("sem display")


_antes = auth_prompt.webbrowser.open
auth_prompt.webbrowser.open = _explode
try:
    assert auth_prompt.pedir(servico="svc-D", **ARGS) is False   # nao levanta
finally:
    auth_prompt.webbrowser.open = _antes
print("[OK] falha ao abrir navegador nao levanta excecao")

# ── 6. pedir() nunca le stdin ───────────────────────────────────────────────
# O jeito mais facil de estragar isto e "aproveitar" e pedir a chave por input()
# — o que travaria o G ate alguem digitar. Guarda explicita.
import inspect  # noqa: E402
fonte = inspect.getsource(auth_prompt)
for proibido in ("input(", "getpass", "sys.stdin"):
    assert proibido not in fonte, f"auth_prompt nao pode bloquear em {proibido}"
print("[OK] nao ha input()/stdin — o pedido nunca bloqueia o pipeline")

print("\nTodos os testes passaram.")
