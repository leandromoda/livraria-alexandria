"""fix_offer_status separa a fila real do step 3 de quem esta bloqueado a montante.

Fixa a correcao de 2026-08-26 (analise dos logs pipeline_2026-08-23_10-20-27 e
pipeline_2026-08-24_20-09-02): a mensagem dizia "N livros com offer_url vazia —
rodar step 3 primeiro" e o N ficava IMOVEL em 179 (14 ocorrencias num log, 43 no
outro) com o autopilot rodando o step 3 varias vezes no intervalo. Todos os 179
estavam com lookup_query NULL, e offer_resolver.fetch_pending filtra por ela —
o step 3 nunca poderia alcanca-los.

Convencao do projeto: assert puro, sem pytest. `publish_ofertas` importa requests
e dotenv; stub em sys.modules antes do import, so quando o real esta ausente.

    PYTHONPATH=. python tests/test_fix_offer_status_motivo.py
"""

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
    raise AssertionError("saida de rede nao esperada no teste")


_stub("requests", get=_boom, post=_boom,
      exceptions=types.SimpleNamespace(RequestException=Exception))
_stub("dotenv", load_dotenv=lambda *a, **k: None)

from steps import publish_ofertas as po  # noqa: E402


DDL = """
CREATE TABLE livros (
    id TEXT PRIMARY KEY, titulo TEXT, offer_url TEXT, lookup_query TEXT,
    offer_status TEXT, status_publish_oferta INTEGER, updated_at TEXT
);
"""


def _db(linhas):
    conn = sqlite3.connect(":memory:")
    conn.executescript(DDL)
    conn.executemany(
        "INSERT INTO livros (id, titulo, offer_url, lookup_query, offer_status,"
        " status_publish_oferta) VALUES (?,?,?,?,?,?)", linhas)
    conn.commit()
    return conn


def _capturar_log(monkey_alvo):
    """Troca po.log por um coletor e devolve a lista de linhas."""
    linhas = []
    original = monkey_alvo.log
    monkey_alvo.log = lambda m: linhas.append(m)
    return linhas, original


# ── 1. Os dois grupos sao contados separadamente ────────────────────────────
conn = _db([
    # bloqueado a montante: sem offer_url E sem lookup_query (o caso dos 179)
    ("b1", "The Journal of Political Economy", None, None, "active", 1),
    ("b2", "Catalogue of the Illinois State Library", None, "", "active", 1),
    # fila legitima do step 3: sem offer_url, mas COM lookup_query
    ("f1", "Dom Casmurro", None, "Dom Casmurro Machado de Assis livro", "active", 1),
    # ja resolvido: tem offer_url (entra no grupo com_url)
    ("r1", "A Metamorfose", "https://www.amazon.com.br/s?k=x", "A Metamorfose livro",
     "active", 1),
])

linhas, original = _capturar_log(po)
try:
    com_url, sem_url = po.fix_offer_status(conn)
finally:
    po.log = original

assert com_url == 1, f"esperado 1 normalizado com offer_url, veio {com_url}"
assert sem_url == 3, f"esperado 3 sem offer_url, veio {sem_url}"

texto = "\n".join(linhas)

# A mensagem enganosa nao pode voltar.
assert "rodar step 3 primeiro" not in texto, texto
# Fila real do step 3: 1 livro (f1).
assert "1 livros sem offer_url na fila do step 3" in texto, texto
# Bloqueados a montante: 2 livros (b1 com NULL, b2 com string vazia).
assert "2 livros sem offer_url E sem lookup_query" in texto, texto
assert "fora do alcance do step 3" in texto, texto
print("[OK] separa fila do step 3 de bloqueado por lookup_query ausente")


# ── 2. lookup_query vazia conta como ausente ────────────────────────────────
# O backfill grava TRIM(lookup_query) = '' como "nao preenchido"; a contagem
# tem de usar o mesmo criterio, senao um livro aparece como fila do step 3 e
# nunca sai de la.
conn = _db([("b", "Vazia", None, "   ", "active", 1)])
linhas, original = _capturar_log(po)
try:
    po.fix_offer_status(conn)
finally:
    po.log = original
texto = "\n".join(linhas)
assert "1 livros sem offer_url E sem lookup_query" in texto, texto
assert "na fila do step 3" not in texto, texto
print("[OK] lookup_query so com espacos conta como ausente")


# ── 3. Sem nenhum bloqueado, so a linha da fila do step 3 aparece ───────────
conn = _db([("f", "Dom Casmurro", None, "Dom Casmurro livro", "active", 1)])
linhas, original = _capturar_log(po)
try:
    po.fix_offer_status(conn)
finally:
    po.log = original
texto = "\n".join(linhas)
assert "1 livros sem offer_url na fila do step 3" in texto, texto
assert "sem lookup_query" not in texto, texto
print("[OK] nao imprime a linha de bloqueado quando nao ha nenhum")

print("\nTodos os testes passaram.")
