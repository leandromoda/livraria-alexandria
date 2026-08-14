"""Republicação seletiva de ofertas (steps/publish_ofertas.run_repair).

Fixa a correção medida no pipeline_2026-08-12_19-03-07 (35h27): o repair
reenviava o catálogo inteiro a cada passe — 4.789 ofertas distintas, 9.630
publicações, 52,6% de todas as linhas do log — para propagar os ~50 preços que
o offer_price_monitor coleta por ciclo.

Convenção do projeto: assert puro, sem pytest. `publish_ofertas` importa
requests e dotenv; stub em sys.modules antes do import, só quando o real está
ausente (mesma técnica de tests/test_backfill_idioma.py).
"""

import sqlite3
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


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


_stub("requests", get=_boom, post=_boom,
      exceptions=types.SimpleNamespace(RequestException=Exception))
_stub("dotenv", load_dotenv=lambda *a, **k: None)

from steps import publish_ofertas as po  # noqa: E402


# ── 1. O hash cobre os campos mutáveis do payload ───────────────────────────
h = po._payload_hash("amazon", "https://x/p?tag=a", 49.9)
assert h == po._payload_hash("amazon", "https://x/p?tag=a", 49.9), "hash instável"
assert h != po._payload_hash("amazon", "https://x/p?tag=a", 59.9), "preço deve mudar o hash"
assert h != po._payload_hash("amazon", "https://y/p?tag=a", 49.9), "URL deve mudar o hash"
assert h != po._payload_hash("mercado_livre", "https://x/p?tag=a", 49.9), "marketplace idem"

# ── 2. Ruído de ponto flutuante NÃO é mudança de preço ──────────────────────
# REAL no SQLite vs NUMERIC no Supabase: sem o arredondamento a 2 casas, a 12ª
# casa decimal republicaria o catálogo para sempre.
assert po._payload_hash("amazon", "u", 49.90) == po._payload_hash("amazon", "u", 49.900000000001)
assert po._payload_hash("amazon", "u", 49.90) != po._payload_hash("amazon", "u", 49.91)

# ── 3. preco None é estável (não vira "None" vs "") ─────────────────────────
assert po._payload_hash("amazon", "u", None) == po._payload_hash("amazon", "u", None)
assert po._payload_hash("amazon", "u", None) != po._payload_hash("amazon", "u", 0.0)


# ── 4. run_repair marca SÓ o que mudou ──────────────────────────────────────
def _db(linhas):
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE livros (
            id TEXT PRIMARY KEY, titulo TEXT, supabase_id TEXT,
            marketplace TEXT, offer_url TEXT, preco REAL, preco_atual REAL,
            offer_status TEXT, status_publish INTEGER,
            status_publish_oferta INTEGER, oferta_payload_hash TEXT,
            updated_at TEXT
        )""")
    conn.executemany(
        "INSERT INTO livros (id,titulo,supabase_id,marketplace,offer_url,"
        "preco_atual,offer_status,status_publish,status_publish_oferta,"
        "oferta_payload_hash) VALUES (?,?,?,?,?,?,?,?,?,?)", linhas)
    conn.commit()
    return conn


class _ConnAberta:
    """Proxy que ignora close(): run_repair fecha, o teste ainda precisa ler.

    sqlite3.Connection.close é read-only, então não dá para monkeypatch direto.
    """

    def __init__(self, conn):
        self._conn = conn

    def close(self):
        pass

    def __getattr__(self, nome):
        return getattr(self._conn, nome)


def _rodar_repair(conn):
    """Executa run_repair contra um banco em memória, sem rede."""
    chamou_run = []
    orig_get, orig_fix, orig_run = po.get_conn, po.fix_offer_status, po.run
    po.get_conn = lambda: _ConnAberta(conn)
    po.fix_offer_status = lambda c=None: None
    po.run = lambda pacote=200: chamou_run.append(pacote)
    try:
        po.run_repair()
    finally:
        po.get_conn, po.fix_offer_status, po.run = orig_get, orig_fix, orig_run
    return chamou_run


def _hash_de(marketplace, url, preco):
    return po._payload_hash(marketplace, po._offer_url_final(url), preco)


URL = "https://www.amazon.com.br/dp/X"
# a: hash bate (inalterada) | b: preço mudou | c: nunca publicada (hash NULL)
conn = _db([
    ("a", "A", "sa", "amazon", URL, 10.0, "1", 1, 1, _hash_de("amazon", URL, 10.0)),
    ("b", "B", "sb", "amazon", URL, 99.0, "1", 1, 1, _hash_de("amazon", URL, 10.0)),
    ("c", "C", "sc", "amazon", URL, 10.0, "1", 1, 1, None),
])
chamou = _rodar_repair(conn)

pend = dict(conn.execute(
    "SELECT id, status_publish_oferta FROM livros").fetchall())
assert pend["a"] == 1, "oferta inalterada NÃO pode ser remarcada para republicar"
assert pend["b"] == 0, "preço mudou → tem de republicar"
assert pend["c"] == 0, "sem hash (nunca publicada) → tem de republicar"
assert chamou == [200], f"run() devia ser chamado uma vez: {chamou}"

# ── 5. Catálogo estável não gera NENHUMA republicação nem chama run() ───────
# É o caso dominante em produção e o que gerava as 9.630 linhas.
conn = _db([
    (f"i{n}", f"T{n}", f"s{n}", "amazon", URL, 10.0, "1", 1, 1,
     _hash_de("amazon", URL, 10.0))
    for n in range(50)
])
chamou = _rodar_repair(conn)
zerados = conn.execute(
    "SELECT COUNT(*) FROM livros WHERE status_publish_oferta = 0").fetchone()[0]
assert zerados == 0, f"catálogo estável remarcou {zerados} ofertas"
assert chamou == [], "sem mudanças, run() nem deve ser chamado (zero HTTP)"

# ── 6. updated_at intacto para quem não mudou ───────────────────────────────
# A versão anterior fazia UPDATE ... SET updated_at = CURRENT_TIMESTAMP em
# TODOS os elegíveis, destruindo o único sinal de "quando esta linha mudou".
conn = _db([("a", "A", "sa", "amazon", URL, 10.0, "1", 1, 1,
             _hash_de("amazon", URL, 10.0))])
conn.execute("UPDATE livros SET updated_at = '2020-01-01' WHERE id='a'")
conn.commit()
_rodar_repair(conn)
assert conn.execute("SELECT updated_at FROM livros WHERE id='a'").fetchone()[0] == "2020-01-01"

print("test_publish_ofertas_repair OK")
