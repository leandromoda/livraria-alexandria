"""
Testes da reingestao de seed (assert puro, sem pytest, sem rede).

    PYTHONPATH=. python tests/test_seed_reingestao.py

Ate 2026-08-30 reingerir um seed era INOCUO: `insert_seed` devolvia
("duplicate", None) e o modulo e INSERT puro — nao existe um unico
`UPDATE livros` nele. Medido: dos 4 arquivos em ingested_seeds/, 23 de 24
seeds caiam como duplicata e nao produziam efeito nenhum.

Agora o seed repetido RELIGA a oferta do livro que ele descreve, via
migrar_ofertas_ml (que so troca com confirmacao da API do ML). Estes testes
fixam o que muda e, sobretudo, o que NAO pode mudar.
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
        raise AssertionError("requests chamado — deveria ter stub")

    m.get = m.post = boom
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

from steps import offer_seed as osd  # noqa: E402

BUSCA_AMZ = "https://www.amazon.com.br/s?k=dom+casmurro&tag=livrariaalexa-20"


class _ConnAberta(sqlite3.Connection):
    """`close()` no-op — o step fecha, o teste ainda precisa ler."""

    def close(self):
        pass


def _db():
    """Banco com o schema canonico do proprio offer_seed (nao um DDL paralelo)."""
    d = tempfile.mkdtemp()
    conn = sqlite3.connect(os.path.join(d, "books.db"), factory=_ConnAberta)
    conn.row_factory = sqlite3.Row
    osd.ensure_tables(conn)
    for col in ("blacklist_reason TEXT", "qa_quarantine INTEGER DEFAULT 0",
                "ml_migracao_em TEXT"):
        try:
            conn.execute(f"ALTER TABLE livros ADD COLUMN {col}")
        except Exception:
            pass
    conn.commit()
    return conn


def _seed_file(seeds):
    d = tempfile.mkdtemp()
    p = os.path.join(d, "001_offer_seeds.json")
    import json
    with open(p, "w", encoding="utf-8") as f:
        json.dump(seeds, f, ensure_ascii=False)
    return p


def _existente(conn, titulo, autor, offer_url=BUSCA_AMZ, **extra):
    campos = {"id": "L1", "titulo": titulo, "autor": autor,
              "offer_url": offer_url, "marketplace": "amazon",
              "status_publish": 1, "created_at": "x", "updated_at": "x"}
    campos.update(extra)
    cols = ", ".join(campos)
    ph = ", ".join("?" * len(campos))
    conn.execute(f"INSERT INTO livros ({cols}) VALUES ({ph})", tuple(campos.values()))
    conn.commit()


def _com_api(resposta):
    """Instala stubs de core.ml_api e steps.offer_resolver; devolve o desfazer."""
    api = types.ModuleType("core.ml_api")
    api.configurado = lambda: True
    api.buscar_livro = resposta
    res = types.ModuleType("steps.offer_resolver")
    res.inject_ml_affiliate = lambda u: u + "?matt_tool=TESTE"
    salvos = {k: sys.modules.get(k) for k in ("core.ml_api", "steps.offer_resolver")}
    sys.modules["core.ml_api"] = api
    sys.modules["steps.offer_resolver"] = res

    def desfazer():
        for k, v in salvos.items():
            if v is not None:
                sys.modules[k] = v
            else:
                sys.modules.pop(k, None)

    return desfazer


ACHOU = lambda *_a, **_k: {"produto_id": "MLB9", "preco": 31.5,  # noqa: E731
                           "url": "https://www.mercadolivre.com.br/p/MLB9"}
NAO_ACHOU = lambda *_a, **_k: None  # noqa: E731


def _row(conn):
    return conn.execute("SELECT * FROM livros WHERE id = 'L1'").fetchone()


SEED = [{"titulo": "Dom Casmurro", "autor": "Machado de Assis",
         "lookup_query": "Dom Casmurro Machado livro", "marketplace": "amazon"}]


# ---------------------------------------------------------------------------

def test_duplicata_devolve_o_id_existente():
    """Era ("duplicate", None) — e por isso o seed nao produzia efeito."""
    conn = _db()
    _existente(conn, "Dom Casmurro", "Machado de Assis")
    result, book_id = osd.insert_seed(conn, SEED[0], seed_id="001")
    assert result == "duplicate", result
    assert book_id == "L1", f"esperava o id do livro existente, veio {book_id!r}"
    print("OK  duplicata devolve o id do livro que ja existe")


def test_reingestao_religa_ao_ml_quando_a_api_confirma():
    conn = _db()
    _existente(conn, "Dom Casmurro", "Machado de Assis")
    desfazer = _com_api(ACHOU)
    try:
        ins, skip, ids = osd.process_file(conn, "001_offer_seeds.json",
                                          _seed_file(SEED))
    finally:
        desfazer()
    r = _row(conn)
    assert (ins, skip) == (0, 1), (ins, skip)
    assert ids == [], "duplicata NAO pode entrar em inserted_ids"
    assert "mercadolivre.com.br/p/MLB9" in r["offer_url"], r["offer_url"]
    assert "matt_tool" in r["offer_url"]
    assert r["marketplace"] == "mercado_livre"
    assert r["preco_atual"] == 31.5
    assert r["status_publish_oferta"] == 0, "precisa reabrir p/ o run_repair"
    print("OK  reingestao religa ao ML e reabre a republicacao")


def test_reingestao_nao_toca_quando_a_api_nao_confirma():
    conn = _db()
    _existente(conn, "Dom Casmurro", "Machado de Assis",
               preco_atual=88.0, status_publish_oferta=1)
    desfazer = _com_api(NAO_ACHOU)
    try:
        osd.process_file(conn, "001_offer_seeds.json", _seed_file(SEED))
    finally:
        desfazer()
    r = _row(conn)
    assert r["offer_url"] == BUSCA_AMZ, "URL nao muda sem confirmacao"
    assert r["marketplace"] == "amazon"
    assert r["preco_atual"] == 88.0, "preco da Amazon nao vai para URL do ML"
    assert r["status_publish_oferta"] == 1
    print("OK  sem confirmacao da API, a reingestao nao altera a oferta")


def test_reingestao_nao_mexe_em_flag_de_publicacao():
    """O Quality Gate ja reavalia todo status_publish=0. Resetar aqui seria
    redundante — e resetar is_publishable republicaria despublicado de proposito."""
    conn = _db()
    _existente(conn, "Dom Casmurro", "Machado de Assis",
               status_publish=0, is_publishable=0)
    desfazer = _com_api(ACHOU)
    try:
        osd.process_file(conn, "001_offer_seeds.json", _seed_file(SEED))
    finally:
        desfazer()
    r = _row(conn)
    assert r["status_publish"] == 0, "reingestao nao publica por conta propria"
    assert r["is_publishable"] == 0, "nao pode reabrir despublicacao deliberada"
    print("OK  reingestao nao mexe em status_publish nem is_publishable")


def test_seed_novo_continua_inserindo():
    """Guarda o caminho feliz: o comportamento novo nao pode quebrar o antigo."""
    conn = _db()
    desfazer = _com_api(ACHOU)
    try:
        ins, skip, ids = osd.process_file(conn, "001_offer_seeds.json",
                                          _seed_file(SEED))
    finally:
        desfazer()
    assert (ins, skip) == (1, 0), (ins, skip)
    assert len(ids) == 1, ids
    n = conn.execute("SELECT COUNT(*) FROM livros").fetchone()[0]
    assert n == 1, n
    print("OK  seed novo continua sendo inserido normalmente")


def test_falha_na_religacao_nao_derruba_a_ingestao():
    conn = _db()
    _existente(conn, "Dom Casmurro", "Machado de Assis")

    def explode(*_a, **_k):
        raise RuntimeError("API fora")

    desfazer = _com_api(explode)
    try:
        ins, skip, _ids = osd.process_file(conn, "001_offer_seeds.json",
                                           _seed_file(SEED))
    finally:
        desfazer()
    assert (ins, skip) == (0, 1), (ins, skip)
    assert _row(conn)["offer_url"] == BUSCA_AMZ
    print("OK  falha na religacao nao derruba a ingestao do seed")


if __name__ == "__main__":
    test_duplicata_devolve_o_id_existente()
    test_reingestao_religa_ao_ml_quando_a_api_confirma()
    test_reingestao_nao_toca_quando_a_api_nao_confirma()
    test_reingestao_nao_mexe_em_flag_de_publicacao()
    test_seed_novo_continua_inserindo()
    test_falha_na_religacao_nao_derruba_a_ingestao()
    print("\nTodos os testes passaram.")
