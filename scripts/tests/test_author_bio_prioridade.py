"""
Testes da prioridade da fila de bios de autor (assert puro, sem pytest).

Cobre o que mudou em 2026-08-23 (TASK-AUTORES-005): a fila era `ORDER BY
a.nome ASC`, e medido no books.db naquele dia 5.793 dos 7.884 autores sem bio
(73%) nao tinham nenhum livro publicado — a pagina de autor faz notFound()
nesse caso, entao a quota do gargalo LLM ia para paginas que respondem 404.

    PYTHONPATH=. python tests/test_author_bio_prioridade.py
"""

import json
import os
import sqlite3
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

SCRIPTS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, SCRIPTS_ROOT)

# `llm_orchestrator` puxa `requests` e `dotenv` pela cadeia de imports, e o
# workflow de CI nao roda `pip install`. Este teste nao faz rede nem le .env:
# basta o nome existir. Os stubs so entram se o modulo real estiver ausente,
# para que localmente o import de verdade continue sendo exercitado.
# Ver a nota "Testar um step que importa requests/dotenv" em scripts/CLAUDE.md.
import types  # noqa: E402

for _nome, _fabrica in (
    ("requests", lambda: types.SimpleNamespace(
        get=lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("requests.get foi chamado — este teste nao faz rede")),
        post=lambda *a, **k: None,
        utils=types.SimpleNamespace(quote=lambda s, safe="/": s),
        exceptions=types.SimpleNamespace(
            ReadTimeout=type("ReadTimeout", (Exception,), {}),
            RequestException=type("RequestException", (Exception,), {}),
        ),
    )),
    ("dotenv", lambda: types.SimpleNamespace(load_dotenv=lambda *a, **k: None)),
):
    try:
        __import__(_nome)
    except ModuleNotFoundError:  # pragma: no cover -- so no CI
        _mod = types.ModuleType(_nome)
        for _k, _v in vars(_fabrica()).items():
            setattr(_mod, _k, _v)
        sys.modules[_nome] = _mod

from steps import llm_orchestrator as orch          # noqa: E402


DDL = """
CREATE TABLE autores (
    id TEXT PRIMARY KEY, nome TEXT, nacionalidade TEXT, descricao TEXT
);
CREATE TABLE livros (
    id TEXT PRIMARY KEY, titulo TEXT, status_publish INTEGER DEFAULT 0
);
CREATE TABLE livros_autores (livro_id TEXT, autor_id TEXT);
"""


def _banco():
    """4 autores sem bio, cobrindo os casos que a ordem precisa separar:

      Zafon   2 livros publicados  -> pagina indexada, mais forte
      Nabokov 1 livro publicado    -> pagina indexada
      Mendes  1 livro NAO publicado-> pagina 404 (o livro nao conta)
      Abreu   nenhum livro         -> pagina 404

    Os nomes sao escolhidos para que a ordem ALFABETICA seja quase o inverso da
    desejada — assim o teste falha se a ordenacao voltar a ser por nome.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    conn.executemany("INSERT INTO autores (id, nome, descricao) VALUES (?, ?, NULL)", [
        ("a-zafon",   "Zafon, Carlos Ruiz"),
        ("a-nabokov", "Nabokov, Vladimir"),
        ("a-mendes",  "Mendes, Fulano"),
        ("a-abreu",   "Abreu, Beltrano"),
    ])
    conn.executemany("INSERT INTO livros (id, titulo, status_publish) VALUES (?, ?, ?)", [
        ("l1", "A Sombra do Vento", 1),
        ("l2", "O Jogo do Anjo", 1),
        ("l3", "Rascunho Inedito", 0),
        ("l4", "Lolita", 1),
    ])
    conn.executemany("INSERT INTO livros_autores (livro_id, autor_id) VALUES (?, ?)", [
        ("l1", "a-zafon"), ("l2", "a-zafon"), ("l3", "a-mendes"), ("l4", "a-nabokov"),
    ])
    conn.commit()
    return conn


def test_conta_so_quem_tem_pagina():
    conn = _banco()
    n = orch._count_pending_author_bio(conn)
    assert n == 2, f"esperado 2 (Zafon e Nabokov), veio {n}"
    conn.close()
    print("[OK] conta so autores sem bio COM livro publicado")


def test_export_ordena_por_livros_publicados():
    conn = _banco()
    tmp = tempfile.mkdtemp()
    batch_dir_original = orch.BATCH_DIR
    try:
        from pathlib import Path
        orch.BATCH_DIR = Path(tmp)
        exportados = orch._export_author_bio(conn, limite=2)
        assert exportados == 2, exportados

        arquivos = [f for f in os.listdir(tmp) if f.endswith("_author_bio_input.json")]
        assert len(arquivos) == 1, arquivos
        with open(os.path.join(tmp, arquivos[0]), encoding="utf-8") as f:
            payload = json.load(f)

        nomes = [a["nome"] for a in payload["autores"]]
        # Zafon (2 publicados) antes de Nabokov (1). Alfabeticamente Zafon seria
        # o ULTIMO dos quatro — se a ordem tivesse voltado a ser por nome, este
        # assert quebraria.
        assert nomes == ["Zafon, Carlos Ruiz", "Nabokov, Vladimir"], nomes
        print("[OK] export poe o autor mais publicado primeiro")
    finally:
        orch.BATCH_DIR = batch_dir_original
        conn.close()


def test_paginas_404_afundam_mas_nao_somem():
    """Com o lote maior que a fila util, os autores de pagina 404 entram no FIM.

    Nao e filtro rigido de proposito: quem ganhar livro publicado depois sobe
    sozinho, sem precisar de nenhum backfill.
    """
    conn = _banco()
    tmp = tempfile.mkdtemp()
    batch_dir_original = orch.BATCH_DIR
    try:
        from pathlib import Path
        orch.BATCH_DIR = Path(tmp)
        orch._export_author_bio(conn, limite=4)
        arq = [f for f in os.listdir(tmp) if f.endswith("_author_bio_input.json")][0]
        with open(os.path.join(tmp, arq), encoding="utf-8") as f:
            nomes = [a["nome"] for a in json.load(f)["autores"]]
        assert nomes == ["Zafon, Carlos Ruiz", "Nabokov, Vladimir",
                         "Abreu, Beltrano", "Mendes, Fulano"], nomes
        print("[OK] paginas 404 afundam para o fim, com desempate alfabetico")
    finally:
        orch.BATCH_DIR = batch_dir_original
        conn.close()


def test_cota_padrao_enche_o_lote():
    """BIO_POR_CICLO deixou de recortar abaixo de BATCH_SIZE_AUTHOR_BIO.

    O slot secundario custa 1 chamada com 10 ou com 25 autores, entao a cota
    menor desperdicava 60% do lote sem economizar quota nenhuma.
    """
    assert orch.BIO_POR_CICLO == orch.BATCH_SIZE_AUTHOR_BIO, (
        orch.BIO_POR_CICLO, orch.BATCH_SIZE_AUTHOR_BIO)
    print("[OK] BIO_POR_CICLO == BATCH_SIZE_AUTHOR_BIO (lote cheio)")


if __name__ == "__main__":
    test_conta_so_quem_tem_pagina()
    test_export_ordena_por_livros_publicados()
    test_paginas_404_afundam_mas_nao_somem()
    test_cota_padrao_enche_o_lote()
    print("\nTodos os testes passaram.")
