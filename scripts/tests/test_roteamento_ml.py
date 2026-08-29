"""Roteamento sempre para o ML, na resolucao do seed e no resgate.

Duas mudancas estruturais de 2026-08-29:

1. `offer_resolver.resolve_offer` para de obedecer o campo `marketplace` do
   seed. A distribuicao mostrava que aquilo era quase moeda ao ar (8.798
   'amazon' contra 8.778 'mercado_livre'), mas os dois lados NAO sao
   equivalentes: o ML tem API oficial (preco, deep link, ~1-2 s, 37% de
   casamento) e a Amazon nao tem API acessivel (scraping sob bot wall,
   ~13,7 s, ~0% de preco). Livro roteado para a Amazon vira beco sem saida.

2. `offer_price_monitor` tenta o ML ANTES de despublicar. "Sumiu da Amazon"
   nao e "sumiu do mundo", e despublicar-para-republicar-depois deixaria a
   pagina fora do ar no intervalo — o que nao se faz num site sob rebaixamento.

    PYTHONPATH=. python tests/test_roteamento_ml.py
"""

import os
import sqlite3
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

for _n, _a in (("requests", {"get": lambda *a, **k: None, "patch": lambda *a, **k: None}),
               ("dotenv", {"load_dotenv": lambda *a, **k: None})):
    try:
        __import__(_n)
    except ModuleNotFoundError:  # pragma: no cover — so no CI
        _m = types.ModuleType(_n)
        for _k, _v in _a.items():
            setattr(_m, _k, _v)
        _m.exceptions = types.SimpleNamespace(
            RequestException=Exception,
            ReadTimeout=type("ReadTimeout", (Exception,), {}))
        _m.utils = types.SimpleNamespace(quote=lambda s, safe="/": s)
        sys.modules[_n] = _m

from core import ml_api                        # noqa: E402
from steps import offer_resolver as res        # noqa: E402
from steps import offer_price_monitor as opm   # noqa: E402


def _com_api(achado):
    """Troca a API do ML por um stub. Devolve a funcao para restaurar."""
    orig_cfg, orig_busca = ml_api.configurado, ml_api.buscar_livro
    ml_api.configurado = lambda: True
    ml_api.buscar_livro = lambda t, a=None, i=None: achado

    def restaurar():
        ml_api.configurado, ml_api.buscar_livro = orig_cfg, orig_busca
    return restaurar


ACHADO = {"produto_id": "MLB20090573", "preco": 24.9,
          "url": "https://www.mercadolivre.com.br/p/MLB20090573",
          "titulo_ml": "Dom Casmurro", "autor_ml": "Machado de Assis",
          "gtin": None, "n_anuncios": 3, "via": "titulo"}


# ── 1. Seed diz 'amazon' — o ML ganha assim mesmo ───────────────────────────
r = _com_api(ACHADO)
try:
    url, preco, mkt = res.resolve_offer("amazon", "dom casmurro livro",
                                        titulo="Dom Casmurro", autor="Machado de Assis")
finally:
    r()
assert mkt == "mercado_livre", mkt
assert "/p/MLB20090573" in url, url
assert preco == 24.9, preco
assert "matt_tool" in url, "faltou a tag de afiliado do ML"
print("[OK] seed 'amazon' e sobrescrito: vai para o ML, com deep link e preco")


# ── 2. API nao confirma -> URL de BUSCA do ML, nunca Amazon ─────────────────
r = _com_api(None)
try:
    url, preco, mkt = res.resolve_offer("amazon", "livro inexistente 999",
                                        titulo="Livro Inexistente 999")
finally:
    r()
assert mkt == "mercado_livre", mkt
assert "lista.mercadolivre.com.br" in url, url
assert "amazon" not in url, url
assert preco is None
print("[OK] sem confirmacao da API, cai na busca do ML — nao na Amazon")


# ── 3. FORCAR_ML=0 volta a obedecer o seed ─────────────────────────────────
res.FORCAR_ML = False
try:
    url, _p, mkt = res.resolve_offer("amazon", "dom casmurro livro",
                                     titulo="Dom Casmurro")
    assert mkt == "amazon" and "amazon.com.br" in url, (mkt, url)
    # E o 'Amazon' com maiuscula, que antes caia em None, agora casa.
    url2, _p2, mkt2 = res.resolve_offer("Amazon", "dom casmurro livro")
    assert mkt2 == "amazon", (mkt2, url2)
finally:
    res.FORCAR_ML = True
print("[OK] FORCAR_ML=0 obedece o seed, e 'Amazon' maiusculo deixou de falhar")


# ── 4. Sem lookup_query, nao inventa oferta ────────────────────────────────
assert res.resolve_offer("amazon", None, titulo="X") == (None, None, None)
print("[OK] sem lookup_query devolve (None, None, None)")


# ── 5. RESGATE: indisponivel na origem, achado no ML -> segue publicado ────
DDL = """CREATE TABLE livros (
    id TEXT PRIMARY KEY, titulo TEXT, autor TEXT, isbn TEXT, offer_url TEXT,
    marketplace TEXT, preco_atual REAL, preco_updated_at TEXT,
    offer_status TEXT, is_publishable INTEGER, status_publish INTEGER,
    updated_at TEXT);"""
conn = sqlite3.connect(":memory:")
conn.row_factory = sqlite3.Row
conn.executescript(DDL)
conn.execute("INSERT INTO livros VALUES ('x','Dom Casmurro','Machado de Assis',"
             "NULL,'https://www.amazon.com.br/dp/ABC','amazon',NULL,NULL,'1',1,1,NULL)")
conn.commit()

_patches = []
opm.supabase_patch = lambda sid, p: _patches.append(("livros", p)) or True
opm.supabase_patch_oferta = lambda sid, p: _patches.append(("ofertas", p)) or True

r = _com_api(ACHADO)
try:
    out = opm._resgatar_no_ml(conn, "x", "Dom Casmurro", "Machado de Assis",
                              None, "sb-1", dry_run=False)
finally:
    r()

assert out is not None, "deveria ter resgatado"
row = conn.execute("SELECT * FROM livros WHERE id='x'").fetchone()
assert "/p/MLB20090573" in row["offer_url"], row["offer_url"]
assert row["marketplace"] == "mercado_livre", row["marketplace"]
assert row["preco_atual"] == 24.9, row["preco_atual"]
assert row["status_publish"] == 1, "o livro NAO pode sair do ar durante o resgate"
assert row["is_publishable"] == 1
assert ("livros", {"is_publishable": True, "offer_status": "active"}) in _patches
print("[OK] resgate troca a oferta para o ML e mantem o livro publicado")


# ── 6. Sem achado no ML, o resgate nao mente ───────────────────────────────
r = _com_api(None)
try:
    assert opm._resgatar_no_ml(conn, "x", "T", "A", None, "sb-1", False) is None
finally:
    r()
# E achado SEM preco tambem nao serve: oferta sem preco e o problema, nao a solucao.
r = _com_api({**ACHADO, "preco": None})
try:
    assert opm._resgatar_no_ml(conn, "x", "T", "A", None, "sb-1", False) is None
finally:
    r()
print("[OK] sem achado, ou achado sem preco, o resgate devolve None")

print("\nTodos os testes passaram.")
