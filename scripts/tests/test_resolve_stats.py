"""
Testes da telemetria do _resolve_produto (assert puro, sem pytest, sem rede).

    PYTHONPATH=. python tests/test_resolve_stats.py

Motivo (medido em 2026-08-29): dois passes do offer_price_monitor no MESMO dia
renderam 41% (62/150, log 07-54-02) e 20% (30/150, log 10-28-52), e o log nao
permitia dizer o porque — a unica saida era `Ativos: N | Erros: N`. Descobrir
que os 120 erros eram 120 URLs do Mercado Livre (nenhuma da Amazon) exigiu
cruzar o NNNN_audit_prices.json com o books.db a mao.

"A API do ML rendeu menos" e "o scraping do ML apanhou do bot wall" sao
correcoes OPOSTAS e eram indistinguiveis no log. Estes testes fixam que cada
caminho de saida incrementa o contador certo.
"""

import os
import sys
import types

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

SCRIPTS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, SCRIPTS_ROOT)


# marketplace_scraper importa requests e bs4 no topo e o CI nao roda
# pip install. Os testes trocam fetch_page/_find_product_url por stub, entao
# nenhuma chamada HTTP acontece — basta o nome existir. Stub so quando o real
# esta ausente, para que localmente o import de verdade siga exercitado.
def _stub_requests():
    m = types.ModuleType("requests")
    m.exceptions = types.SimpleNamespace(
        ReadTimeout=type("ReadTimeout", (Exception,), {}),
        RequestException=type("RequestException", (Exception,), {}),
        ConnectTimeout=type("ConnectTimeout", (Exception,), {}),
        HTTPError=type("HTTPError", (Exception,), {}),
    )

    def _boom(*_a, **_k):
        raise AssertionError("requests.get chamado — o teste deveria ter feito stub")

    m.get = _boom
    m.post = _boom
    m.Session = lambda *_a, **_k: types.SimpleNamespace(get=_boom, post=_boom)
    return m


def _stub_bs4():
    m = types.ModuleType("bs4")

    class BeautifulSoup:  # noqa: N801
        def __init__(self, *_a, **_k):
            pass

    m.BeautifulSoup = BeautifulSoup
    return m


def _stub_dotenv():
    m = types.ModuleType("dotenv")
    m.load_dotenv = lambda *_a, **_k: False
    m.find_dotenv = lambda *_a, **_k: ""
    return m


for _nome, _fab in (("requests", _stub_requests), ("bs4", _stub_bs4),
                    ("dotenv", _stub_dotenv)):
    try:
        __import__(_nome)
    except ModuleNotFoundError:  # pragma: no cover — so no CI
        sys.modules[_nome] = _fab()

from steps import marketplace_scraper as ms  # noqa: E402


ML_URL = "https://lista.mercadolivre.com.br/dom-casmurro"
AMZ_URL = "https://www.amazon.com.br/s?k=dom+casmurro"


def _stats():
    return dict(ms._resolve_stats)


def _com_api(retorno):
    """Troca _resolve_produto_ml_api por um stub que devolve `retorno`."""
    original = ms._resolve_produto_ml_api
    ms._resolve_produto_ml_api = lambda *_a, **_k: retorno
    return original


# ---------------------------------------------------------------------------

def test_api_confirmou_nao_cai_no_scraping():
    ms.reset_resolve_stats()
    orig = ms._resolve_produto_ml_api

    def fake(*_a, **_k):
        ms._resolve_stats["ml_api_ok"] += 1
        return ({"preco": 30.0, "disponivel": True}, "https://x/p/MLB1")

    ms._resolve_produto_ml_api = fake

    def nao_chamar(*_a, **_k):
        raise AssertionError("fetch_page chamado apos a API confirmar")

    orig_fetch, ms.fetch_page = ms.fetch_page, nao_chamar
    try:
        result, url = ms._resolve_produto(ML_URL, "Dom Casmurro", "Machado")
    finally:
        ms._resolve_produto_ml_api = orig
        ms.fetch_page = orig_fetch

    s = _stats()
    assert result is not None and url.endswith("MLB1"), (result, url)
    assert s["ml_api_ok"] == 1, s
    assert s["scrape_ok"] == 0 and s["scrape_sem_pagina"] == 0, s
    print("OK  API confirmou -> ml_api_ok, sem tocar no scraping")


