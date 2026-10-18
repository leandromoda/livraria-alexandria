"""
Testes de steps.indexnow (assert puro, sem pytest, sem rede).

    PYTHONPATH=. python tests/test_indexnow.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from steps import indexnow as ix  # noqa: E402

XML = """<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://livrariaalexandria.com.br/</loc><changefreq>weekly</changefreq></url>
<url><loc>https://livrariaalexandria.com.br/livros/a</loc><lastmod>2026-10-01T00:00:00+00:00</lastmod></url>
<url><loc>https://livrariaalexandria.com.br/livros/b</loc><lastmod>2026-10-02T00:00:00+00:00</lastmod></url>
</urlset>"""

H = "https://livrariaalexandria.com.br"


def test_parse():
    m = ix.parse_sitemap(XML)
    assert m == {
        H + "/": "",
        H + "/livros/a": "2026-10-01T00:00:00+00:00",
        H + "/livros/b": "2026-10-02T00:00:00+00:00",
    }, m


def test_primeiro_envio_manda_tudo():
    atual = ix.parse_sitemap(XML)
    assert sorted(ix.diff({}, atual)) == sorted(atual)


def test_so_o_que_mudou_e_o_que_saiu():
    atual = ix.parse_sitemap(XML)
    enviados = {
        H + "/": "",                                       # igual -> não envia
        H + "/livros/a": "2026-09-01T00:00:00+00:00",      # lastmod mudou
        H + "/livros/c": "2026-09-01T00:00:00+00:00",      # saiu do sitemap
    }
    assert sorted(ix.diff(enviados, atual)) == sorted([
        H + "/livros/a", H + "/livros/b", H + "/livros/c",
    ])


def test_aplicar_so_registra_aceitas():
    atual = ix.parse_sitemap(XML)
    enviados = {H + "/livros/c": "x"}
    novo = ix.aplicar(enviados, atual, [H + "/livros/a", H + "/livros/c"])
    # a entra com o lastmod atual; c (removida) sai do estado; b não foi aceita.
    assert novo == {H + "/livros/a": "2026-10-01T00:00:00+00:00"}, novo
    assert ix.diff(novo, atual)  # b continua pendente


def test_chave_publicada_bate():
    raiz = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    caminho = os.path.join(raiz, "public", ix.KEY + ".txt")
    with open(caminho, encoding="utf-8") as f:
        assert f.read().strip() == ix.KEY


if __name__ == "__main__":
    for nome, fn in list(globals().items()):
        if nome.startswith("test_"):
            fn()
            print("ok", nome)
