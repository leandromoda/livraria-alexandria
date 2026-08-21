# ============================================================
# ISBN — normalizacao e validacao
# Livraria Alexandria
#
# Espelha `lib/isbn.ts` do site. As duas implementacoes precisam concordar:
# o site so emite `isbn`/`gtin13` no JSON-LD quando o valor e um ISBN-13
# valido, e o pipeline so grava ISBN que passe pela mesma regra.
#
# Motivo: em 2026-08-21 o Search Console apontou "Valor ISBN13 invalido para
# `isbn`" (Listagens do comerciante, [WNC-10030322]). O #289 fez o site parar
# de propagar o valor ruim; este modulo ataca a origem — a ingestao gravava o
# `isbn` do seed sem checar formato nem digito verificador.
#
# Medido em 2026-08-21 (PostgREST, livros com is_publishable=true e isbn nao
# nulo, n=9): 7 ISBN-13 validos, 1 com 13 digitos e checksum ERRADO
# (`pai-rico-pai-pobre` -> 9788576849943) e 1 ISBN-10
# (`industrial-economics-and-management-principles` -> 8131803015).
# ============================================================

import re


def _checksum13(doze_digitos):
    """Digito verificador do ISBN-13: modulo 10 com pesos alternados 1 e 3."""
    soma = sum(
        (1 if i % 2 == 0 else 3) * int(d)
        for i, d in enumerate(doze_digitos)
    )
    return (10 - (soma % 10)) % 10


def _isbn10_valido(corpo):
    """ISBN-10: modulo 11 com pesos decrescentes 10..1; o ultimo digito pode
    ser `X`, que vale 10."""
    soma = sum(
        (10 if c == "X" else int(c)) * (10 - i)
        for i, c in enumerate(corpo)
    )
    return soma % 11 == 0


def normalize_isbn13(bruto):
    """Devolve o ISBN-13 canonico (13 digitos, sem hifen) ou None.

    - ISBN-13 com checksum correto: devolve normalizado (sem hifen/espaco).
    - ISBN-10 valido: converte (prefixo 978 + checksum recalculado). E a
      conversao canonica, nao heuristica.
    - Qualquer outra coisa (checksum errado, tamanho estranho, lixo): None.

    Nunca levanta excecao — entrada pode ser None, numero ou string suja.
    """
    if bruto is None:
        return None

    limpo = re.sub(r"[^0-9X]", "", str(bruto).upper())

    if len(limpo) == 13:
        if not limpo.isdigit():
            return None  # `X` so existe em ISBN-10
        return limpo if _checksum13(limpo[:12]) == int(limpo[12]) else None

    if len(limpo) == 10:
        if not re.fullmatch(r"[0-9]{9}[0-9X]", limpo):
            return None
        if not _isbn10_valido(limpo):
            return None
        corpo = "978" + limpo[:9]
        return corpo + str(_checksum13(corpo))

    return None
