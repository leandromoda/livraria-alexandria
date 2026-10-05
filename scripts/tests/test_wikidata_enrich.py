"""
Testes de steps.wikidata_enrich (assert puro, sem pytest, sem rede).

    PYTHONPATH=. python tests/test_wikidata_enrich.py

Fixa as duas folhas do casamento (autor E título), a escolha do melhor
candidato, a regra de idioma dos rótulos e o "só tem chave quem tem dado".
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

# O step (e o isbn_backfill que ele importa) faz `import requests` no topo e o
# CI não roda pip install. Nada aqui sai pela rede — basta o nome existir.
try:
    import requests  # noqa: F401
except ImportError:
    _m = types.ModuleType("requests")

    def _boom(*_a, **_k):
        raise AssertionError("requests chamado — teste sem stub")

    _m.get = _m.patch = _m.Session = _boom
    sys.modules["requests"] = _m

from steps import wikidata_enrich as w  # noqa: E402


def _lbl(**langs):
    return {k.replace("_", "-"): {"value": v} for k, v in langs.items()}


def _claim(prop, valor, **extra):
    return {"mainsnak": {"datavalue": {"value": valor}}, "rank": "normal", **extra}


def _item(qid, labels, claims=None, sitelinks=None, aliases=None):
    return {"id": qid, "labels": labels, "aliases": aliases or {},
            "claims": claims or {}, "sitelinks": sitelinks or {}}


def _ref(qid):
    return {"id": qid}


def _tempo(ano):
    return {"time": f"+{ano:04d}-00-00T00:00:00Z", "precision": 9}


ADAMS = _item("Q42", _lbl(en="Douglas Adams"))
VANCE = _item("Q4805298", _lbl(en="Ashlee Vance"))
ISAACSON = _item("Q296539", _lbl(en="Walter Isaacson"))


def test_autor_casa():
    assert w.autor_casa("J.R.R. Tolkien", {"J. R. R. Tolkien"})
    assert w.autor_casa("Tolkien", {"J. R. R. Tolkien"})
    assert w.autor_casa("Machado de Assis", {"Joaquim Maria Machado de Assis"})
    # Um sobrenome em comum não basta: "King" casaria autores diferentes.
    assert not w.autor_casa("Carole King", {"Stephen King"})
    assert not w.autor_casa("", {"Douglas Adams"})


def test_duas_folhas_e_melhor_candidato():
    obras = {
        # mesmo título, autor errado — a biografia do Isaacson
        "Q1": _item("Q1", _lbl(en="Elon Musk"), {"P50": [_claim("P50", _ref("Q296539"))]}),
        # autor certo, título certo
        "Q2": _item("Q2", _lbl(en="Elon Musk"), {"P50": [_claim("P50", _ref("Q4805298"))]}),
        # sem P50 — nunca aceito
        "Q3": _item("Q3", _lbl(en="Elon Musk")),
    }
    auts = {"Q296539": ISAACSON, "Q4805298": VANCE}
    q, sim = w.escolher_obra("Elon Musk", "Ashlee Vance", obras, auts)
    assert q == "Q2" and sim == 1.0, (q, sim)

    q, motivo = w.escolher_obra("Elon Musk", "Fulano de Tal", obras, auts)
    assert q is None and motivo == "autor_nao_casa"

    q, motivo = w.escolher_obra("Elon Musk", "Ashlee Vance", {"Q3": obras["Q3"]}, auts)
    assert q is None and motivo == "sem_obra_com_autor"


def test_titulo_divergente_mesmo_autor():
    # Outro livro do mesmo autor não pode passar (a lição do ML: "Mistério no
    # Castelo de Chimneys" -> "Um mistério no Caribe").
    obras = {"Q9": _item("Q9", _lbl(pt="O Restaurante no Fim do Universo"),
                         {"P50": [_claim("P50", _ref("Q42"))]})}
    q, motivo = w.escolher_obra("O Guia do Mochileiro das Galáxias", "Douglas Adams",
                                obras, {"Q42": ADAMS})
    assert q is None and motivo == "titulo_divergente"


def test_titulo_original_conta_para_casar():
    obras = {"Q5": _item("Q5", _lbl(en="Brave New World"),
                         {"P50": [_claim("P50", _ref("Q8"))],
                          "P1476": [_claim("P1476", {"text": "Admirável Mundo Novo", "language": "pt"})]})}
    q, _ = w.escolher_obra("Admirável Mundo Novo", "Aldous Huxley", obras,
                           {"Q8": _item("Q8", _lbl(en="Aldous Huxley"))})
    assert q == "Q5"


def test_extrair_livro_so_com_dado_e_rotulos_pt():
    refs = {
        "Q1860": _item("Q1860", _lbl(pt="inglês")),
        "Q24925": _item("Q24925", _lbl(pt_br="ficção científica", en="science fiction")),
        "Q99": _item("Q99", _lbl(en="comic novel")),  # só en: gênero descartado
        "Q25169": _item("Q25169", _lbl(pt="À Boleia Pela Galáxia",
                                       pt_br="O Guia do Mochileiro das Galáxias")),
        "Q500": _item("Q500", _lbl(en="The Hitchhiker's Guide to the Galaxy"),
                      {"P31": [_claim("P31", _ref("Q11424"))], "P577": [_claim("P577", _tempo(2005))]}),
        "Q11424": _item("Q11424", _lbl(pt="filme")),
    }
    ent = _item("Q3107329", _lbl(en="The Hitchhiker's Guide to the Galaxy"), {
        "P1476": [_claim("P1476", {"text": "The Hitchhiker's Guide to the Galaxy"})],
        "P407": [_claim("P407", _ref("Q1860"))],
        "P577": [_claim("P577", _tempo(1980)), _claim("P577", _tempo(1979))],
        "P136": [_claim("P136", _ref("Q99")), _claim("P136", _ref("Q24925"))],
        "P179": [_claim("P179", _ref("Q25169"),
                        qualifiers={"P1545": [{"datavalue": {"value": "1"}}]})],
        "P4969": [_claim("P4969", _ref("Q500"))],
        "P648": [_claim("P648", "OL20666020W")],
    }, sitelinks={"ptwiki": {"url": "https://pt.wikipedia.org/wiki/X"}})
    d = w.extrair_livro(ent, refs)
    assert d["publicacao"] == 1979, "menor ano = primeira publicação"
    assert d["generos"] == ["ficção científica"], d["generos"]
    assert d["idioma_original"] == "inglês"
    assert d["serie"] == {"qid": "Q25169", "nome": "O Guia do Mochileiro das Galáxias", "ordem": "1"}
    assert d["adaptacoes"] == [{"titulo": "The Hitchhiker's Guide to the Galaxy",
                                "tipo": "filme", "ano": 2005}]
    assert d["wikipedia"] == {"pt": "https://pt.wikipedia.org/wiki/X"}
    assert "premios" not in d, "lista vazia não vira chave"


def test_extrair_autor():
    refs = {"Q145": _item("Q145", _lbl(pt="Reino Unido"))}
    ent = _item("Q42", _lbl(en="Douglas Adams"), {
        "P569": [_claim("P569", _tempo(1952))],
        "P570": [_claim("P570", _tempo(2001))],
        "P27": [_claim("P27", _ref("Q145"))],
    })
    assert w.extrair_autor(ent, refs) == {"qid": "Q42", "nascimento": 1952,
                                          "morte": 2001, "pais": "Reino Unido"}
    vivo = w.extrair_autor(_item("Q1", {}), {})
    assert vivo == {"qid": "Q1"}


def test_ano_negativo_e_deprecated():
    ent = {"claims": {"P577": [
        {"mainsnak": {"datavalue": {"value": {"time": "-0399-00-00T00:00:00Z"}}}, "rank": "normal"},
        {"mainsnak": {"datavalue": {"value": {"time": "-0500-00-00T00:00:00Z"}}}, "rank": "deprecated"},
    ]}}
    assert w.ano(ent, "P577") == -399


def test_consultas_subtitulo():
    assert w.consultas("Sapiens: Uma Breve História da Humanidade") == [
        "Sapiens: Uma Breve História da Humanidade", "Sapiens"]
    assert w.consultas("1984") == ["1984"]


if __name__ == "__main__":
    for nome, fn in list(globals().items()):
        if nome.startswith("test_") and callable(fn):
            fn()
            print(f"OK  {nome}")
    print("todos os testes passaram")
