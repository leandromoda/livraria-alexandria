"""Testes de steps.isbn_backfill — a guarda de titulo e a escolha do candidato.

    PYTHONPATH=. python tests/test_isbn_backfill.py

O que este teste protege e uma falha SILENCIOSA e cara: aceitar o ISBN de uma
coletanea/box como se fosse o do livro. O identificador tem formato valido e
checksum correto, entao nada a jusante reclama — o site publica um ISBN que
aponta para outro produto. E a mesma classe de defeito do #289, so que pior,
porque parece certo.

Os dois casos de coletanea abaixo sao REAIS: sairam da amostra de 25 livros
publicados medida em 2026-08-21, na qual um limiar UNIdirecional de 0,6 os
aceitou. Por isso o modulo usa cobertura bidirecional.
"""

import os
import sys
import types

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

SCRIPTS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, SCRIPTS_ROOT)

# Mesmo tratamento de test_marketplace_scraper_ordem.py: o CI nao roda
# `pip install`, e tanto isbn_backfill quanto steps.publish fazem
# `import requests` no topo. Este teste nao faz rede — so precisa que o nome
# exista para o import passar. Onde `requests` existe (local), o import real
# continua sendo exercitado.
try:
    import requests  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover — so no CI
    _fake = types.ModuleType("requests")
    _fake.utils = types.SimpleNamespace(quote=lambda s, safe="/": s)

    def _boom(*_a, **_k):
        raise AssertionError("requests foi chamado — este teste nao faz rede")

    _fake.get = _boom
    _fake.patch = _boom
    _fake.post = _boom
    sys.modules["requests"] = _fake

from steps import isbn_backfill as ib


# ==========================================================
# similaridade_titulo — cobertura BIDIRECIONAL
# ==========================================================

assert ib.similaridade_titulo("O Nariz", "O Nariz") == 1.0
assert ib.similaridade_titulo("O cemitério de Praga", "O Cemitério de Praga") == 1.0
print("[OK] titulo identico (e acento/caixa) da 1.0")

# Caso real da amostra: "Don Segundo Sombra" -> "Dom Segundo Sombra".
# Erra uma palavra em tres, mas e o mesmo livro — tem de passar do limiar.
assert ib.similaridade_titulo("Don Segundo Sombra", "Dom Segundo Sombra") >= ib.LIMIAR_TITULO
print("[OK] variacao ortografica de uma palavra ainda passa")

# ---- os dois falso-aceitos que motivaram o criterio bidirecional ----

# Coletanea: o titulo do livro cabe INTEIRO no titulo do volume.
sim = ib.similaridade_titulo("Cinco Elegias", "Novos poemas, 1938, e Cinco elegias")
assert sim < ib.LIMIAR_TITULO, f"coletanea deveria reprovar, deu {sim:.2f}"
print("[OK] coletanea e reprovada (o livro cabe dentro do volume)")

# Box de 5 livros.
sim = ib.similaridade_titulo(
    "Beautiful Stranger",
    "The Beautiful Series, 5 Books Collection Set, Beautiful Stranger",
)
assert sim < ib.LIMIAR_TITULO, f"box deveria reprovar, deu {sim:.2f}"
print("[OK] box de varios livros e reprovado")

# Caso real de mismatch puro: "Kafka: Os Anos Decisivos" -> "Kafka".
sim = ib.similaridade_titulo("Kafka: Os Anos Decisivos", "Kafka")
assert sim < ib.LIMIAR_TITULO, f"mismatch deveria reprovar, deu {sim:.2f}"
print("[OK] titulo truncado e reprovado")

# Degenerados nao explodem nem passam.
for a, b in (("", "x"), ("x", ""), (None, "Livro"), ("Livro", None)):
    assert ib.similaridade_titulo(a, b) == 0.0
print("[OK] titulo vazio/None da 0.0")


# ==========================================================
# buscar_isbn — escolha do candidato
# ==========================================================

class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code, self.text = payload, status, ""

    def json(self):
        return self._payload


def _volume(titulo, identificadores):
    return {
        "volumeInfo": {
            "title": titulo,
            "industryIdentifiers": [
                {"type": "ISBN_13", "identifier": i} for i in identificadores
            ],
        }
    }


def _stub(payload, status=200):
    ib.requests = types.SimpleNamespace(get=lambda *a, **k: _Resp(payload, status))


# O melhor titulo NAO e o primeiro item: a funcao tem de varrer os candidatos.
_stub({"items": [
    _volume("Kafka", ["9788532305541"]),
    _volume("Kafka: Os Anos Decisivos", ["9781009395847"]),
]})
isbn, _ = ib.buscar_isbn("Kafka: Os Anos Decisivos", None, "k")
assert isbn == "9781009395847", isbn
print("[OK] escolhe o candidato de maior similaridade, nao o primeiro")

# Candidato sem ISBN valido e ignorado, mesmo com titulo perfeito.
_stub({"items": [
    _volume("O Nariz", ["nao-e-isbn"]),
    _volume("O Nariz", ["9786586490312"]),
]})
isbn, _ = ib.buscar_isbn("O Nariz", None, "k")
assert isbn == "9786586490312", isbn
print("[OK] candidato sem ISBN valido e ignorado")

# ISBN presente mas titulo divergente: NAO grava.
_stub({"items": [_volume("Outro Livro Totalmente Diferente", ["9786586490312"])]})
isbn, motivo = ib.buscar_isbn("O Nariz", None, "k")
assert isbn is None and "divergente" in motivo, (isbn, motivo)
print("[OK] titulo divergente nao vira ISBN gravado")

# Sem resultado.
_stub({"items": []})
assert ib.buscar_isbn("Livro Inexistente", None, "k")[0] is None
print("[OK] resposta sem itens nao quebra")

# 429 tem de virar QuotaEstourada — o loop depende disso para PARAR o lote em
# vez de contar o livro como "sem ISBN" e queimar o `isbn_checado_em` dele.
_stub({}, status=429)
try:
    ib.buscar_isbn("Qualquer", None, "k")
    raise AssertionError("429 deveria levantar QuotaEstourada")
except ib.QuotaEstourada:
    pass
print("[OK] HTTP 429 levanta QuotaEstourada")

# Erro de rede vira motivo, nao excecao — um livro nao derruba o lote.
ib.requests = types.SimpleNamespace(
    get=lambda *a, **k: (_ for _ in ()).throw(TimeoutError("boom"))
)
isbn, motivo = ib.buscar_isbn("Qualquer", None, "k")
assert isbn is None and "rede" in motivo, (isbn, motivo)
print("[OK] erro de rede nao derruba o lote")


print("\nTodos os testes passaram.")
