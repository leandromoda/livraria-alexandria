"""Cadência do list_composer no autopilot — core/step_cadence.py.

Convenção do projeto: assert puro, sem pytest. Só stdlib, para não exigir passo
de instalação no CI.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.step_cadence import deve_rodar_listas, LISTAS_SAFETY_EVERY  # noqa: E402


def test_publicacao_nova_dispara():
    """Livro publicado neste ciclo => o composer tem entrada nova."""
    assert deve_rodar_listas(101, 100, 0) is True
    assert deve_rodar_listas(3_700, 3_699, 5) is True


def test_sem_publicacao_nao_dispara():
    """É o caso dominante nos logs: nada publicou, nada a compor."""
    assert deve_rodar_listas(100, 100, 0) is False
    assert deve_rodar_listas(100, 100, LISTAS_SAFETY_EVERY - 1) is False


def test_rede_de_seguranca_dispara_no_limite():
    """Sem publicação nova, ainda assim roda a cada LISTAS_SAFETY_EVERY ciclos —
    pega lista que ficou elegível por outro caminho (dedup de autores, categoria
    temática nova)."""
    assert deve_rodar_listas(100, 100, LISTAS_SAFETY_EVERY) is True
    assert deve_rodar_listas(100, 100, LISTAS_SAFETY_EVERY + 3) is True


def test_contagem_regressiva_nao_dispara():
    """Publicados só DIMINUÍREM (despublicação/blacklist) não é entrada nova."""
    assert deve_rodar_listas(98, 100, 0) is False


def test_cenario_medido_dos_logs():
    """Reproduz o observado em 2026-08-04/05/06: ~11h de ciclos sem publicação.

    Nos logs, 52 passes de list_composer produziram 2 listas. Com o guard, uma
    sequência de 60 ciclos sem publicação alguma roda o composer só pelas redes
    de segurança — 60 // 25 = 2 passes, não 60.
    """
    passes = 0
    ciclos_sem_rodar = 0
    publicados = 3_700          # cravado: nada publica (quota LLM esgotada)
    ultimo = publicados
    for _ in range(60):
        if deve_rodar_listas(publicados, ultimo, ciclos_sem_rodar):
            passes += 1
            ultimo = publicados
            ciclos_sem_rodar = 0
        else:
            ciclos_sem_rodar += 1
    assert passes == 2, f"esperado 2 passes de segurança em 60 ciclos, veio {passes}"


if __name__ == "__main__":
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {nome}")
    print("test_step_cadence OK")
