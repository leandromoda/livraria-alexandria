"""
Testes da remocao da tag de afiliado em requisicao de MAQUINA.

    PYTHONPATH=. python tests/test_strip_afiliado.py

Motivo (medido em 2026-08-30, painel de Associados, ultimos 30 dias):

    Cliques 3.402 | Pedidos 0 | Conversao 0,00% | Ganhos R$ 0,00

O `oferta_clicks` do site tem 4 cliques de livro no total desde janeiro, e o
site recebe ~1 visita/dia da Busca. O excedente vinha do proprio pipeline:
`build_amazon_url` injeta `tag=`, a URL etiquetada e gravada em
`livros.offer_url`, e `offer_price_monitor` / step 4 chamam
`fetch_page(offer_url)` sobre ELA — ate 3 requisicoes por livro, 150 livros por
passe do G. Cada uma contava como clique de afiliado.

O contrato de Associados proibe gerar clique artificial. Estes testes fixam que
a tag sai da requisicao e CONTINUA na URL publicada.
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


def _stub(nome, fab):
    try:
        __import__(nome)
    except ModuleNotFoundError:  # pragma: no cover — so no CI
        sys.modules[nome] = fab()


def _requests():
    m = types.ModuleType("requests")
    m.exceptions = types.SimpleNamespace(
        RequestException=type("RequestException", (Exception,), {}),
        ReadTimeout=type("ReadTimeout", (Exception,), {}),
        ConnectTimeout=type("ConnectTimeout", (Exception,), {}),
        HTTPError=type("HTTPError", (Exception,), {}),
    )

    def boom(*_a, **_k):
        raise AssertionError("requests.get chamado sem stub")

    m.get = m.post = boom
    m.utils = types.SimpleNamespace(quote=lambda s, safe="/": s)
    m.Session = lambda *_a, **_k: types.SimpleNamespace(get=boom, post=boom)
    return m


def _bs4():
    m = types.ModuleType("bs4")
    m.BeautifulSoup = type("BeautifulSoup", (), {"__init__": lambda s, *a, **k: None})
    return m


def _dotenv():
    m = types.ModuleType("dotenv")
    m.load_dotenv = lambda *_a, **_k: False
    m.find_dotenv = lambda *_a, **_k: ""
    return m


_stub("requests", _requests)
_stub("bs4", _bs4)
_stub("dotenv", _dotenv)

from steps import offer_resolver as ores  # noqa: E402
from steps import marketplace_scraper as ms  # noqa: E402

AMZ = "https://www.amazon.com.br/s?k=dom+casmurro&tag=livrariaalexa-20"
AMZ_DP = "https://www.amazon.com.br/dp/8535914846?tag=livrariaalexa-20&psc=1"
ML = ("https://www.mercadolivre.com.br/p/MLB123"
      "?matt_tool=12345&matt_word=alexandria&quantity=1")


# ---------------------------------------------------------------------------

def test_remove_tag_da_amazon():
    u = ores.strip_affiliate_params(AMZ)
    assert "tag=" not in u, u
    assert "k=dom+casmurro" in u, "a busca em si tem de sobreviver"
    print("OK  tag= removida da URL da Amazon")


def test_preserva_os_demais_params():
    u = ores.strip_affiliate_params(AMZ_DP)
    assert "tag=" not in u, u
    assert "psc=1" in u, "parametro nao-afiliado nao pode ser descartado"
    assert "/dp/8535914846" in u, "o caminho do produto tem de ficar intacto"
    print("OK  remove so o de afiliado, preserva o resto")


def test_remove_afiliado_do_ml():
    u = ores.strip_affiliate_params(ML)
    assert "matt_tool" not in u and "matt_word" not in u, u
    assert "quantity=1" in u
    print("OK  matt_tool/matt_word removidos da URL do ML")


def test_idempotente_e_tolerante():
    limpa = "https://www.amazon.com.br/s?k=x"
    assert ores.strip_affiliate_params(limpa) == limpa
    assert ores.strip_affiliate_params(ores.strip_affiliate_params(AMZ)) \
        == ores.strip_affiliate_params(AMZ)
    assert ores.strip_affiliate_params("") == ""
    assert ores.strip_affiliate_params(None) is None
    print("OK  idempotente, e nao quebra com vazio/None")


def test_a_url_PUBLICADA_continua_com_a_tag():
    """A remocao e so na requisicao. O link do usuario NAO pode perder a tag."""
    u = ores.build_amazon_url("dom casmurro")
    assert "tag=" in u, "o link publicado precisa da tag — e a monetizacao"
    v = ores.inject_amazon_tag("https://www.amazon.com.br/dp/123")
    assert "tag=" in v, v
    print("OK  build_amazon_url / inject_amazon_tag seguem etiquetando")


def test_fetch_page_nao_envia_a_tag():
    """O teste que fecha o buraco: o que sai na rede nao pode ter tag."""
    vistas = []

    class Resp:
        status_code = 200
        text = "<html></html>"

    def espiao(url, **_k):
        vistas.append(url)
        return Resp()

    orig = ms.requests.get
    ms.requests.get = espiao
    try:
        ms.fetch_page(AMZ)
        ms.fetch_page(ML)
    finally:
        ms.requests.get = orig

    assert len(vistas) == 2, vistas
    for u in vistas:
        assert "tag=" not in u, f"tag vazou para a rede: {u}"
        assert "matt_tool" not in u, f"matt_tool vazou para a rede: {u}"
    assert "k=dom+casmurro" in vistas[0], vistas[0]
    assert "/p/MLB123" in vistas[1], vistas[1]
    print("OK  fetch_page nao envia parametro de afiliado na requisicao")


if __name__ == "__main__":
    test_remove_tag_da_amazon()
    test_preserva_os_demais_params()
    test_remove_afiliado_do_ml()
    test_idempotente_e_tolerante()
    test_a_url_PUBLICADA_continua_com_a_tag()
    test_fetch_page_nao_envia_a_tag()
    print("\nTodos os testes passaram.")
