"""Slot secundário do llm_orchestrator — rodízio, gate de staleness e cursor.

Fixa o que a medição de 2026-08-09 motivou: uma janela da sessão PRO comporta
5-6 chamadas (n=3, logs de 08-04/05/06), então gastar 2 delas em tarefas
secundárias custava 33-40% da janela. O slot reduz isso a 1.

Convenção do projeto: assert puro, sem pytest. `llm_orchestrator` arrasta
`requests`/`dotenv` e o pipeline inteiro, então os módulos pesados entram como
stub em `sys.modules` ANTES do import — mesma técnica de
`tests/test_backfill_idioma.py` —, e só quando o real está ausente, para o
import de verdade continuar exercitado localmente.
"""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _stub(nome, **attrs):
    """Instala um módulo falso só se o real não existir."""
    try:
        __import__(nome)
        return
    except ImportError:
        pass
    mod = types.ModuleType(nome)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[nome] = mod


def _boom(*a, **k):
    raise AssertionError("saída de rede não esperada no teste")


_stub("requests", get=_boom, post=_boom,
      exceptions=types.SimpleNamespace(ConnectionError=Exception,
                                       RequestException=Exception))
_stub("dotenv", load_dotenv=lambda *a, **k: None)

from steps import llm_orchestrator as orch  # noqa: E402


# ── Dublês ──────────────────────────────────────────────────────────────────

class Cenario:
    """Substitui as dependências do slot: cursor, pendências, auditoria e LLM."""

    def __init__(self, *, bios=100, classify=100, vencida=None):
        self.cursor = None                 # None = nunca gravado (1ª execução)
        self.bios = bios
        self.classify = classify
        self.vencida = vencida             # (label, modo) ou None
        self.chamadas = []                 # quem consumiu o slot, em ordem

    def instalar(self, monkey):
        monkey(orch.kv_state, "get",
               lambda k, default=None, conn=None: (self.cursor
                                                   if self.cursor is not None
                                                   else default))
        monkey(orch.kv_state, "set",
               lambda k, v, conn=None: setattr(self, "cursor", str(v)))
        monkey(orch, "get_conn", lambda: types.SimpleNamespace(close=lambda: None))
        monkey(orch, "_count_pending_author_bio", lambda conn: self.bios)
        monkey(orch, "_count_pending_classify", lambda conn: self.classify)
        monkey(orch, "_auditoria_llm_vencida", lambda conn: self.vencida)

        def _bio(cota):
            self.chamadas.append("author_bio")
            return min(cota, self.bios), False

        def _cls(cota):
            self.chamadas.append("classify")
            return min(cota, self.classify), False

        def _aud(label, modo, cota):
            self.chamadas.append(f"audit:{modo}")
            return 0, False

        monkey(orch, "_rotacao_author_bio", _bio)
        monkey(orch, "_rotacao_classify", _cls)
        monkey(orch, "_rodar_auditoria_llm", _aud)


_originais = []


def monkey(obj, nome, valor):
    _originais.append((obj, nome, getattr(obj, nome)))
    setattr(obj, nome, valor)


def restaurar():
    while _originais:
        obj, nome, valor = _originais.pop()
        setattr(obj, nome, valor)


def rodar(cenario, ciclos=1):
    cenario.instalar(monkey)
    try:
        for _ in range(ciclos):
            orch._slot_secundario()
        return list(cenario.chamadas)
    finally:
        restaurar()


# ── 1. UMA chamada por ciclo, não duas ──────────────────────────────────────
# É o ponto inteiro da mudança: 2 de 5-6 chamadas por janela viravam 1.
c = Cenario()
chamadas = rodar(c, ciclos=1)
assert len(chamadas) == 1, f"o slot deve gastar 1 chamada, gastou {len(chamadas)}: {chamadas}"

# ── 2. O rodízio alterna de verdade ─────────────────────────────────────────
c = Cenario()
chamadas = rodar(c, ciclos=4)
assert chamadas == ["author_bio", "classify", "author_bio", "classify"], chamadas

# ── 3. O cursor sobrevive à reinicialização do processo ─────────────────────
# O caso que quebraria tudo: em memória, o cursor reiniciaria a cada
# `python main.py` e — como o limite da sessão bate no Ciclo 1 — author_bio
# ganharia o slot SEMPRE e classify nunca rodaria.
c = Cenario()
rodar(c, ciclos=1)                       # 1ª execução: author_bio
cursor_persistido = c.cursor
assert cursor_persistido is not None, "o cursor tem de ser gravado"

c2 = Cenario()                            # processo novo…
c2.cursor = cursor_persistido             # …que lê o cursor do pipeline_state
chamadas = rodar(c2, ciclos=1)
assert chamadas == ["classify"], (
    f"após reiniciar, a vez era de classify; veio {chamadas}. "
    "Sem persistência o rodízio degenera em 'sempre o primeiro'."
)

# ── 4. Auditoria vencida preempta o rodízio ─────────────────────────────────
c = Cenario(vencida=("22 Conteúdo (LLM)", "content"))
chamadas = rodar(c, ciclos=1)
assert chamadas == ["audit:content"], chamadas

# ── 5. O GATE é o que protege a publicação ──────────────────────────────────
# Dentro do limiar (48h/168h) a auditoria NÃO ocupa o slot. É a diferença entre
# ~2% e ~17-20% da janela — sem isso, a auditoria custaria 1 das 5-6 chamadas
# TODA janela, cortando a sinopse de 3 para 2 lotes.
c = Cenario(vencida=None)
chamadas = rodar(c, ciclos=6)
assert not any(x.startswith("audit") for x in chamadas), (
    f"auditoria não vencida não pode gastar o slot: {chamadas}"
)

# ── 6. AUDIT_LLM_POR_CICLO=0 desliga as auditorias ──────────────────────────
c = Cenario(vencida=("22 Conteúdo (LLM)", "content"))
monkey(orch, "AUDIT_LLM_POR_CICLO", 0)
try:
    c.instalar(monkey)
    orch._slot_secundario()
finally:
    restaurar()
assert c.chamadas == ["author_bio"], (
    f"com AUDIT_LLM_POR_CICLO=0 o slot volta ao rodízio; veio {c.chamadas}"
)

# ── 7. Quem não tem trabalho passa a vez sem gastar o slot ──────────────────
c = Cenario(bios=0)                       # sem bios pendentes
chamadas = rodar(c, ciclos=1)
assert chamadas == ["classify"], f"devia pular bios e usar classify: {chamadas}"

c = Cenario(bios=0, classify=0)           # nada a fazer
chamadas = rodar(c, ciclos=1)
assert chamadas == [], f"sem pendências, nenhuma chamada: {chamadas}"

# ── 8. SLOT_SECUNDARIO=0 restaura as duas rotações fixas ────────────────────
c = Cenario()
monkey(orch, "SLOT_SECUNDARIO", 0)
try:
    c.instalar(monkey)
    orch._slot_secundario()
finally:
    restaurar()
assert c.chamadas == ["author_bio", "classify"], (
    f"com SLOT_SECUNDARIO=0 o comportamento antigo volta; veio {c.chamadas}"
)

print("test_slot_secundario OK")