def test_bot_wall_conta_sem_pagina_nao_sem_card():
    """A distincao que faltava: bot wall != nenhum card compativel."""
    ms.reset_resolve_stats()
    orig = _com_api(None)
    orig_fetch, ms.fetch_page = ms.fetch_page, lambda *_a, **_k: None
    try:
        result, url = ms._resolve_produto(AMZ_URL, "Dom Casmurro", "Machado")
    finally:
        ms._resolve_produto_ml_api = orig
        ms.fetch_page = orig_fetch

    s = _stats()
    assert (result, url) == (None, None)
    assert s["scrape_sem_pagina"] == 1, s
    assert s["scrape_sem_card"] == 0, "bot wall nao pode virar 'sem card'"
    print("OK  bot wall -> scrape_sem_pagina (distinto de scrape_sem_card)")


def test_pagina_sem_card_compativel():
    ms.reset_resolve_stats()
    orig = _com_api(None)
    orig_fetch, ms.fetch_page = ms.fetch_page, lambda *_a, **_k: object()
    orig_find, ms._find_product_url = ms._find_product_url, lambda *_a, **_k: None
    try:
        ms._resolve_produto(AMZ_URL, "Dom Casmurro", "Machado")
    finally:
        ms._resolve_produto_ml_api = orig
        ms.fetch_page = orig_fetch
        ms._find_product_url = orig_find

    s = _stats()
    assert s["scrape_sem_card"] == 1, s
    assert s["scrape_sem_pagina"] == 0, s
    print("OK  pagina veio mas nenhum card casou -> scrape_sem_card")


def test_scraping_resolveu():
    ms.reset_resolve_stats()
    orig = _com_api(None)
    orig_fetch, ms.fetch_page = ms.fetch_page, lambda *_a, **_k: object()
    orig_find = ms._find_product_url
    orig_scrape = ms.scrape_marketplace
    ms._find_product_url = lambda *_a, **_k: "https://www.amazon.com.br/dp/123"
    ms.scrape_marketplace = lambda *_a, **_k: {"preco": 42.0, "disponivel": True}
    try:
        result, url = ms._resolve_produto(AMZ_URL, "Dom Casmurro", "Machado")
    finally:
        ms._resolve_produto_ml_api = orig
        ms.fetch_page = orig_fetch
        ms._find_product_url = orig_find
        ms.scrape_marketplace = orig_scrape

    s = _stats()
    assert result and "dp/123" in url, (result, url)
    assert s["scrape_ok"] == 1, s
    print("OK  scraping resolveu -> scrape_ok")


def test_reset_zera_entre_passes():
    """Sem reset, um passe herdaria os contadores do anterior no mesmo processo."""
    ms.reset_resolve_stats()
    ms._resolve_stats["ml_api_ok"] = 7
    ms._resolve_stats["scrape_sem_pagina"] = 3
    ms.reset_resolve_stats()
    assert all(v == 0 for v in ms._resolve_stats.values()), ms._resolve_stats
    print("OK  reset_resolve_stats zera tudo")


def test_linha_agregada_omite_zeros():
    ms.reset_resolve_stats()
    assert ms.resolve_stats_line() == "sem tentativas"
    ms._resolve_stats["ml_api_ok"] = 30
    ms._resolve_stats["ml_api_miss"] = 120
    linha = ms.resolve_stats_line()
    assert "ml_api_ok=30" in linha and "ml_api_miss=120" in linha, linha
    assert "scrape_ok" not in linha, f"zero nao deve aparecer: {linha}"
    print("OK  linha agregada mostra so o que aconteceu")


if __name__ == "__main__":
    test_api_confirmou_nao_cai_no_scraping()
    test_bot_wall_conta_sem_pagina_nao_sem_card()
    test_pagina_sem_card_compativel()
    test_scraping_resolveu()
    test_reset_zera_entre_passes()
    test_linha_agregada_omite_zeros()
    print("\nTodos os testes passaram.")
