"""Testes de core.isbn — normalizacao e validacao de ISBN.

Rodar da pasta scripts/:
    python tests/test_isbn.py

Por que este teste existe: ate 2026-08-21 a ingestao gravava o `isbn` do seed
cru, sem checar formato nem digito verificador. O Search Console apontou
"Valor ISBN13 invalido para `isbn`" ([WNC-10030322]) porque o site publicava
esse valor no JSON-LD. O #289 fez o site parar de propagar; este modulo ataca
a origem.

A falha que este teste protege e SILENCIOSA: um ISBN com checksum errado tem o
tamanho certo e a cara certa. So o digito verificador denuncia — e foi
exatamente `9788576849943` (13 digitos, checksum errado) que passou.

`lib/isbn.ts` no site implementa a MESMA regra. Se mudar uma, mudar a outra.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.isbn import normalize_isbn13


# ==========================================================
# ISBN-13 valido passa intacto
# ==========================================================

assert normalize_isbn13("9788532305541") == "9788532305541"
assert normalize_isbn13("9781009395847") == "9781009395847"
print("[OK] ISBN-13 valido passa intacto")


# ==========================================================
# O caso que originou o bug: 13 digitos, checksum ERRADO
# ==========================================================

# `pai-rico-pai-pobre` no banco de producao (medido 2026-08-21). Tem 13
# digitos, entao a checagem antiga (`len == 13`) aprovava.
assert normalize_isbn13("9788576849943") is None, \
    "checksum errado tem de ser rejeitado, nao so contado"
print("[OK] 13 digitos com checksum errado e rejeitado")


# ==========================================================
# 2026-09-20: checksum certo, prefixo que NAO e de ISBN
# ==========================================================

# O aviso do GSC voltou depois que o backfill do #293 levou os livros com ISBN
# de 9 para 2.818. Dos publicaveis, 18 tinham 13 digitos com checksum VALIDO e
# prefixo fora do Bookland — EAN-13 de outro dominio, nao ISBN. Valores reais
# do Supabase em 2026-09-20:
assert normalize_isbn13("4064066106690") is None   # 35-sonnets
assert normalize_isbn13("3410007589793") is None   # a-guerra-dos-judeus
assert normalize_isbn13("8596547414988") is None   # beatrice
assert normalize_isbn13("2200000107497") is None   # lorna-doone
print("[OK] EAN-13 com checksum valido fora do Bookland (978/979) e rejeitado")

# E o 979 continua valendo — ISBN-13 moderno usa os dois prefixos.
assert normalize_isbn13("9791234567896") == "9791234567896"
print("[OK] prefixo 979 continua aceito")


# ==========================================================
# ISBN-10 e convertido, nao descartado
# ==========================================================

# `industrial-economics-and-management-principles` (medido 2026-08-21).
assert normalize_isbn13("8131803015") == "9788131803011"
# Com o digito verificador `X`, que vale 10.
assert normalize_isbn13("080442957X") == "9780804429573"
# Minusculo tambem — a normalizacao faz upper antes de limpar.
assert normalize_isbn13("080442957x") == "9780804429573"
print("[OK] ISBN-10 valido vira ISBN-13 (inclusive com X)")

assert normalize_isbn13("1234567890") is None, "ISBN-10 com checksum invalido"
print("[OK] ISBN-10 com checksum invalido e rejeitado")


# ==========================================================
# Separadores e sujeira
# ==========================================================

assert normalize_isbn13("978-85-3230-554-1") == "9788532305541"
assert normalize_isbn13("978 85 3230 554 1") == "9788532305541"
assert normalize_isbn13("ISBN 978-85-3230-554-1") == "9788532305541"
print("[OK] hifens, espacos e prefixo textual sao ignorados")

# `X` so existe como digito verificador de ISBN-10: num campo de 13 e lixo.
assert normalize_isbn13("978853230554X") is None
print("[OK] X em ISBN-13 e rejeitado")


# ==========================================================
# Entrada degenerada — nunca levanta excecao
# ==========================================================

for entrada in (None, "", "   ", "123", "abc", "-", 0, 9788532305541):
    resultado = normalize_isbn13(entrada)
    assert resultado is None or resultado == "9788532305541", \
        f"entrada {entrada!r} devolveu {resultado!r}"
# Int com o valor certo tambem funciona (seeds as vezes trazem numero, nao str).
assert normalize_isbn13(9788532305541) == "9788532305541"
print("[OK] None, vazio, lixo e int nao quebram")


print("\nTodos os testes passaram.")
