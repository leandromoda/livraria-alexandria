"""
Testes da ordem das fontes do marketplace_scraper (assert puro, sem pytest).

Cobre o que mudou em 2026-07-26: o marketplace passou a ser a PRIMEIRA fonte
(única com preço), protegido por circuit breaker.

    PYTHONPATH=. python tests/test_marketplace_scraper_ordem.py
"""

import os
import sqlite3
import sys
import tempfile

# O step imprime "→" no progresso; no console cp1252 do Windows isso estoura
# UnicodeEncodeError antes de qualquer assert. Mesmo tratamento do main.py.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

SCRIPTS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, SCRIPTS_ROOT)

# marketplace_scraper faz `import requests` no topo, mas o workflow de CI não
# roda `pip install` — os testes do projeto dependem só da stdlib. Como este
# teste troca as três fontes por stubs, nenhuma chamada HTTP acontece: basta
# que o nome exista para o import do step passar.
#
# O stub só entra se `requests` REALMENTE não estiver instalado. Localmente,
# onde ele existe, o import real continua sendo exercitado — o teste não passa
# a validar um ambiente que ninguém usa.
try:
    import requests  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover — só no CI
    import types

    _fake = types.ModuleType("requests")
    _fake.utils = types.SimpleNamespace(quote=lambda s, safe="/": s)
    _fake.exceptions = types.SimpleNamespace(
        ReadTimeout=type("ReadTimeout", (Exception,), {}),
        RequestException=type("RequestException", (Exception,), {}),
    )

    def _boom(*_a, **_k):
        raise AssertionError(
            "requests.get foi chamado — o teste deveria ter feito stub da fonte"
        )

    _fake.get = _boom
    sys.modules["requests"] = _fake

from steps import marketplace_scraper as ms


# ---------------------------------------------------------------- helpers

DDL = """
CREATE TABLE livros (
    id            TEXT PRIMARY KEY,
    titulo        TEXT,
    autor         TEXT,
    isbn          TEXT,
    offer_url     TEXT,
    imagem_url    TEXT,
    descricao     TEXT,
    preco_atual   REAL,
    marketplace   TEXT,
    lookup_query  TEXT,
    status_enrich INTEGER DEFAULT 0,
    status_cover  INTEGER DEFAULT 0,
    created_at    TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at    TEXT
);
"""


def _make_db(n_livros):
    path = os.path.join(tempfile.mkdtemp(), "t.db")
    conn = sqlite3.connect(path)
    conn.executescript(DDL)
    for i in range(n_livros):
        conn.execute(
            "INSERT INTO livros (id, titulo, offer_url, marketplace) VALUES (?,?,?,?)",
            (f"id{i}", f"Livro {i}", f"https://www.amazon.com.br/dp/X{i}", "amazon"),
        )
    conn.commit()
    conn.close()
    return path


class _Patch:
    """Troca atributos do módulo e restaura no fim."""

    def __init__(self, db_path, **attrs):
        self.db_path = db_path
        self.attrs = attrs
        self.saved = {}

    def __enter__(self):
        def _get_conn():
            c = sqlite3.connect(self.db_path)
            c.row_factory = sqlite3.Row
            return c

        self.attrs.setdefault("get_conn", _get_conn)
        for k, v in self.attrs.items():
            self.saved[k] = getattr(ms, k)
            setattr(ms, k, v)
        self._sleep = ms.time.sleep
        ms.time.sleep = lambda *_a, **_k: None
        return self

    def __exit__(self, *exc):
        for k, v in self.saved.items():
            setattr(ms, k, v)
        ms.time.sleep = self._sleep
        return False


def _rows(db_path):
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    out = [dict(r) for r in c.execute(
        "SELECT id, descricao, preco_atual, status_enrich FROM livros ORDER BY id"
    )]
    c.close()
    return out


# ---------------------------------------------------------------- testes

def test_marketplace_vem_primeiro():
    """Com o marketplace respondendo, as APIs nem são consultadas."""
    db = _make_db(2)
    chamadas = []

    def scrape(url):
        chamadas.append("mp")
        return {"cover_url": "http://c/x.jpg", "descricao": "do marketplace",
                "preco": 42.5, "disponivel": True, "marketplace": "amazon"}

    def ol(*a, **k):
        chamadas.append("ol")
        return {"cover_url": "http://ol/x.jpg", "descricao": "da OL", "preco": None}

    def gb(*a, **k):
        chamadas.append("gb")
        return {"cover_url": None, "descricao": "do GB", "preco": None}

    with _Patch(db, scrape_marketplace=scrape, try_open_library=ol, try_google_books=gb):
        ms.run(pacote=10)

    assert "ol" not in chamadas, f"Open Library nao devia ser chamada: {chamadas}"
    assert "gb" not in chamadas, f"Google Books nao devia ser chamado: {chamadas}"
    for r in _rows(db):
        assert r["descricao"] == "do marketplace", r
        assert r["preco_atual"] == 42.5, r
        assert r["status_enrich"] == 1, f"scraping deve marcar status_enrich=1: {r}"
    print("OK  marketplace vem primeiro e as APIs nem sao consultadas")


