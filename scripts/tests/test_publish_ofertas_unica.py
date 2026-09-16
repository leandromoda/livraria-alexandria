"""Uma oferta ativa por livro (steps/publish_ofertas.desativar_outras).

O upsert é por (livro_id, marketplace). Trocar o marketplace de um livro
inseria linha nova e deixava a antiga ativa: medido no Supabase em 2026-09-16,
570 livros publicáveis com mais de uma oferta ativa, 500 deles com a busca da
Amazon sem preço ao lado do deep link do ML com preço.

Assert puro, sem rede: `requests.post`/`patch` trocados no módulo.

    PYTHONPATH=. python tests/test_publish_ofertas_unica.py
"""

import os
import sqlite3
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def _stub(nome, **attrs):
    try:
        __import__(nome)
        return
    except ImportError:
        pass
    mod = types.ModuleType(nome)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[nome] = mod


def _boom(*a, **k):
    raise AssertionError("saída de rede não esperada no teste")


_stub("requests", get=_boom, post=_boom, patch=_boom,
      exceptions=types.SimpleNamespace(RequestException=Exception))
_stub("dotenv", load_dotenv=lambda *a, **k: None)

from steps import publish_ofertas as po  # noqa: E402

po.time.sleep = lambda s: None


class _Res:
    def __init__(self, code):
        self.status_code, self.text = code, ""


class _ConnAberta:
    def __init__(self, conn):
        self._conn = conn

    def close(self):
        pass

    def __getattr__(self, nome):
        return getattr(self._conn, nome)


def _db():
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE livros (
            id TEXT PRIMARY KEY, titulo TEXT, supabase_id TEXT,
            marketplace TEXT, offer_url TEXT, preco REAL, preco_atual REAL,
            offer_status TEXT, status_publish INTEGER,
            status_publish_oferta INTEGER, oferta_payload_hash TEXT,
            updated_at TEXT)""")
    conn.execute(
        "INSERT INTO livros (id,titulo,supabase_id,marketplace,offer_url,preco_atual,"
        "offer_status,status_publish,status_publish_oferta) VALUES "
        "('a','A','sb-1','mercado_livre','https://www.mercadolivre.com.br/p/MLB1',"
        "24.9,'1',1,0)")
    conn.commit()
    return conn


def _rodar(post_code=201, patch_codes=(204,)):
    chamadas = []
    codes = list(patch_codes)

    def _post(url, headers=None, json=None, timeout=None):
        chamadas.append(("POST", url, json))
        return _Res(post_code)

    def _patch(url, headers=None, json=None, timeout=None):
        chamadas.append(("PATCH", url, json, headers.get("Prefer")))
        return _Res(codes.pop(0) if codes else 204)

    conn = _db()
    orig = po.get_conn, po.requests.post, getattr(po.requests, "patch", None)
    po.get_conn = lambda: _ConnAberta(conn)
    po.requests.post, po.requests.patch = _post, _patch
    os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://sb.test")
    os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "k")
    try:
        po.run(10)
    finally:
        po.get_conn, po.requests.post, po.requests.patch = orig
    return conn, chamadas


# ── 1. Publicar desativa as ofertas de OUTRO marketplace do mesmo livro ─────
conn, ch = _rodar()
assert [c[0] for c in ch] == ["POST", "PATCH"], ch
_, url, corpo, prefer = ch[1]
assert "livro_id=eq.sb-1" in url, url
assert "marketplace=neq.mercado_livre" in url, url
assert "ativa=eq.true" in url, url
assert corpo == {"ativa": False}, "desativa, nunca apaga (oferta_clicks aponta p/ as linhas)"
assert "resolution" not in (prefer or ""), prefer
assert conn.execute("SELECT status_publish_oferta FROM livros").fetchone()[0] == 1
print("[OK] publicar desativa a oferta antiga de outro marketplace")

# ── 2. Upsert falhou → não desativa nada (o livro não fica sem oferta) ──────
conn, ch = _rodar(post_code=500)
assert all(c[0] == "POST" for c in ch), ch
assert conn.execute("SELECT status_publish_oferta FROM livros").fetchone()[0] == 0
print("[OK] upsert falho não desativa a oferta existente")

# ── 3. Desativação falhou → não marca publicado, o próximo passe refaz ──────
conn, ch = _rodar(patch_codes=(500, 500, 500))
assert conn.execute("SELECT status_publish_oferta FROM livros").fetchone()[0] == 0, \
    "sem desativar, marcar publicado deixaria a duplicata para sempre"
print("[OK] falha ao desativar mantém a oferta pendente")

# ── 4. Sem marketplace local não afirma nada ────────────────────────────────
assert po.desativar_outras("https://sb.test", {}, "sb-1", None) is True
assert po.desativar_outras("https://sb.test", {}, None, "amazon") is True
print("[OK] sem marketplace/livro_id não dispara PATCH")

print("\nTodos os testes passaram.")
