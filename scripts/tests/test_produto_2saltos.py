"""
Testes da resolucao busca -> produto (2 saltos) e da fila do monitor de precos.

Cobre o que mudou em 2026-08-23 (TASK-OFERTAS-004): o `offer_price_monitor`
lia o preco do PRIMEIRO CARD da pagina de busca aplicando seletores de pagina
de produto. Medido no books.db: 4.849 dos 4.856 livros publicados (99,9%) tem
`offer_url` de busca, e a busca de "O Guia do Mochileiro das Galaxias" devolvia
4 precos, dois deles de OUTROS livros da serie.

    PYTHONPATH=. python tests/test_produto_2saltos.py
"""

import os
import sqlite3
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

SCRIPTS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, SCRIPTS_ROOT)

# Mesmo tratamento de `tests/test_marketplace_scraper_ordem.py`: o step importa
# `requests` no topo e o workflow de CI nao roda `pip install`. Este teste nao
# faz rede nenhuma (a "soup" e um stub), entao basta o nome existir. Localmente,
# onde requests existe, o import real continua sendo exercitado.
try:
    import requests  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover -- so no CI
    import types

    _fake = types.ModuleType("requests")
    _fake.utils = types.SimpleNamespace(quote=lambda s, safe="/": s)
    _fake.exceptions = types.SimpleNamespace(
        ReadTimeout=type("ReadTimeout", (Exception,), {}),
        RequestException=type("RequestException", (Exception,), {}),
    )

    def _boom(*_a, **_k):
        raise AssertionError("requests.get foi chamado — este teste nao faz rede")

    _fake.get = _boom
    sys.modules["requests"] = _fake

from steps import marketplace_scraper as ms          # noqa: E402
from steps import offer_price_monitor as opm         # noqa: E402


# ------------------------------------------------------------------ stubs
# "Soup" minima: evita depender de beautifulsoup4, que tambem nao esta
# instalado no CI. So precisa do subconjunto que `_find_product_url` usa.

class FakeTag:
    def __init__(self, texto="", href=None):
        self.texto = texto
        self.attrs = {"href": href} if href is not None else {}

    def get_text(self, *_a, **_k):
        return self.texto

    def get(self, k, default=None):
        return self.attrs.get(k, default)


class FakeCard:
    def __init__(self, titulo, hrefs, texto_extra=""):
        self.titulo = titulo
        self.hrefs = hrefs
        self.texto_extra = texto_extra

    def select_one(self, _sel):
        return FakeTag(self.titulo)

    def select(self, _sel):
        return [FakeTag(href=h) for h in self.hrefs]

    def get_text(self, *_a, **_k):
        return f"{self.titulo} {self.texto_extra}"


class FakeSoup:
    def __init__(self, cards):
        self.cards = cards

    def select(self, _sel):
        return self.cards


def _asin(n):
    return f"https://www.amazon.com.br/dp/{n}"


# ------------------------------------------------------- 1. casamento de titulo

def test_serie_nao_casa_no_regime_estrito():
    """O falso positivo medido em 2026-08-23: livro 5 da mesma serie, mesmo autor."""
    buscado = "O Guia do Mochileiro das Galaxias"
    outro   = "Praticamente Inofensiva - Volume 5. Serie O Mochileiro das Galaxias"

    # Regime frouxo (jogos, inalterado): 2 de 3 tokens = 0,67 >= 0,6 -> aceita.
    assert ms._titulo_compativel(buscado, outro) is True

    # Regime estrito (livros): falta o token "guia" -> rejeita. E o autor ser o
    # mesmo (Douglas Adams) NAO salva: o portao de titulo vem antes.
    assert ms._titulo_compativel(buscado, outro, autor="Douglas Adams",
                                 texto_card=outro, estrito=True) is False
    print("[OK] titulo de outro livro da serie e rejeitado no regime estrito")


