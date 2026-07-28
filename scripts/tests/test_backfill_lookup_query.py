"""
Testes do backfill de lookup_query (assert puro, sem pytest, sem rede).

    PYTHONPATH=. python tests/test_backfill_lookup_query.py
"""

import os
import sqlite3
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SCRIPTS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, SCRIPTS_ROOT)

from tools import backfill_lookup_query as bl

DDL = """
CREATE TABLE livros (
    id           TEXT PRIMARY KEY,
    titulo       TEXT,
    autor        TEXT,
    lookup_query TEXT,
    idioma       TEXT,
    idioma_fonte TEXT,
    created_at   TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at   TEXT
);
"""


def _db(linhas):
    path = os.path.join(tempfile.mkdtemp(), "t.db")
    c = sqlite3.connect(path)
    c.executescript(DDL)
    for i, (tit, aut, lq, idi, fonte) in enumerate(linhas):
        c.execute(
            "INSERT INTO livros (id,titulo,autor,lookup_query,idioma,idioma_fonte) "
            "VALUES (?,?,?,?,?,?)", ("id%d" % i, tit, aut, lq, idi, fonte))
    c.commit(); c.close()
    return path


class _Patch:
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        self._gc = bl.get_conn

        def gc():
            cc = sqlite3.connect(self.path)
            cc.row_factory = sqlite3.Row
            return cc

        bl.get_conn = gc
        return self

    def __exit__(self, *e):
        bl.get_conn = self._gc
        return False


def _lq(path):
    c = sqlite3.connect(path)
    out = {t: q for t, q in c.execute("SELECT titulo, lookup_query FROM livros")}
    c.close()
    return out


def test_monta_no_padrao_do_catalogo():
    assert bl.montar("Caminhos da Mente", "Daniel Kahneman") == \
        "Caminhos da Mente Daniel Kahneman livro"
    print("OK  monta no padrao '<titulo> <autor> livro'")


def test_sem_autor_ainda_monta():
    assert bl.montar("Microeconomia e sociedade no Brasil", None) == \
        "Microeconomia e sociedade no Brasil livro"
    print("OK  sem autor ainda monta")


def test_corta_subtitulo_e_apostrofo():
    assert bl.montar("Racionais MC's: Sobrevivendo no Inferno", None) == \
        "Racionais MCs livro"
    print("OK  corta subtitulo e apostrofo")


def test_preserva_acento():
    q = bl.montar("Dinâmica macroeconômica", "Mário Henrique Simonsen")
    assert q == "Dinâmica macroeconômica Mário Henrique Simonsen livro", q
    print("OK  preserva acento")


def test_ignora_autor_institucional_longo():
    q = bl.montar("Republic of Mozambique",
                  "International Monetary Fund, Research Dept.")
    assert q == "Republic of Mozambique International Monetary Fund livro", q
    print("OK  corta autor institucional no primeiro segmento")


def test_titulo_inutil_retorna_none():
    assert bl.montar("", "Alguem") is None
    assert bl.montar("   ", None) is None
    print("OK  titulo vazio nao gera query")


def test_escopo_so_pega_pt_confirmado():
    """O ponto do escopo: nao gastar requisicao com idioma nao verificado."""
    path = _db([
        ("Dom Casmurro", "Machado", None, "PT", "google"),
        ("The Great Gatsby", "Fitzgerald", None, "PT", "fraco"),
        ("Macroeconomic Theory", "Ackley", None, "EN", "google"),
    ])
    with _Patch(path):
        bl.run(escopo="pt_confirmado")
    r = _lq(path)
    assert r["Dom Casmurro"], r
    assert r["The Great Gatsby"] is None, "idioma nao verificado fica de fora: %r" % r
    assert r["Macroeconomic Theory"] is None, "EN fica de fora: %r" % r
    print("OK  escopo pt_confirmado exclui idioma nao verificado e nao-PT")


def test_idempotente_e_dry_run():
    path = _db([("A", None, None, "PT", "google"),
                ("B", None, "ja tinha", "PT", "google")])
    with _Patch(path):
        bl.run(dry_run=True)
        assert _lq(path)["A"] is None, "dry-run nao grava"
        bl.run()
        r1 = _lq(path)
        assert r1["A"] == "A livro"
        assert r1["B"] == "ja tinha", "nao sobrescreve quem ja tinha"
        bl.run()
        assert _lq(path) == r1, "2a passada nao muda nada"
    print("OK  dry-run nao grava; idempotente; nao sobrescreve")


if __name__ == "__main__":
    test_monta_no_padrao_do_catalogo()
    test_sem_autor_ainda_monta()
    test_corta_subtitulo_e_apostrofo()
    test_preserva_acento()
    test_ignora_autor_institucional_longo()
    test_titulo_inutil_retorna_none()
    test_escopo_so_pega_pt_confirmado()
    test_idempotente_e_dry_run()
    print("\nTodos os testes do backfill_lookup_query passaram.")
