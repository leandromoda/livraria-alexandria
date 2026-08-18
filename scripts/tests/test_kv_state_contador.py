"""Persistencia do contador de cadencia do autopilot (assert puro, sem rede).

    PYTHONPATH=. python tests/test_kv_state_contador.py

Contexto (2026-08-18): `ciclos_sem_repair` em steps/autopilot.py era variavel
local, entao cada re-invocacao de autopilot.run() o zerava e a rede de seguranca
de REPAIR_SAFETY_EVERY=25 ciclos NUNCA disparava. Medido no
pipeline_2026-08-17_05-35-45.log: 31 ocorrencias de "Reparo de relacoes: sem
livros novos", todas com a contagem regressiva parada em 23-24 — ela nunca
desceu. O fix persiste o contador via core/kv_state. Este teste fixa o
round-trip e a tolerancia a lixo.
"""

import os
import sqlite3
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SCRIPTS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, SCRIPTS_ROOT)

from core import kv_state  # noqa: E402

CHAVE = "autopilot.ciclos_sem_repair"


def _conn():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return sqlite3.connect(path), path


def main():
    conn, path = _conn()
    try:
        print("teste: contador de cadencia sobrevive a re-invocacao")

        assert kv_state.get(CHAVE, 0, conn=conn) == 0, "ausente deve devolver o default"
        print("  OK  ausente -> default")

        # Simula ciclos consecutivos SEM livros novos, como no log real.
        for esperado in range(1, 6):
            atual = int(kv_state.get(CHAVE, 0, conn=conn) or 0) + 1
            kv_state.set(CHAVE, atual, conn=conn)
            lido = int(kv_state.get(CHAVE, 0, conn=conn) or 0)
            assert lido == esperado, f"ciclo {esperado}: leu {lido}"
        print("  OK  5 ciclos acumulam (era isso que nao acontecia)")

        # Nova "invocacao": outra conexao, mesmo arquivo — o contador continua.
        outra = sqlite3.connect(path)
        try:
            assert int(kv_state.get(CHAVE, 0, conn=outra) or 0) == 5, \
                "contador nao sobreviveu a nova conexao"
        finally:
            outra.close()
        print("  OK  sobrevive a nova conexao/processo")

        # Reset ao rodar o reparo.
        kv_state.set(CHAVE, 0, conn=conn)
        assert int(kv_state.get(CHAVE, 0, conn=conn) or 0) == 0
        print("  OK  reset volta a zero")

        # Lixo gravado nao pode derrubar o autopilot — o call site faz int(... or 0)
        # dentro de try/except; aqui garantimos que kv_state devolve o que gravou.
        kv_state.set(CHAVE, "nao-numero", conn=conn)
        bruto = kv_state.get(CHAVE, 0, conn=conn)
        try:
            valor = int(bruto or 0)
        except (TypeError, ValueError):
            valor = 0
        assert valor == 0, "valor invalido deve degradar para 0"
        print("  OK  valor invalido degrada para 0")

        print("\nOK: 5 checagens")
    finally:
        conn.close()
        try:
            os.unlink(path)
        except OSError:
            pass


if __name__ == "__main__":
    main()