def test_edicao_do_mesmo_livro_casa():
    """Tokens extras de edicao nao podem reprovar — sao o caso normal."""
    assert ms._titulo_compativel(
        "Comece pelo Porque",
        "Comece pelo porque - Edicao comemorativa, revista e atualizada",
        autor="Simon Sinek",
        texto_card="Comece pelo porque ... por Simon Sinek",
        estrito=True,
    ) is True
    print("[OK] edicao comemorativa do mesmo livro e aceita")


def test_autor_diferente_rejeita():
    """Titulo bate, autor nao aparece no card -> rejeita no regime estrito."""
    assert ms._titulo_compativel(
        "A Metamorfose", "A Metamorfose",
        autor="Franz Kafka", texto_card="A Metamorfose | por Outro Escritor",
        estrito=True,
    ) is False
    # Sem autor conhecido a checagem nao se aplica.
    assert ms._titulo_compativel("A Metamorfose", "A Metamorfose",
                                 estrito=True) is True
    print("[OK] autor ausente no card reprova; sem autor conhecido, nao reprova")


# --------------------------------------------------- 2. escolha do melhor card

def test_escolhe_o_card_de_maior_pontuacao():
    """Na busca medida, o card certo e o 'O guia do mochileiro das galaxias'.
    'O guia definitivo...' tambem passa o portao, mas pontua menos."""
    soup = FakeSoup([
        FakeCard("O guia definitivo do mochileiro das galaxias",
                 [_asin("AAAAAAAAAA")], "Douglas Adams"),
        FakeCard("O guia do mochileiro das galaxias",
                 [_asin("BBBBBBBBBB")], "Douglas Adams"),
    ])
    url = ms._find_product_url(soup, "amazon", "O Guia do Mochileiro das Galaxias",
                               autor="Douglas Adams", estrito=True)
    assert url == _asin("BBBBBBBBBB"), url
    print("[OK] escolhe o card de maior pontuacao, nao o primeiro")


def test_pula_patrocinado():
    soup = FakeSoup([
        FakeCard("A Metamorfose",
                 ["https://www.amazon.com.br/sspa/click?url=/dp/CCCCCCCCCC",
                  _asin("DDDDDDDDDD")],
                 "Franz Kafka"),
    ])
    url = ms._find_product_url(soup, "amazon", "A Metamorfose",
                               autor="Franz Kafka", estrito=True)
    assert url == _asin("DDDDDDDDDD"), url
    print("[OK] link patrocinado (/sspa/) e pulado")


def test_sem_card_compativel_devolve_none():
    soup = FakeSoup([FakeCard("Outro Livro Qualquer", [_asin("EEEEEEEEEE")])])
    assert ms._find_product_url(soup, "amazon", "A Metamorfose",
                                autor="Franz Kafka", estrito=True) is None
    print("[OK] sem card compativel -> None (nada de raspar a busca)")


def test_ml_pula_anuncio():
    soup = FakeSoup([
        FakeCard("A Metamorfose Franz Kafka",
                 ["https://click1.mercadolivre.com.br/mclics?to=/MLB-123",
                  "https://produto.mercadolivre.com.br/MLB-999888777-a-metamorfose"],
                 "Franz Kafka"),
    ])
    url = ms._find_product_url(soup, "mercadolivre", "A Metamorfose",
                               autor="Franz Kafka", estrito=True)
    assert url == "https://produto.mercadolivre.com.br/MLB-999888777-a-metamorfose", url
    print("[OK] anuncio do ML (click1/mclics) e pulado")


# ------------------------------------------------------- 3. deteccao de busca

def test_reconhece_url_de_busca():
    assert opm._e_url_de_busca(
        "https://www.amazon.com.br/s?k=A+Metamorfose+livro&tag=x") is True
    assert opm._e_url_de_busca(
        "https://lista.mercadolivre.com.br/a-metamorfose-livro") is True
    assert opm._e_url_de_busca("https://www.amazon.com.br/dp/8535914846") is False
    assert opm._e_url_de_busca(
        "https://produto.mercadolivre.com.br/MLB-999-a-metamorfose") is False
    print("[OK] URL de busca distinguida de pagina de produto")


