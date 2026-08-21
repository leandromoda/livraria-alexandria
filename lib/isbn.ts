/**
 * Normalização e validação de ISBN para os identificadores do schema.org.
 *
 * Motivo: em 2026-08-21 o Search Console apontou "Valor ISBN13 inválido para
 * `isbn`" no relatório de Listagens do comerciante ([WNC-10030322]). A causa
 * era emitir `livro.isbn` cru — o valor do banco ia para o JSON-LD sem
 * nenhuma checagem de formato ou dígito verificador.
 *
 * Medido em 2026-08-21 (PostgREST, livros com `is_publishable=true` e `isbn`
 * não nulo, n=9): 7 eram ISBN-13 válidos, 1 tinha 13 dígitos com **checksum
 * errado** (`pai-rico-pai-pobre` → `9788576849943`) e 1 era **ISBN-10**
 * (`industrial-economics-and-management-principles` → `8131803015`). Esses 2
 * eram o apontamento.
 *
 * O Google valida `isbn` das Listagens do comerciante como ISBN-13, então
 * ISBN-10 é convertido (prefixo `978` + dígito verificador recalculado) em vez
 * de descartado — é a conversão canônica, não uma heurística.
 */

function checksum13(twelveDigits: string): number {
  const soma = [...twelveDigits].reduce(
    (acc, digito, i) => acc + (i % 2 === 0 ? 1 : 3) * Number(digito),
    0,
  );
  return (10 - (soma % 10)) % 10;
}

function isbn10Valido(corpo: string): boolean {
  // ISBN-10 usa peso decrescente 10..1 em módulo 11, e o último dígito pode
  // ser `X` (valor 10).
  const soma = [...corpo].reduce((acc, c, i) => {
    const valor = c === "X" ? 10 : Number(c);
    return acc + valor * (10 - i);
  }, 0);
  return soma % 11 === 0;
}

/**
 * Devolve o ISBN-13 canônico (13 dígitos, sem hífen) ou `null` quando o valor
 * não é um ISBN válido. Nunca devolve string vazia — quem chama pode testar a
 * verdade do retorno direto.
 */
export function toIsbn13(bruto: string | null | undefined): string | null {
  if (!bruto) return null;

  const limpo = bruto.toUpperCase().replace(/[^0-9X]/g, "");

  if (limpo.length === 13) {
    if (!/^\d{13}$/.test(limpo)) return null; // `X` só existe em ISBN-10
    return checksum13(limpo.slice(0, 12)) === Number(limpo[12]) ? limpo : null;
  }

  if (limpo.length === 10) {
    if (!/^\d{9}[0-9X]$/.test(limpo)) return null;
    if (!isbn10Valido(limpo)) return null;
    const corpo = `978${limpo.slice(0, 9)}`;
    return `${corpo}${checksum13(corpo)}`;
  }

  return null;
}
