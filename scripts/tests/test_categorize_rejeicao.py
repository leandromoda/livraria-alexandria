"""
Testes da rejeicao de categorizacao (assert puro, sem pytest, sem rede).

    PYTHONPATH=. python tests/test_categorize_rejeicao.py

Fixa o invariante que o laco de 2026-08-27..29 violava: livro rejeitado pelo
agente NAO pode voltar para `status_categorize = 0`, porque
`categorize_export.fetch_pending` seleciona exatamente esse estado com um
`ORDER BY priority_score DESC, created_at ASC` deterministico — o mesmo livro
reencabeca a fila no lote seguinte, para sempre.

Medido nos 3 logs de 2026-08-27..29: 547 rejeicoes para 32 livros distintos,
nove deles 54 vezes cada, ~40% de cada lote de classify. Ver TASK-CLASSIFY-001.

Nao precisa de stub em `sys.modules`: a cadeia de import de
`steps/categorize_import.py` e `core/db.py` + `core/logger.py`, ambos so stdlib.
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

from steps import categorize_import as ci


# Espelha as colunas de `livros` que o caminho de rejeicao toca, mais o
# `is_publishable` que escolhe entre o estado 2 e o 4 (blacklist).
DDL = """
CREATE TABLE livros (
    id                  TEXT PRIMARY KEY,
    titulo              TEXT,
    autor               TEXT,
    is_publishable      INTEGER DEFAULT 1,
    status_categorize   INTEGER DEFAULT 0,
    categorize_attempts INTEGER DEFAULT 0,
    categorize_motivo   TEXT,
    created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at          TEXT
);
CREATE TABLE livros_categorias_tematicas (
    livro_id       TEXT,
    categoria_slug TEXT,
    confidence     REAL,
    primary_cat    INTEGER,
    created_at     TEXT,
    PRIMARY KEY (livro_id, categoria_slug)
);
"""

TAXONOMY = {"filosofia": {"slug": "filosofia"}, "historia": {"slug": "historia"}}


def _db(livros):
    """livros: lista de (id, titulo, is_publishable)."""
    conn = sqlite3.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    for lid, titulo, pub in livros:
        conn.execute(
            "INSERT INTO livros (id, titulo, autor, is_publishable) VALUES (?,?,?,?)",
            (lid, titulo, "Autor", pub),
        )
    conn.commit()
    return conn


def _output(resultados):
    path = os.path.join(tempfile.mkdtemp(), "001_categorize_output.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"resultados": resultados}, f)
    return path


def _estado(conn, lid):
    r = conn.execute(
        "SELECT status_categorize, categorize_attempts, categorize_motivo "
        "FROM livros WHERE id = ?",
        (lid,),
    ).fetchone()
    return r["status_categorize"], r["categorize_attempts"], r["categorize_motivo"]


def _rodar(conn, resultados):
    return ci._process_file(_output(resultados), TAXONOMY, conn, conn.cursor())


# ---------------------------------------------------------------------------

def test_rejeicao_com_motivo_sai_da_fila():
    """O caso do laco: rejeicao com motivo nao pode voltar para 0."""
    conn = _db([("l1", "How to Brew", 1)])
    ok, rej, _ja, _err = _rodar(conn, [{
        "id": "l1",
        "status": "REJECTED",
        "motivo": "taxonomia nao possui categoria para cervejaria caseira",
        "categorias": [],
    }])

    status, attempts, motivo = _estado(conn, "l1")
    assert (ok, rej) == (0, 1), (ok, rej)
    assert status == 2, f"esperava 2 (fora da fila), veio {status}"
    assert status != 0, "REGRESSAO: livro devolvido a fila — o laco voltou"
    assert attempts == 1, attempts
    assert "cervejaria" in (motivo or ""), motivo
    print("OK  rejeicao com motivo -> status 2, fora da fila")


def test_attempts_incrementa_a_cada_rejeicao():
    """`categorize_attempts` era lido por reset_failed e nunca escrito."""
    conn = _db([("l1", "Furniture Projects", 1)])
    item = {"id": "l1", "status": "REJECTED", "motivo": "sem categoria", "categorias": []}

    _rodar(conn, [item])
    # Segunda passada: simula o menu 10 devolvendo o livro a fila.
    conn.execute("UPDATE livros SET status_categorize = 0 WHERE id = 'l1'")
    conn.commit()
    _rodar(conn, [item])

    _status, attempts, _m = _estado(conn, "l1")
    assert attempts == 2, f"esperava 2 tentativas acumuladas, veio {attempts}"
    print("OK  categorize_attempts acumula (nao e mais letra morta)")


def test_rejeicao_sem_motivo_mantem_status():
    """Rejeicao sem motivo = falha transitoria do agente, nao veredito."""
    conn = _db([("l1", "Dom Casmurro", 1)])
    for motivo in (None, "", "  ", "none"):
        conn.execute("UPDATE livros SET status_categorize = 0, "
                     "categorize_attempts = 0 WHERE id = 'l1'")
        conn.commit()
        _rodar(conn, [{"id": "l1", "status": "REJECTED",
                       "motivo": motivo, "categorias": []}])
        status, attempts, _m = _estado(conn, "l1")
        assert status == 0, f"motivo={motivo!r}: esperava 0 (retry), veio {status}"
        assert attempts == 0, f"motivo={motivo!r}: nao devia contar tentativa"
    print("OK  rejeicao sem motivo mantem o livro na fila para retry")


def test_blacklistado_continua_indo_para_4():
    """`reprocess_blacklist` depende de status_categorize = 4."""
    conn = _db([("l1", "Livro banido", 0)])
    _rodar(conn, [{"id": "l1", "status": "REJECTED",
                   "motivo": "fora da taxonomia", "categorias": []}])
    status, _a, _m = _estado(conn, "l1")
    assert status == 4, f"blacklistado deve ir para 4, veio {status}"
    print("OK  livro blacklistado continua indo para 4")


def test_validacao_invalida_tambem_sai_da_fila():
    """Slug fora da taxonomia percorre o mesmo caminho."""
    conn = _db([("l1", "Livro qualquer", 1)])
    _rodar(conn, [{"id": "l1", "status": "CLASSIFIED",
                   "categorias": ["slug-que-nao-existe"]}])
    status, attempts, motivo = _estado(conn, "l1")
    assert status == 2, status
    assert attempts == 1, attempts
    assert "slug" in (motivo or "").lower(), motivo
    print("OK  rejeicao na validacao -> status 2, com motivo gravado")


def test_classificado_continua_funcionando():
    """Guarda o caminho feliz: o fix nao pode quebrar a classificacao."""
    conn = _db([("l1", "A Republica", 1)])
    ok, rej, _ja, _err = _rodar(conn, [{"id": "l1", "status": "CLASSIFIED",
                                        "categorias": ["filosofia", "historia"]}])
    status, attempts, _m = _estado(conn, "l1")
    linhas = conn.execute(
        "SELECT categoria_slug, primary_cat FROM livros_categorias_tematicas "
        "WHERE livro_id = 'l1' ORDER BY primary_cat DESC"
    ).fetchall()
    assert (ok, rej) == (1, 0), (ok, rej)
    assert status == 1, status
    assert attempts == 0, "livro classificado nao pode contar tentativa"
    assert [r["categoria_slug"] for r in linhas] == ["filosofia", "historia"]
    assert linhas[0]["primary_cat"] == 1
    print("OK  caminho feliz intacto (status 1 + categorias gravadas)")


if __name__ == "__main__":
    test_rejeicao_com_motivo_sai_da_fila()
    test_attempts_incrementa_a_cada_rejeicao()
    test_rejeicao_sem_motivo_mantem_status()
    test_blacklistado_continua_indo_para_4()
    test_validacao_invalida_tambem_sai_da_fila()
    test_classificado_continua_funcionando()
    print("\nTodos os testes passaram.")
