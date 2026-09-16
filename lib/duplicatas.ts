/**
 * Livros publicados em duplicata — a mesma obra em mais de uma página.
 *
 * Mapa `slug da duplicata → slug da página mantida`. Usado nos DOIS lugares que
 * precisam concordar, pela mesma razão do `lib/indexavel.ts`:
 *   - `generateMetadata` de `livros/[slug]` → canonical aponta para a mantida;
 *   - `app/sitemap.ts` → a duplicata sai do sitemap.
 * Anunciar no sitemap uma URL cuja canonical aponta para outra é sinal
 * contraditório para o Google.
 *
 * ⚠ É CANONICAL, NÃO 404 NEM NOINDEX. A duplicata continua no ar, navegável e
 * com oferta; só deixa de competir com a própria obra. Reversível: remover a
 * entrada daqui devolve a página ao índice.
 *
 * COMO A LISTA FOI FEITA — medido em 2026-09-16 (TASK-SEO-017).
 *
 * Duas páginas publicáveis cuja oferta ativa aponta para o MESMO produto de
 * catálogo do ML (`/p/MLB…`) foram resolvidas pela API para o mesmo item,
 * passando pelo portão autor + título. Cruzamento no PostgREST de produção:
 * 5.094 livros publicáveis × ofertas ativas com `/p/MLB` (829 livros).
 * Resultado: 14 grupos, 28 páginas, 0 com título divergente — 13 são duplicata.
 *
 * Por que NÃO se usou o sufixo `-2` como critério: medido no mesmo dia, dos 121
 * pares `slug` / `slug-N` publicáveis, os que apontam para produtos diferentes
 * incluem OBRAS DIFERENTES com o mesmo título — Electra (Sófocles × Eurípides),
 * Inferno (Dan Brown × Patrícia Melo), Blade Runner (Philip K. Dick × K. W.
 * Jeter). E o sufixo não enxerga duplicata de grafia distinta (as três últimas
 * entradas abaixo).
 *
 * Regra de qual página fica (escolhida por Leandro em 2026-09-16):
 *   1. a sem sufixo numérico;
 *   2. sem sufixo nos dois lados, a de título igual ao `BOOK_TITLE` do ML;
 *   3. sufixo nos dois lados (só Narnia), a de menor número.
 *
 * ⚠ FICOU DE FORA de propósito: `a-guerra-dos-tronos` (1996) e
 * `a-guerra-dos-tronos---edicao-ilustrada` (2016). Caem no mesmo produto, mas
 * são edições distintas — é oferta errada numa delas, não duplicata.
 *
 * O critério só cobre quem já migrou para o ML (16% do catálogo). Os demais
 * pares seguem sem decisão — não completar esta lista por heurística de slug.
 */
export const DUPLICATA_PARA_CANONICA: Readonly<Record<string, string>> = {
  // sufixo numérico → sem sufixo (regra 1)
  "it-a-coisa-2": "it-a-coisa",
  "cem-anos-de-solidao-2": "cem-anos-de-solidao",
  "os-tres-mosqueteiros-2": "os-tres-mosqueteiros",
  "o-morro-dos-ventos-uivantes-2": "o-morro-dos-ventos-uivantes",
  "pais-e-filhos-2": "pais-e-filhos",
  "mrs-dalloway-2": "mrs-dalloway",
  "o-espiao-que-saiu-do-frio-2": "o-espiao-que-saiu-do-frio",
  "crime-e-castigo-2": "crime-e-castigo",
  "os-miseraveis-2": "os-miseraveis",

  // sufixo nos dois lados → menor número (regra 3)
  "as-cronicas-de-narnia-3": "as-cronicas-de-narnia-2",

  // sem sufixo, invisíveis à heurística de slug → BOOK_TITLE do ML (regra 2)
  "as-cartas-persas": "cartas-persas", //              ML: "Cartas Persas"
  "amor-nos-tempos-do-colera": "o-amor-nos-tempos-do-colera", // "O amor nos tempos do cólera"
  "o-rei-amarelo": "o-rei-de-amarelo", //              ML: "O rei de amarelo"
};

/** Slug da página que deve ser a canônica para este livro. */
export function slugCanonicoLivro(slug: string): string {
  return DUPLICATA_PARA_CANONICA[slug] ?? slug;
}

/** True se esta página é duplicata e não deve ir ao sitemap. */
export function livroEhDuplicata(slug: string): boolean {
  return Object.prototype.hasOwnProperty.call(DUPLICATA_PARA_CANONICA, slug);
}
