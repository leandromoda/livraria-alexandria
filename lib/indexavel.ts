/**
 * Regra única de "esta página merece estar no índice do Google".
 *
 * Usada nos DOIS lugares que precisam concordar: o `sitemap.ts` (o que é
 * anunciado) e o `generateMetadata` de cada página (o `robots: noindex`).
 * Divergir entre os dois é pior que qualquer um dos dois sozinho — anunciar no
 * sitemap uma URL com `noindex` foi exatamente o alerta "Excluída pela tag
 * noindex" que o Search Console levantou em agosto de 2026.
 *
 * ⚠ POR QUE ESTE CORTE EXISTE — medido em 2026-09-05.
 *
 * O site levou o August 2026 spam update (18–21/08) e as impressões caíram
 * ~93%. Três semanas depois **não houve recuperação**: posição média 58,1 nos
 * últimos 7 dias, contra 56,1 em 26/08; 3 cliques na semana; 631 impressões.
 *
 * Medindo o sitemap de produção contra o Supabase, a pegada fina apareceu — e
 * não onde a intuição aponta:
 *
 *   /livros      5.095 URLs   DENSAS: 5.031 de 5.186 (97%) com descrição
 *                             >= 600 caracteres; só 9 sem descrição
 *   /autores     2.291 URLs   2.063 (90%) SEM BIO; 1.418 (62%) com 1 livro só
 *   /listas        743 URLs   437 (59%) com < 5 membros; TODAS com
 *                             introdução < 200 caracteres
 *   /categorias    127 URLs   saudáveis — 129 das 174 com 20+ livros
 *
 * Faixa fina somada: 1.855 URLs = 22,4% do sitemap. Uma página de autor sem
 * bio é, literalmente, um nome e uma lista de um livro; uma "lista dos
 * melhores X" com 2 itens não é uma lista.
 *
 * E bate com o sinal que o próprio GSC deu em agosto: `/listas/` caiu de 21%
 * para 6,7% da fatia de impressões depois do update. O Google já começou a
 * rebaixar exatamente esta faixa.
 *
 * ⚠ O CORTE É `noindex`, NUNCA 404. A página continua existindo, navegável e
 * linkada internamente — ela só deixa de ser oferecida ao Google. Quando ganhar
 * corpo (o autor recebe bio, a lista chega a 5 membros), volta ao índice
 * sozinha, sem backfill e sem intervenção. Isso é o oposto do #286, que 404a
 * categoria vazia: ali não havia conteúdo nenhum; aqui há, só não o bastante
 * para competir.
 *
 * Critério escolhido pelo Leandro em 2026-09-05, entre três apresentados: o de
 * "sem conteúdo próprio". Descartados o mais agressivo (que tirava do índice
 * páginas de autor que funcionam como índice legítimo de vários livros) e o
 * mínimo (só as listas).
 */

/** Abaixo disto, uma "lista" não é uma lista. */
export const MIN_MEMBROS_LISTA = 5;

/**
 * Acima disto, a página de autor vale como ÍNDICE mesmo sem bio — reunir 2+
 * livros de um autor já é serviço prestado ao leitor. É o que separa este
 * critério do agressivo.
 */
export const MIN_LIVROS_AUTOR_SEM_BIO = 2;

/** Bio curta demais não conta como conteúdo próprio. */
export const MIN_CHARS_BIO = 200;

export function temBio(descricao: string | null | undefined): boolean {
  return (descricao ?? "").trim().length >= MIN_CHARS_BIO;
}

/**
 * Autor entra no índice se tem bio própria OU se agrega livros suficientes
 * para a página valer como índice.
 */
export function autorIndexavel(
  descricao: string | null | undefined,
  qtdLivros: number,
): boolean {
  if (qtdLivros < 1) return false; // sem livro a página já 404a (#263)
  return temBio(descricao) || qtdLivros >= MIN_LIVROS_AUTOR_SEM_BIO;
}

export function listaIndexavel(qtdMembros: number): boolean {
  return qtdMembros >= MIN_MEMBROS_LISTA;
}

/** Açúcar para o `generateMetadata`: espalha `robots` só quando é para excluir. */
export function robotsSeNaoIndexavel(indexavel: boolean) {
  return indexavel ? {} : { robots: { index: false, follow: true } };
}
