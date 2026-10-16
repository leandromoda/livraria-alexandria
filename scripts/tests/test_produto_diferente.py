"""
Portão de "produto diferente" (assert puro, sem rede).

    PYTHONPATH=. python tests/test_produto_diferente.py

Casos reais da varredura de 2026-10-16: amostra de 400 das 2.349 ofertas
publicadas com link de produto do ML, classificada à mão (11 errados, 4
ambíguos, 383 corretos). Ver o comentário de `_produto_diferente` em
steps/marketplace_scraper.py.
"""

import os
import sys
import types

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SCRIPTS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, SCRIPTS_ROOT)

# marketplace_scraper importa requests/bs4 no topo e o CI não roda pip install.
for nome in ("requests", "bs4"):
    try:
        __import__(nome)
    except ImportError:
        m = types.ModuleType(nome)
        if nome == "bs4":
            m.BeautifulSoup = object
        else:
            m.get = m.post = m.patch = lambda *a, **k: (_ for _ in ()).throw(AssertionError("rede"))
            m.exceptions = types.SimpleNamespace(RequestException=Exception, Timeout=Exception)
            m.Session = object
        sys.modules[nome] = m

from steps.marketplace_scraper import _produto_diferente, _titulo_score  # noqa: E402

# (nosso título, título do ML, nome completo do produto) -> errado
ERRADOS = [
    ("O Guia do Mochileiro das Galáxias", "O guia definitivo do Mochileiro das Galáxias", None),
    ("A Psicologia do Dinheiro", "Kit A Psicologia Financeira + A Arte de Gastar Dinheiro | Morgan Housel", None),
    ("Todas as Suas Imperfeições",
     "As Mil Partes Do Meu Coração + Uma Segunda Chance + Todas As Suas Imperfeições + Verity", None),
    ("A Tempestade", "A tempestade (Mangá Shakespeare)", None),
    ("E Não Sobrou Nenhum", "E não sobrou nenhum",
     "E não sobrou nenhum - graphic novel - Christie, Agatha - Globo Livros - Capa Mole"),
    ("The Portrait of a Lady",
     "Livro The Portrait Of A Lady - Hub Young Adult Readers - Stage 3 - Book With Audio Cd", None),
    ("Inferno", "LIVRO ESPERO QUE SIRVAM CERVEJA NO INFERNO", None),
]

# Corretos que o portão NÃO pode rejeitar — falso negativo tira o preço e a
# página sai do índice.
CORRETOS = [
    ("Dresden", "Dresden: Terça-feira, 13 de fevereiro de 1945"),
    ("Vineland", 'Vineland: O livro que deu origem ao filme "Uma batalha após a outra"'),
    ("Os Mitos Gregos", "Os mitos gregos: Box com dois volumes"),
    ("As Cruzadas", "Box As cruzadas"),
    ("Musashi", "BOX - MUSASHI"),
    ("O Exorcista", "O Exorcista - Edição de Luxo"),
    ("Monções", "Monções e capítulos de expansão paulista"),          # 3 a mais: limite
    ("The Stand: A Dança da Morte", "The Stand - A Dança da Morte - Livro I"),
    ("Osho - Amor, Liberdade e Solitude", "Amor, Liberdade e Solitude"),
    ("MaddAddam", "MaddAddão"),
    ("Electronic Literature", "Literatura eletrônica"),
    ("Perfeitos", "Perfeitos (Vol. 2 Feios)"),
    ("Guia dos Perplexos", "Guia Dos Perplexos Obra Completa-maimônides"),
]


def test_errados_reprovados():
    for nosso, ml, nome in ERRADOS:
        assert _produto_diferente(nosso, ml, nome), (nosso, ml)
    print(f"[OK] {len(ERRADOS)} produtos errados reprovados")


def test_corretos_passam():
    for nosso, ml in CORRETOS:
        assert _produto_diferente(nosso, ml) is None, (nosso, ml, _produto_diferente(nosso, ml))
    print(f"[OK] {len(CORRETOS)} produtos corretos aprovados")


def test_marcador_no_nosso_titulo_nao_reprova():
    # "Kit"/"definitivo" que fazem parte do NOME do livro não são sinal de pacote.
    assert _produto_diferente("O Guia Definitivo do Mochileiro das Galáxias",
                              "O guia definitivo do Mochileiro das Galáxias") is None
    assert _produto_diferente("Kit de Sobrevivência", "Kit de Sobrevivência") is None
    print("[OK] marcador presente no nosso título não reprova")


def test_portao_estrito_aplica_e_jogos_nao():
    # Livros (estrito): o kit contém todas as palavras e mesmo assim cai.
    assert _titulo_score("Comunicação Não Violenta",
                         "Kit Comunicação Não Violenta + Vive", estrito=True) is None
    assert _titulo_score("Comunicação Não Violenta",
                         "Comunicação Não Violenta", estrito=True) is not None
    # Jogos (frouxo): "box" e expansão são o próprio produto — regra não se aplica.
    assert _titulo_score("Gloomhaven", "Kit Gloomhaven + Expansão", estrito=False) is not None
    print("[OK] portão vale para livros e não para jogos")


if __name__ == "__main__":
    for nome, fn in list(globals().items()):
        if nome.startswith("test_") and callable(fn):
            fn()
    print("todos os testes passaram")