# ------------------------------------------------------------ 4. fila do monitor

# `isbn` entrou na fila em 2026-08-29: e a chave de busca preferencial da API
# de catalogo do ML (TASK-OFERTAS-005). Sem a coluna aqui, fetch_pending quebra.
DDL = """
CREATE TABLE livros (
    id TEXT PRIMARY KEY,
    titulo TEXT, autor TEXT, isbn TEXT, slug TEXT, offer_url TEXT,
    supabase_id TEXT,
    preco_atual REAL, preco_updated_at TEXT, offer_status TEXT,
    status_publish INTEGER DEFAULT 0
);
"""


def test_fila_prioriza_quem_nao_tem_preco():
    """Cobertura antes de refresh: 553 de 4.856 visitados (11%) em 2026-08-23."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    conn.executemany(
        "INSERT INTO livros (id, titulo, offer_url, preco_atual, preco_updated_at,"
        " status_publish) VALUES (?, ?, 'https://www.amazon.com.br/s?k=x', ?, ?, 1)",
        [
            ("a", "Com preco antigo",  49.9, "2026-01-01"),
            ("b", "Sem preco, visitado", None, "2026-08-20"),
            ("c", "Sem preco, nunca visitado", None, None),
        ],
    )
    conn.commit()

    ordem = [r["id"] for r in opm.fetch_pending(conn, 10, priorizar_ml=False)]
    assert ordem[0] == "c", ordem   # nunca visitado, sem preco
    assert ordem[1] == "b", ordem   # sem preco, visitado ha mais tempo
    assert ordem[2] == "a", ordem   # ja tem preco -> por ultimo
    conn.close()
    print("[OK] fila poe quem nao tem preco antes de quem so precisa de refresh")


def test_fila_prioriza_mercado_livre():
    """ML antes de Amazon — os dois lados tem economia oposta.

    Medido no passe do G de 2026-08-29: 50 livros em 11m26s renderam 12 precos,
    e os 12 vieram TODOS da API do ML. Os da Amazon consumiram quase todo o
    tempo em backoff de 503 e renderam zero.

      ML via API ......... ~1-2 s por livro, 37% de aproveitamento
      Amazon (scraping) .. ~13,7 s por livro, ~0% sob bot wall

    Sem esta ordem, a fila real comecava com 12 de 12 livros da Amazon.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    conn.executemany(
        "INSERT INTO livros (id, titulo, offer_url, preco_atual, preco_updated_at,"
        " status_publish) VALUES (?, ?, ?, NULL, ?, 1)",
        [
            # a Amazon foi vista ha MAIS tempo: no round-robin puro ela vem antes
            ("amz", "Livro da Amazon", "https://www.amazon.com.br/s?k=x", "2026-01-01"),
            ("ml",  "Livro do ML", "https://lista.mercadolivre.com.br/y", "2026-08-01"),
        ],
    )
    conn.commit()

    assert [r["id"] for r in opm.fetch_pending(conn, 10)] == ["ml", "amz"]
    # E continua reversivel, para quando o backlog do ML drenar ou o bot wall cair.
    assert [r["id"] for r in opm.fetch_pending(conn, 10, priorizar_ml=False)] == \
        ["amz", "ml"]
    conn.close()
    print("[OK] ML vem antes da Amazon, e PRIORIZAR_ML=0 reverte")


if __name__ == "__main__":
    test_serie_nao_casa_no_regime_estrito()
    test_edicao_do_mesmo_livro_casa()
    test_autor_diferente_rejeita()
    test_escolhe_o_card_de_maior_pontuacao()
    test_pula_patrocinado()
    test_sem_card_compativel_devolve_none()
    test_ml_pula_anuncio()
    test_reconhece_url_de_busca()
    test_fila_prioriza_quem_nao_tem_preco()
    test_fila_prioriza_mercado_livre()
    print("\nTodos os testes passaram.")
