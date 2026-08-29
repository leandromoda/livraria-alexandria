"""Deteccao de indisponibilidade — o bug que despublicou livro a venda.

Em 2026-08-29 o monitor tirou 6 livros do ar numa passada. Tres conferidos na
hora estavam A VENDA: A Quinta Estacao (R$ 69,10), Cidade dos Ossos (R$ 300,90),
Encontro com Rama (R$ 54,85).

`is_unavailable` varria o texto INTEIRO da pagina atras das palavras de
`unavail`, e casava com boilerplate presente em TODA pagina de produto da
Amazon. Este teste usa os trechos REAIS extraidos daquelas paginas.

    PYTHONPATH=. python tests/test_indisponivel.py
"""

import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    import requests  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover — so no CI
    _f = types.ModuleType("requests")
    _f.utils = types.SimpleNamespace(quote=lambda s, safe="/": s)
    _f.exceptions = types.SimpleNamespace(
        ReadTimeout=type("ReadTimeout", (Exception,), {}),
        RequestException=type("RequestException", (Exception,), {}))
    _f.get = lambda *a, **k: (_ for _ in ()).throw(AssertionError("sem rede"))
    sys.modules["requests"] = _f

from steps import marketplace_scraper as ms  # noqa: E402

SINAIS = ms.SELECTORS["amazon"]["unavail"]


# ── "Soup" minima: so o que is_unavailable usa ──────────────────────────────
class FakeEl:
    def __init__(self, txt):
        self.txt = txt

    def get_text(self, *a, **k):
        return self.txt


class FakeSoup:
    def __init__(self, texto_pagina, regioes=None):
        self.texto = texto_pagina
        self.regioes = regioes or {}

    def get_text(self, *a, **k):
        return self.texto

    def select(self, sel):
        return [FakeEl(t) for t in self.regioes.get(sel, [])]


# Boilerplate REAL, copiado das paginas dos 3 livros em 2026-08-29.
BOILERPLATE = (
    "compra, escolha outro vendedor. %cardName% ${cardName} indisponível para o "
    "vendedor escolhido ${cardName} indisponível para quantidades acima de "
    "${maxQuantity}. Desculpe, houve um problema. Listar indisponível. "
    "Baixe o app Kindle gratuito. Imagem não disponível Imagem não disponível "
    "para Cor: VÍDEOS VISUALIZAÇÃO 360°"
)


# ── 1. O caso que causou o estrago: boilerplate + preco ─────────────────────
soup = FakeSoup(BOILERPLATE)
assert any(s.lower() in BOILERPLATE.lower() for s in SINAIS), \
    "o boilerplate precisa conter as palavras — senao o teste nao prova nada"
assert ms.is_unavailable(soup, SINAIS, preco=69.10, marketplace="amazon") is False
print("[OK] pagina com preco NAO e indisponivel, mesmo com o boilerplate")

# ── 2. Sem preco, mas o boilerplate esta FORA da regiao de disponibilidade ──
# Antes do fix isto tambem despublicava. Sem regiao declarada -> False.
assert ms.is_unavailable(soup, SINAIS, preco=None, marketplace="amazon") is False
print("[OK] boilerplate fora da regiao de disponibilidade nao conta")

# ── 3. Indisponibilidade DE VERDADE: sem preco + regiao declarando ──────────
soup_real = FakeSoup(BOILERPLATE, regioes={
    "#availability": ["Indisponível. Não sabemos quando este produto estará "
                      "disponível novamente."]})
assert ms.is_unavailable(soup_real, SINAIS, preco=None, marketplace="amazon") is True
print("[OK] regiao #availability declarando indisponivel e detectada")

# ── 4. Regiao declarando indisponivel MAS com preco: preco manda ────────────
# Livro com "indisponível" numa variacao de formato e preco na principal.
assert ms.is_unavailable(soup_real, SINAIS, preco=54.85, marketplace="amazon") is False
print("[OK] preco tem precedencia sobre a regiao")

# ── 5. Regiao presente e dizendo que TEM estoque ────────────────────────────
soup_ok = FakeSoup(BOILERPLATE, regioes={"#availability": ["Em estoque"]})
assert ms.is_unavailable(soup_ok, SINAIS, preco=None, marketplace="amazon") is False
print("[OK] 'Em estoque' na regiao nao dispara")

# ── 6. Marketplace desconhecido nunca despublica ────────────────────────────
# Sem selector de regiao, "nao consegui confirmar" NAO pode virar "indisponivel"
# quando a consequencia e tirar a pagina do ar.
assert ms.is_unavailable(soup, SINAIS, preco=None, marketplace=None) is False
assert ms.is_unavailable(soup, SINAIS, preco=None, marketplace="magalu") is False
print("[OK] sem regiao conhecida, o default seguro e 'disponivel'")

# ── 7. A constante do threshold nao pode voltar a ser letra morta ───────────
from steps import offer_price_monitor as opm  # noqa: E402
assert opm.UNAVAIL_THRESHOLD >= 2, opm.UNAVAIL_THRESHOLD
fonte = __import__("inspect").getsource(opm.process_book)
assert "ja_marcado" in fonte, (
    "process_book precisa exigir 2 deteccoes consecutivas antes de despublicar")
assert "1ª detecção" in fonte, "a 1a deteccao deve apenas registrar, sem despublicar"
print("[OK] despublicar exige 2 deteccoes consecutivas")

print("\nTodos os testes passaram.")
