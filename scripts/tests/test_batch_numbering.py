"""Testes de core.batch_numbering — numeração e resolução de lotes.

Rodar da pasta scripts/:
    python tests/test_batch_numbering.py

Cobre as duas regras que, se quebrarem, falham em SILÊNCIO:
  1. Rollover de 999 — o padrão antigo `\\d{3}` parava de reconhecer os
     arquivos a partir de `1000_`, fazendo next_batch_number reutilizar o
     mesmo número indefinidamente (lotes sobrescritos, livros presos em
     status_synopsis = 3).
  2. Ordem órfão-primeiro — pending_batch_input tem de devolver o menor lote
     ainda sem output, para que lotes de ciclos anteriores sejam drenados
     antes do recém-exportado.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.batch_numbering import next_batch_number, pending_batch_input


def _mkdir():
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "processed_synopsis"), exist_ok=True)
    return d


def _touch(d, name):
    open(os.path.join(d, name), "w").close()


def _base(path):
    return os.path.basename(path) if path else None


# ==========================================================
# pending_batch_input — regra do prompt dos agentes batch
# ==========================================================

d = _mkdir()
assert pending_batch_input(d, "synopsis") is None, "diretório vazio deve dar None"
print("[OK] diretório vazio -> None")

_touch(d, "037_synopsis_input.json")
assert _base(pending_batch_input(d, "synopsis")) == "037_synopsis_input.json"
print("[OK] input único -> 037")

# O caso que motivou resolver em Python replicando a regra (em vez de injetar
# o path recém-exportado): o órfão 037 tem de vir ANTES do novo 040.
_touch(d, "040_synopsis_input.json")
assert _base(pending_batch_input(d, "synopsis")) == "037_synopsis_input.json", \
    "órfão de ciclo anterior deve ser drenado primeiro"
print("[OK] órfão 037 precede o novo 040")

# Output existente = lote já processado (o mv falhou, mas o trabalho foi feito).
_touch(d, "037_synopsis_output.json")
assert _base(pending_batch_input(d, "synopsis")) == "040_synopsis_input.json", \
    "lote com output deve ser pulado"
print("[OK] 037 com output -> pula para 040")

_touch(d, "040_synopsis_output.json")
assert pending_batch_input(d, "synopsis") is None, "todos processados deve dar None"
print("[OK] todos com output -> None")


# ==========================================================
# Isolamento de prefixo — os 3 pipelines compartilham data/batch
# ==========================================================

d = _mkdir()
_touch(d, "042_synopsis_infantis_input.json")
_touch(d, "043_synopsis_jogos_input.json")
_touch(d, "044_synopsis_input.json")
_touch(d, "005_categorize_input.json")

assert _base(pending_batch_input(d, "synopsis")) == "044_synopsis_input.json", \
    "prefixo 'synopsis' não pode capturar synopsis_infantis/synopsis_jogos"
assert _base(pending_batch_input(d, "synopsis_infantis")) == "042_synopsis_infantis_input.json"
assert _base(pending_batch_input(d, "synopsis_jogos")) == "043_synopsis_jogos_input.json"
assert _base(pending_batch_input(d, "categorize")) == "005_categorize_input.json"
print("[OK] prefixos isolados entre livros / infantis / jogos / categorize")


# ==========================================================
# Rollover de 999 — regressão de \d{3}
# ==========================================================

d = _mkdir()
_touch(d, "999_synopsis_input.json")
_touch(d, "999_synopsis_output.json")

n1 = next_batch_number(d, "synopsis")
assert n1 == "1000", f"após 999 deve vir 1000, veio {n1!r}"
print(f"[OK] 999 -> {n1}")

_touch(d, f"{n1}_synopsis_input.json")
n2 = next_batch_number(d, "synopsis")
assert n2 == "1001", f"número reutilizado: {n1!r} seguido de {n2!r}"
print(f"[OK] {n1} -> {n2} (sem reutilização)")

# O lote de 4 dígitos precisa ser visível para a resolução, senão o hint some.
assert _base(pending_batch_input(d, "synopsis")) == "1000_synopsis_input.json", \
    "lote de 4 dígitos deve ser resolvível"
print("[OK] lote de 4 dígitos é resolvível")


# ==========================================================
# Ordenação numérica com larguras mistas
# ==========================================================

d = _mkdir()
_touch(d, "1000_synopsis_input.json")
_touch(d, "999_synopsis_input.json")

# Lexicograficamente "1000" < "999" — a ordenação tem de ser por int.
assert _base(pending_batch_input(d, "synopsis")) == "999_synopsis_input.json", \
    "ordenação deve ser numérica, não lexicográfica"
print("[OK] 999 precede 1000 (ordenação numérica)")

# Zero-padding preservado continua funcionando na mesma largura.
d = _mkdir()
_touch(d, "007_synopsis_input.json")
_touch(d, "012_synopsis_input.json")
assert _base(pending_batch_input(d, "synopsis")) == "007_synopsis_input.json"
print("[OK] zero-padding de 3 dígitos preservado")


print("\nTodos os testes passaram.")
