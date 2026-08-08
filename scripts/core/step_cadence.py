"""Cadência de steps que só produzem quando a entrada deles mudou.

Mora em `core/` pelo mesmo motivo que `core/drain_loop.py`: `steps/autopilot.py`
arrasta ~30 steps (e com eles `requests`/`dotenv`), o que tornaria um teste de CI
frágil. Aqui só entra stdlib e a decisão é uma função pura.
"""


# Rede de segurança: mesmo sem publicação nova, roda a cada N ciclos para pegar
# lista que se torne elegível por outro caminho (dedup de autores que junta obras
# sob um autor só, livro que ganhou categoria temática no step 9). Mesmo valor e
# mesma ideia do REPAIR_SAFETY_EVERY em steps/autopilot.py.
LISTAS_SAFETY_EVERY = 25


def deve_rodar_listas(publicados_agora, publicados_no_ultimo_passe,
                      ciclos_sem_rodar, safety_every=LISTAS_SAFETY_EVERY):
    """O `list_composer` tem trabalho possível neste ciclo?

    A ENTRADA do composer só muda quando um livro é publicado — e o step
    "14 Publicar Livros" roda ANTES de "18 Listas SEO" na mesma volta do laço,
    então um livro publicado neste ciclo já é visto pelo composer neste ciclo.
    Sem esse guard ele varre ~128 categorias + ~129 temáticas + ~430 autores a
    cada ciclo só para reencontrar listas que já existem.

    Medido em 2026-08-08 nos 3 logs de ~11h de 2026-08-04/05/06 (contagem por
    `List Composer iniciado` e `Lista (temática )?criada`): 52 / 51 / 52 passes
    produziram 2 / 5 / 5 listas — 0,07 lista por passe.
    """
    if publicados_agora > publicados_no_ultimo_passe:
        return True
    return ciclos_sem_rodar >= safety_every
