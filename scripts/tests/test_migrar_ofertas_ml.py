"""
Testes da migracao Amazon -> ML (assert puro, sem pytest, sem rede).

    PYTHONPATH=. python tests/test_migrar_ofertas_ml.py

O step so migra quando a API do ML CONFIRMA o produto. O registro anterior
(TASK-OFERTAS-007) dizia que trocar busca da Amazon por busca do ML seria
"neutro" — nao e, e estes testes fixam os dois motivos:

  1. livro fora do catalogo do ML trocaria uma busca que acha por uma vazia;
  2. `offer_resolver.update_offer` faz `preco_atual = COALESCE(?, preco_atual)`,
     entao sem confirmacao o preco da AMAZON sobreviveria colado numa URL do ML.

E fixam o anti-laco: livro nao confirmado vai para o FIM da fila (carimbo em
`ml_migracao_em`), em vez de ser reconsultado a cada passe — que foi o defeito
corrigido no #307 na categorizacao.
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
        raise AssertionError("requests chamado — o teste deveria ter feito stub")

    m.get = m.post = boom
    m.Session = lambda *_a, **_k: types.SimpleNamespace(get=boom, post=boom)
    return m


def _bs4():
    m = types.ModuleType("bs4")
    m.BeautifulSoup = type("BeautifulSoup", (), {"__init__": lambda self, *a, **k: None})
    return m


def _dotenv():
    m = types.ModuleType("dotenv")
    m.load_dotenv = lambda *_a, **_k: False
    m.find_dotenv = lambda *_a, **_k: ""
    return m


_stub("requests", _requests)
_stub("bs4", _bs4)
_stub("dotenv", _dotenv)

from steps import migrar_ofertas_ml as mig  # noqa: E402

DDL = """
CREATE TABLE livros (
    id                    TEXT PRIMARY KEY,
    titulo                TEXT,
    autor                 TEXT,
    isbn                  TEXT,
    offer_url             TEXT,
    marketplace           TEXT,
    preco_atual           REAL,
    preco_updated_at      TEXT,
    offer_status          TEXT,
    status_publish        INTEGER DEFAULT 1,
    status_publish_oferta INTEGER DEFAULT 1,
    supabase_id           TEXT,
    ml_migracao_em        TEXT,
    updated_at            TEXT
);
"""

BUSCA_AMZ = "https://www.amazon.com.br/s?k=dom+casmurro&tag=livrariaalexa-20"
DP_AMZ = "https://www.amazon.com.br/dp/8535914846?tag=livrariaalexa-20"


class _ConnAberta(sqlite3.Connection):
    """`close()` vira no-op: o step fecha a conexao no fim e o teste ainda
    precisa ler o estado. `sqlite3.Connection.close` e read-only, entao a
    troca tem de ser por subclasse, nao por monkeypatch no objeto."""

    def close(self):
        pass


def _db(livros):
    conn = sqlite3.connect(os.path.join(tempfile.mkdtemp(), "t.db"),
                           factory=_ConnAberta)
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    for l in livros:
        cols = ", ".join(l.keys())
        ph = ", ".join("?" * len(l))
        conn.execute(f"INSERT INTO livros ({cols}) VALUES ({ph})", tuple(l.values()))
    conn.commit()
    return conn


def _rodar(conn, resposta, dry_run=False, limit=50):
    """Roda mig.run com get_conn e ml_api trocados por stubs."""
    fake_api = types.ModuleType("core.ml_api")
    fake_api.configurado = lambda: True
    fake_api.buscar_livro = resposta
    salvo = sys.modules.get("core.ml_api")
    sys.modules["core.ml_api"] = fake_api

    fake_res = types.ModuleType("steps.offer_resolver")
    fake_res.inject_ml_affiliate = lambda u: u + "?matt_tool=TESTE"
    salvo_res = sys.modules.get("steps.offer_resolver")
    sys.modules["steps.offer_resolver"] = fake_res

    orig_conn, mig.get_conn = mig.get_conn, lambda: conn
    try:
        return mig.run(limit=limit, dry_run=dry_run)
    finally:
        mig.get_conn = orig_conn
        if salvo is not None:
            sys.modules["core.ml_api"] = salvo
        else:
            sys.modules.pop("core.ml_api", None)
        if salvo_res is not None:
            sys.modules["steps.offer_resolver"] = salvo_res
        else:
            sys.modules.pop("steps.offer_resolver", None)


ACHOU = lambda *_a, **_k: {  # noqa: E731
    "produto_id": "MLB123",
    "preco": 39.9,
    "url": "https://www.mercadolivre.com.br/p/MLB123",
}
NAO_ACHOU = lambda *_a, **_k: None  # noqa: E731


def _row(conn, lid):
    return conn.execute("SELECT * FROM livros WHERE id = ?", (lid,)).fetchone()


# ---------------------------------------------------------------------------

def test_oferta_boa_da_amazon_nao_entra_na_fila():
    """Deep link /dp/ + preco = oferta que funciona. Trocar seria regressao."""
    conn = _db([
        {"id": "boa", "titulo": "Livro Bom", "offer_url": DP_AMZ, "preco_atual": 42.0},
        {"id": "magra", "titulo": "Livro Magro", "offer_url": BUSCA_AMZ},
    ])
    ids = [r["id"] for r in mig.fetch_pending(conn, 50)]
    assert "boa" not in ids, "livro com deep link E preco nao pode ser migrado"
    assert "magra" in ids, ids
    print("OK  deep link /dp/ + preco fica de fora da fila")


def test_dp_sem_preco_entra():
    """Só a combinação dos dois protege — deep link sozinho nao e oferta boa."""
    conn = _db([{"id": "x", "titulo": "T", "offer_url": DP_AMZ}])
    assert [r["id"] for r in mig.fetch_pending(conn, 50)] == ["x"]
    print("OK  deep link SEM preco continua elegivel")


def test_nao_confirmado_nao_toca_em_nada():
    """O risco 2: preco da Amazon nao pode sobreviver colado numa URL do ML."""
    conn = _db([{"id": "x", "titulo": "Sob a Roda", "autor": "Hesse",
                 "offer_url": BUSCA_AMZ, "marketplace": "amazon",
                 "preco_atual": 55.0, "status_publish_oferta": 1}])
    mig_, nao, err = _rodar(conn, NAO_ACHOU)
    r = _row(conn, "x")
    assert (mig_, nao, err) == (0, 1, 0), (mig_, nao, err)
    assert r["offer_url"] == BUSCA_AMZ, "URL nao pode mudar sem confirmacao"
    assert r["marketplace"] == "amazon", "marketplace nao pode virar ML"
    assert r["preco_atual"] == 55.0, "preco da Amazon preservado, e na Amazon"
    assert r["status_publish_oferta"] == 1, "nao republica o que nao mudou"
    assert r["ml_migracao_em"] is not None, "mas a tentativa e carimbada"
    print("OK  nao confirmado: nada muda, so carimba a tentativa")


def test_confirmado_migra_com_preco_e_reabre_republicacao():
    conn = _db([{"id": "x", "titulo": "Dom Casmurro", "autor": "Machado",
                 "offer_url": BUSCA_AMZ, "marketplace": "amazon",
                 "status_publish_oferta": 1}])
    mig_, nao, err = _rodar(conn, ACHOU)
    r = _row(conn, "x")
    assert (mig_, nao, err) == (1, 0, 0), (mig_, nao, err)
    assert "mercadolivre.com.br/p/MLB123" in r["offer_url"], r["offer_url"]
    assert "matt_tool" in r["offer_url"], "tag de afiliado tem de ser injetada"
    assert r["marketplace"] == "mercado_livre", r["marketplace"]
    assert r["preco_atual"] == 39.9, r["preco_atual"]
    assert r["preco_updated_at"] is not None
    assert r["status_publish_oferta"] == 0, "precisa reabrir p/ o run_repair"
    print("OK  confirmado: deep link + preco + republicacao reaberta")


def test_fila_poe_nunca_tentado_primeiro():
    """O anti-laco: sem isto, os nao confirmados voltariam a cada passe."""
    conn = _db([
        {"id": "velho", "titulo": "A", "offer_url": BUSCA_AMZ,
         "ml_migracao_em": "2026-08-01T00:00:00"},
        {"id": "novo", "titulo": "B", "offer_url": BUSCA_AMZ},
        {"id": "recente", "titulo": "C", "offer_url": BUSCA_AMZ,
         "ml_migracao_em": "2026-08-30T00:00:00"},
    ])
    ids = [r["id"] for r in mig.fetch_pending(conn, 50)]
    assert ids == ["novo", "velho", "recente"], ids
    print("OK  fila: nunca-tentado, depois o carimbo mais antigo")


def test_erro_de_api_nao_carimba():
    """Falha de rede != livro avaliado. Carimbar mandaria ao fim da fila a toa."""
    def explode(*_a, **_k):
        raise RuntimeError("timeout")

    conn = _db([{"id": "x", "titulo": "T", "offer_url": BUSCA_AMZ}])
    mig_, nao, err = _rodar(conn, explode)
    assert (mig_, nao, err) == (0, 0, 1), (mig_, nao, err)
    assert _row(conn, "x")["ml_migracao_em"] is None, "erro de API nao carimba"
    print("OK  erro de API nao carimba (o livro segue no topo da fila)")


def test_dry_run_nao_escreve():
    conn = _db([{"id": "x", "titulo": "T", "offer_url": BUSCA_AMZ,
                 "marketplace": "amazon"}])
    mig_, _n, _e = _rodar(conn, ACHOU, dry_run=True)
    r = _row(conn, "x")
    assert mig_ == 1, "conta o que migraria"
    assert r["offer_url"] == BUSCA_AMZ and r["marketplace"] == "amazon"
    assert r["ml_migracao_em"] is None
    print("OK  dry-run conta mas nao grava")


def test_so_publicados():
    conn = _db([{"id": "x", "titulo": "T", "offer_url": BUSCA_AMZ,
                 "status_publish": 0}])
    assert mig.fetch_pending(conn, 50) == []
    print("OK  livro nao publicado fica fora")


if __name__ == "__main__":
    test_oferta_boa_da_amazon_nao_entra_na_fila()
    test_dp_sem_preco_entra()
    test_nao_confirmado_nao_toca_em_nada()
    test_confirmado_migra_com_preco_e_reabre_republicacao()
    test_fila_poe_nunca_tentado_primeiro()
    test_erro_de_api_nao_carimba()
    test_dry_run_nao_escreve()
    test_so_publicados()
    print("\nTodos os testes passaram.")
