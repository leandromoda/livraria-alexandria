"""
Testes do backfill de idioma (assert puro, sem pytest, sem rede).

    PYTHONPATH=. python tests/test_backfill_idioma.py
"""

import os
import sqlite3
import sys
import tempfile
import types

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

SCRIPTS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, SCRIPTS_ROOT)

# O tool importa requests E dotenv no topo (via enrich_descricao) e o CI nao
# roda pip install. Como os testes trocam `consultar` por stub, nenhuma chamada
# HTTP acontece — basta o nome existir. Stub so quando o real esta ausente,
# para que localmente o import de verdade continue sendo exercitado.
def _stub_requests():
    m = types.ModuleType("requests")
    m.utils = types.SimpleNamespace(quote=lambda s, safe="/": s)
    m.exceptions = types.SimpleNamespace(
        ReadTimeout=type("ReadTimeout", (Exception,), {}),
        RequestException=type("RequestException", (Exception,), {}),
    )

    def _boom(*_a, **_k):
        raise AssertionError("requests.get chamado — o teste deveria ter feito stub")

    m.get = _boom
    return m


def _stub_dotenv():
    m = types.ModuleType("dotenv")
    m.load_dotenv = lambda *_a, **_k: False
    m.find_dotenv = lambda *_a, **_k: ""
    return m


for _nome, _fab in (("requests", _stub_requests), ("dotenv", _stub_dotenv)):
    try:
        __import__(_nome)
    except ModuleNotFoundError:  # pragma: no cover — so no CI
        sys.modules[_nome] = _fab()

from tools import backfill_idioma as bi


DDL = """
CREATE TABLE livros (
    id          TEXT PRIMARY KEY,
    titulo      TEXT,
    autor       TEXT,
    isbn        TEXT,
    idioma      TEXT,
    status_enrich  INTEGER DEFAULT 0,
    status_publish INTEGER DEFAULT 0,
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at  TEXT
);
"""


def _db(livros):
    path = os.path.join(tempfile.mkdtemp(), "t.db")
    c = sqlite3.connect(path)
    c.executescript(DDL)
    for i, (tit, aut, isbn) in enumerate(livros):
        c.execute(
            "INSERT INTO livros (id,titulo,autor,isbn,idioma) VALUES (?,?,?,?,'PT')",
            ("id%d" % i, tit, aut, isbn),
        )
    c.commit()
    c.close()
    return path


class _Patch:
    def __init__(self, path, consultar):
        self.path, self.consultar = path, consultar

    def __enter__(self):
        self._gc, self._cs = bi.get_conn, bi.consultar

        def gc():
            cc = sqlite3.connect(self.path)
            cc.row_factory = sqlite3.Row
            return cc

        bi.get_conn, bi.consultar = gc, self.consultar
        return self

    def __exit__(self, *e):
        bi.get_conn, bi.consultar = self._gc, self._cs
        return False


def _rows(path):
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    out = [dict(r) for r in c.execute(
        "SELECT titulo, idioma, idioma_checado_em FROM livros ORDER BY id")]
    c.close()
    return out


# ---------------------------------------------------------------- testes

def test_mapeia_bcp47():
    assert bi.mapear_idioma("pt") == "PT"
    assert bi.mapear_idioma("pt-BR") == "PT"
    assert bi.mapear_idioma("en-GB") == "EN"
    assert bi.mapear_idioma("ES") == "ES"
    assert bi.mapear_idioma("de") is None, "idioma fora do mapa nao pode virar PT"
    assert bi.mapear_idioma(None) is None
    assert bi.mapear_idioma("") is None
    print("OK  mapeamento BCP-47 -> dominio do pipeline")


def test_grava_idioma_quando_titulo_casa():
    path = _db([("Macroeconomic Theory", "Gardner Ackley", None)])
    with _Patch(path, lambda t, a, i: ("en", "Macroeconomic Theory")):
        bi.run(escopo="travados")
    r = _rows(path)[0]
    assert r["idioma"] == "EN", r
    assert r["idioma_checado_em"], "deve marcar como checado"
    print("OK  grava idioma quando o titulo casa")


def test_casamento_fraco_nao_altera():
    """O erro caro: marcar um PT como EN tira o livro da publicacao."""
    path = _db([("Dinâmica macroeconômica", "Simonsen", None)])
    with _Patch(path, lambda t, a, i: ("en", "Principles of Macroeconomics")):
        bi.run(escopo="travados")
    r = _rows(path)[0]
    assert r["idioma"] == "PT", "casamento fraco nao pode sobrescrever: %r" % r
    print("OK  casamento fraco de titulo nao altera o idioma")


def test_isbn_dispensa_casamento_de_titulo():
    """Com ISBN a edicao e exata — titulo divergente nao invalida."""
    path = _db([("O Hobbit", "Tolkien", "9788595084742")])
    with _Patch(path, lambda t, a, i: ("pt", None)):
        bi.run(escopo="travados")
    assert _rows(path)[0]["idioma"] == "PT"
    print("OK  ISBN dispensa o casamento de titulo")


def test_sem_resposta_marca_checado():
    """Sem isto o tool re-consulta os mesmos livros e queima a cota diaria."""
    path = _db([("Titulo Obscuro", None, None)])
    with _Patch(path, lambda t, a, i: (None, None)):
        bi.run(escopo="travados")
    r = _rows(path)[0]
    assert r["idioma"] == "PT"
    assert r["idioma_checado_em"], "sem resposta ainda assim marca checado: %r" % r
    print("OK  sem resposta marca checado (nao re-consulta)")


def test_retomavel_e_dry_run():
    path = _db([("A", None, None), ("B", None, None)])
    with _Patch(path, lambda t, a, i: ("en", t)):
        bi.run(escopo="travados", dry_run=True)
        assert all(r["idioma_checado_em"] is None for r in _rows(path)), "dry-run nao grava"
        bi.run(escopo="travados", limite=1)
        checados = [r for r in _rows(path) if r["idioma_checado_em"]]
        assert len(checados) == 1, "limite deve valer: %r" % _rows(path)
        bi.run(escopo="travados")
        assert all(r["idioma_checado_em"] for r in _rows(path)), "2a passada completa"
    print("OK  dry-run nao grava; --limit e retomada funcionam")


def test_429_interrompe_sem_marcar():
    def boom(t, a, i):
        raise RuntimeError("Google Books 429 — cota diaria esgotada")

    path = _db([("A", None, None), ("B", None, None)])
    with _Patch(path, boom):
        bi.run(escopo="travados")
    assert all(r["idioma_checado_em"] is None for r in _rows(path)), \
        "429 nao pode marcar livros como checados"
    print("OK  429 interrompe sem marcar nada como checado")


if __name__ == "__main__":
    test_mapeia_bcp47()
    test_grava_idioma_quando_titulo_casa()
    test_casamento_fraco_nao_altera()
    test_isbn_dispensa_casamento_de_titulo()
    test_sem_resposta_marca_checado()
    test_retomavel_e_dry_run()
    test_429_interrompe_sem_marcar()
    print("\nTodos os testes do backfill_idioma passaram.")
