"""Espera produtiva do loop multijanela (core/drain_loop.py).

Fixa o comportamento que a análise dos logs de 2026-07-23..07-30 motivou: o
autopilot não pode ser re-invocado indefinidamente quando o não-LLM está seco.

Só stdlib — `core.drain_loop` não importa nada pesado de propósito (ver o
docstring do módulo), então este teste roda no CI sem `pip install`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.drain_loop import drenar_ate_reset


class Fake:
    """Relógio, sono, autopilot e janela de sessão falsos."""

    def __init__(self, cooldown_s, pendente, trabalho_novo_em=None, novo_qtd=0,
                 custo_passe_s=60):
        self.t = 0.0
        self.cooldown_s = cooldown_s
        self.pendente = pendente
        self.trabalho_novo_em = trabalho_novo_em
        self.novo_qtd = novo_qtd
        self.custo_passe_s = custo_passe_s
        self.invocacoes = 0
        self.logs = []

    def monotonic(self):
        return self.t

    def sleep(self, n):
        self.t += n
        if self.trabalho_novo_em is not None and self.t >= self.trabalho_novo_em:
            self.pendente += self.novo_qtd
            self.trabalho_novo_em = None

    def session_window(self):
        restante = max(0, self.cooldown_s - self.t)
        return {"in_cooldown": restante > 0, "seconds_until_reset": restante}

    def count_pending(self):
        return self.pendente

    def autopilot_run(self):
        self.invocacoes += 1
        self.t += self.custo_passe_s
        if self.pendente > 0:
            self.pendente = max(0, self.pendente - 10)

    def log(self, m):
        self.logs.append(m)

    def rodar(self, **kw):
        return drenar_ate_reset(
            autopilot_run=self.autopilot_run,
            count_pending=self.count_pending,
            session_window=self.session_window,
            log=self.log,
            sleep=self.sleep,
            monotonic=self.monotonic,
            **kw,
        )


# ── 1. Cooldown inteiro sem trabalho: não pode martelar o autopilot ──────────
# Antes da correção o loop chamava autopilot.run() a cada ≤5 min (~50x em 5h).
# Com a suspensão do dreno, sobram só as re-checagens de 30 em 30 min.
f = Fake(cooldown_s=5 * 3600, pendente=0)
assert f.rodar() == "quota_restaurada"
assert f.invocacoes <= 12, f"esperava ≤12 invocações em 5h secas, veio {f.invocacoes}"
assert any("seco" in m for m in f.logs), "devia logar que suspendeu o dreno"

# ── 2. Havendo trabalho real, drena até o fim ────────────────────────────────
f = Fake(cooldown_s=5 * 3600, pendente=200)
assert f.rodar() == "quota_restaurada"
assert f.pendente == 0, f"backlog real não foi drenado (sobrou {f.pendente})"

# ── 3. Trabalho que aparece no meio da espera é pego pela rede de segurança ──
f = Fake(cooldown_s=5 * 3600, pendente=0, trabalho_novo_em=7200, novo_qtd=50)
assert f.rodar() == "quota_restaurada"
assert f.pendente == 0, f"trabalho novo não foi drenado (sobrou {f.pendente})"

# ── 4. Sem cooldown: um passe e sai ─────────────────────────────────────────
f = Fake(cooldown_s=0, pendente=0)
assert f.rodar() == "quota_restaurada"
assert f.invocacoes == 1, f"esperava 1 invocação, veio {f.invocacoes}"

# ── 5. dreno_safety_s menor => mais re-checagens (o parâmetro tem efeito) ────
f_curto = Fake(cooldown_s=5 * 3600, pendente=0)
f_curto.rodar(dreno_safety_s=600)
f_longo = Fake(cooldown_s=5 * 3600, pendente=0)
f_longo.rodar(dreno_safety_s=3600)
assert f_curto.invocacoes > f_longo.invocacoes, (
    f"dreno_safety_s sem efeito: {f_curto.invocacoes} vs {f_longo.invocacoes}"
)

# ── 6. Não entra em loop infinito quando o passe do autopilot é instantâneo ──
# (custo 0 é o pior caso para um busy-spin.)
f = Fake(cooldown_s=3600, pendente=0, custo_passe_s=0)
assert f.rodar() == "quota_restaurada"
assert f.invocacoes <= 12, f"busy-spin: {f.invocacoes} invocações"

# ── 7. `prefixo` etiqueta as linhas do chamador ──────────────────────────────
# A seção Jogos reusa este loop desde 2026-08-08 (antes ela tinha um laço
# próprio que re-rodava o quality gate a cada ≤5 min: 61/60/62 passes com
# "Aprovados: 0 | Bloqueados: 319" nos logs de 08-04/05/06). As linhas dela
# precisam sair como [J], não [G], senão o log mente sobre quem drenou.
f = Fake(cooldown_s=5 * 3600, pendente=0)
f.rodar(prefixo="[J]")
assert f.logs, "esperava alguma linha de log"
assert all(m.startswith("[J]") for m in f.logs), f"prefixo ignorado: {f.logs[:3]}"

f = Fake(cooldown_s=5 * 3600, pendente=0)
f.rodar()
assert all(m.startswith("[G]") for m in f.logs), f"padrão devia ser [G]: {f.logs[:3]}"

print("test_drain_loop OK")
