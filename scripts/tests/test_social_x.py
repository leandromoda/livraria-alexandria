"""
"Livro do dia" no X — partes sem LLM (assert puro, sem rede).

    PYTHONPATH=. python tests/test_social_x.py
"""

import json
import os
import sqlite3
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SCRIPTS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, SCRIPTS_ROOT)

from steps import social_x as sx  # noqa: E402


def test_montar_numera_e_poe_convite_com_utm():
    finais = sx.montar(["Principal.", "Um.", "Dois.", "Três."], "dom-casmurro")
    assert len(finais) == 5
    assert finais[0].endswith("01/05") and finais[-1].endswith("05/05")
    assert "livrariaalexandria.com.br/livros/dom-casmurro?utm_source=x" in finais[-1]
    assert "utm_campaign=livro-do-dia" in finais[-1]
    # numeração que o agente tenha escrito é removida, não duplicada
    assert sx.montar(["Texto 01/04", "a.", "b.", "c."], "x")[0].count("/") == 1
    print("[OK] numeração gerada aqui e convite com UTM no fim")


def test_url_conta_23():
    assert sx.tamanho_x("ver https://livrariaalexandria.com.br/livros/um-slug-bem-comprido?utm_source=x") == 4 + 23
    print("[OK] URL conta 23 caracteres, como no X")


def test_hashtag_so_no_principal_e_no_maximo_2():
    assert sx.verificar_parte("Texto. #ficção #clássicos\n01/05", principal=True) == []
    assert any("hashtags" in p for p in
               sx.verificar_parte("Texto. #a #b #c\n01/05", principal=True))
    assert any("fora do post principal" in p for p in sx.verificar_parte("Texto. #a\n02/05"))
    print("[OK] até 2 hashtags, só no post principal")


def test_proibidas_e_forma():
    probs = sx.verificar_parte("Leitura obrigatória! Você sabia disso...\n02/05")
    texto = " ".join(probs)
    assert "exclamação" in texto and "reticências" in texto
    assert "leitura obrigatória" in texto and "você sabia" in texto
    print("[OK] exclamação, reticências e expressões proibidas")


def test_estrutura_conta_comentarios_do_agente():
    assert 0 in sx.problemas_mecanicos(["P.", "a.", "b."], "s")          # 2 comentários
    assert 0 not in sx.problemas_mecanicos(["P.", "a.", "b.", "c."], "s")
    assert 0 in sx.problemas_mecanicos(["P."] + ["x."] * 7, "s")        # 7 comentários
    print("[OK] 3 a 6 comentários do agente (+ convite)")


def test_json_da_saida_tolera_cerca():
    obj = sx._json_da_saida('Aqui está:\n```json\n{"partes": ["a", "b"]}\n```')
    assert obj["partes"] == ["a", "b"]
    print("[OK] JSON extraído mesmo com cerca de código")


def _banco():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE livros (id TEXT PRIMARY KEY, titulo TEXT, autor TEXT, slug TEXT,
            ano_publicacao INTEGER, sinopse TEXT, wiki TEXT, wiki_qid TEXT, imagem_url TEXT,
            status_publish INTEGER, is_publishable INTEGER, preco_atual REAL, priority_score INTEGER);
        CREATE TABLE livros_categorias_tematicas (livro_id TEXT, categoria_slug TEXT,
            confidence REAL, primary_cat INTEGER);
        CREATE TABLE livros_autores (livro_id TEXT, autor_id TEXT);
        CREATE TABLE autores (id TEXT, wiki TEXT);
    """)
    sx.ensure_schema(c)
    wp = json.dumps({"qid": "Q1", "wikipedia": {"pt": "https://pt.wikipedia.org/wiki/X"}})
    livros = [
        # id, slug, score, wiki, qid, preço, grupo(slug)
        ("a1", "a1", 1000, None, None, 30.0, "romance-brasileiro"),
        ("a2", "a2", 1000, wp, "Q1", 30.0, "romance-brasileiro"),      # mais conhecido do grupo
        ("b1", "b1", 1000, None, None, 30.0, "ficcao-cientifica-classica"),
        ("c1", "c1", 1000, wp, "Q2", None, "romance-brasileiro"),     # sem preço: inelegível
    ]
    for lid, slug, score, wiki, qid, preco, cat in livros:
        c.execute("INSERT INTO livros VALUES (?,?,?,?,?,?,?,?,?,1,1,?,?)",
                  (lid, lid.upper(), "Autor", slug, 2000, "Sinopse.", wiki, qid, None, preco, score))
        c.execute("INSERT INTO livros_categorias_tematicas VALUES (?,?,1.0,1)", (lid, cat))
    return c


def test_rodizio_por_grupo_e_popularidade():
    orig = sx._taxonomia
    sx._taxonomia = lambda: {"romance-brasileiro": ("Romance Brasileiro", "Literatura Brasileira"),
                             "ficcao-cientifica-classica": ("FC Clássica", "Ficção Científica")}
    try:
        c = _banco()
        lid, grupo = sx.escolher_livro(c)
        # nenhum grupo usado ainda: ordem alfabética de grupo -> Ficção Científica
        assert (lid, grupo) == ("b1", "Ficção Científica"), (lid, grupo)
        c.execute("INSERT INTO social_posts (livro_id, slug, categoria, status, partes, criado_em)"
                  " VALUES ('b1','b1','Ficção Científica','publicado','[]','2026-10-17T10:00:00')")
        lid, grupo = sx.escolher_livro(c)
        # próximo grupo; dentro dele vence quem tem Wikipédia pt, não o alfabético
        assert (lid, grupo) == ("a2", "Literatura Brasileira"), (lid, grupo)
        c.execute("INSERT INTO social_posts (livro_id, slug, categoria, status, partes, criado_em)"
                  " VALUES ('a2','a2','Literatura Brasileira','descartado','[]','2026-10-17T11:00:00')")
        # descartado não volta; sem preço nunca entra
        lid, _ = sx.escolher_livro(c)
        assert lid == "a1", lid
    finally:
        sx._taxonomia = orig
    print("[OK] rodízio por grupo, mais conhecido primeiro, sem repetir nem pegar sem preço")


if __name__ == "__main__":
    for nome, fn in list(globals().items()):
        if nome.startswith("test_") and callable(fn):
            fn()
    print("todos os testes passaram")