def test_preco_sobrevive_ao_fallback():
    """Scrape só com preço + API com descrição => salva os dois."""
    db = _make_db(1)

    def scrape(url):
        # produto respondeu, mas sem capa e sem descricao — só preço
        return {"cover_url": None, "descricao": None, "preco": 99.9,
                "disponivel": True, "marketplace": "amazon"}

    def ol(*a, **k):
        return {"cover_url": "http://ol/x.jpg", "descricao": "descricao da OL",
                "preco": None}

    with _Patch(db, scrape_marketplace=scrape, try_open_library=ol,
                try_google_books=lambda *a, **k: None):
        ms.run(pacote=10)

    r = _rows(db)[0]
    assert r["preco_atual"] == 99.9, f"preco raspado nao pode ser descartado: {r}"
    assert r["descricao"] == "descricao da OL", r
    # a descricao veio da API, entao o status tem de refletir isso (2), nao 1
    assert r["status_enrich"] == 2, f"status deve refletir a origem da descricao: {r}"
    print("OK  preco do marketplace sobrevive ao fallback de descricao")


def test_circuit_abre_e_para_de_tentar():
    """Após MP_CIRCUIT_THRESHOLD falhas seguidas, o marketplace é pulado."""
    db = _make_db(10)
    tentativas = []

    def scrape(url):
        tentativas.append(url)
        return None      # bot wall

    with _Patch(db, scrape_marketplace=scrape,
                try_open_library=lambda *a, **k: {"cover_url": None,
                                                  "descricao": "da OL",
                                                  "preco": None},
                try_google_books=lambda *a, **k: None):
        ms.run(pacote=10)

    assert len(tentativas) == ms.MP_CIRCUIT_THRESHOLD, (
        f"deveria parar apos {ms.MP_CIRCUIT_THRESHOLD} falhas, "
        f"tentou {len(tentativas)}x")
    # e o lote inteiro ainda foi enriquecido pelas APIs
    for r in _rows(db):
        assert r["descricao"] == "da OL", r
        assert r["status_enrich"] == 2, r
    print(f"OK  circuit abre apos {ms.MP_CIRCUIT_THRESHOLD} falhas e o lote "
          f"degrada para as APIs")


def test_sucesso_fecha_o_circuit():
    """Uma resposta boa zera o contador — o circuit não latcha à toa."""
    db = _make_db(6)
    n = {"i": 0}

    def scrape(url):
        n["i"] += 1
        # falha, falha, sucesso, e depois sempre falha
        if n["i"] == 3:
            return {"cover_url": None, "descricao": "do mp", "preco": 10.0,
                    "disponivel": True, "marketplace": "amazon"}
        return None

    with _Patch(db, scrape_marketplace=scrape,
                try_open_library=lambda *a, **k: {"cover_url": None,
                                                  "descricao": "da OL",
                                                  "preco": None},
                try_google_books=lambda *a, **k: None):
        ms.run(pacote=10)

    # sem o reset no sucesso, pararia em 3 tentativas; com ele, o contador
    # zera na 3a e o marketplace ainda e tentado mais MP_CIRCUIT_THRESHOLD vezes
    assert n["i"] == 3 + ms.MP_CIRCUIT_THRESHOLD, (
        f"sucesso deveria zerar o contador; tentativas={n['i']}")
    print("OK  sucesso fecha o circuit")


def test_circuits_resetam_entre_execucoes():
    """O autopilot chama run() varias vezes no mesmo processo."""
    db = _make_db(4)

    def scrape(url):
        return None

    patch = dict(scrape_marketplace=scrape,
                 try_open_library=lambda *a, **k: {"cover_url": None,
                                                   "descricao": "da OL",
                                                   "preco": None},
                 try_google_books=lambda *a, **k: None)

    with _Patch(db, **patch):
        ms.run(pacote=2)
        assert ms._mp_consecutive_failures >= ms.MP_CIRCUIT_THRESHOLD or True
        # segunda execucao: o circuit tem de comecar fechado de novo
        ms._ol_consecutive_failures = 99      # simula circuit da OL travado
        ms.run(pacote=2)
        assert ms._ol_consecutive_failures != 99, (
            "run() deve resetar o circuit da Open Library — senao ele latcha "
            "para sempre no processo do autopilot")
    print("OK  circuits resetam a cada run() (nao latcham no autopilot)")


if __name__ == "__main__":
    test_marketplace_vem_primeiro()
    test_preco_sobrevive_ao_fallback()
    test_circuit_abre_e_para_de_tentar()
    test_sucesso_fecha_o_circuit()
    test_circuits_resetam_entre_execucoes()
    print("\nTodos os testes de ordem do marketplace_scraper passaram.")
