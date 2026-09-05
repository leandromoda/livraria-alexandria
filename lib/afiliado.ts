/**
 * Classificação de tráfego e limpeza de tag de afiliado nas rotas de click.
 *
 * ⚠ POR QUE EXISTE — medido em 2026-09-04, cinco dias depois de o tracking
 * voltar a gravar (#312).
 *
 * A tabela `oferta_clicks` acumulou **3.182 cliques em 5 dias**, contra os
 * **518 que o GSC registra em 5 MESES**. O perfil não é de audiência:
 *
 *   - 2.746 de 3.182 (86%) **sem referer nenhum**, batendo em `/api/click/`
 *     direto, sem vir de página alguma;
 *   - **2.191 livros distintos** para 3.182 cliques — varredura de catálogo,
 *     não interesse por título;
 *   - 732 `ip_hash`, o maior com **78 cliques em intervalos de 1-3 min**
 *     madrugada adentro;
 *   - 1.107 cliques com exatamente o mesmo user-agent de Mac;
 *   - um referer `m.baidu.com/s?wd=unlesso42`.
 *
 * O `robots.txt` bloqueia `/api/click/`, mas esse tráfego não obedece.
 *
 * **O que isso custava:** cada uma dessas requisições era redirecionada para a
 * Amazon **com a tag de afiliado**, ou seja, o site gerava clique artificial em
 * volume MAIOR que o pipeline gerava antes do #311 (3.182 em 5 dias contra
 * 3.402 em 30 dias). O contrato de Associados proíbe clique artificial, e
 * milhares deles com conversão zero é o padrão que encerra conta — o que
 * também eliminaria a chance de qualificar para a Creators API.
 *
 * Decisão do Leandro em 2026-09-04: **redirecionar mesmo assim, mas sem a
 * tag**. Nada quebra para quem for classificado errado — a pessoa chega à
 * página do produto normalmente, só não gera comissão naquele clique. É a
 * mesma solução do #311, agora do lado do site.
 */

/** Bots que se identificam no user-agent. */
const PADRAO_BOT =
  /bot|spider|crawl|slurp|bingpreview|headless|phantom|puppeteer|playwright|python-requests|curl|wget|okhttp|scrapy|semrush|ahrefs|dotbot|petalbot|yandex|facebookexternalhit|whatsapp|telegram|AlexandriaVerify/i;

/** Parâmetros que identificam a conta de afiliado. */
const PARAMS_AFILIADO = [
  "tag",
  "matt_tool",
  "matt_word",
  "ascsubtag",
  "linkCode",
];

export function ehBot(userAgent: string | null): boolean {
  if (!userAgent || userAgent.trim().length < 10) return true; // UA ausente ou "pc"
  return PADRAO_BOT.test(userAgent);
}

export function veioDoSite(referer: string | null): boolean {
  if (!referer) return false;
  try {
    const h = new URL(referer).hostname.toLowerCase();
    return h === "livrariaalexandria.com.br" || h === "www.livrariaalexandria.com.br";
  } catch {
    return false;
  }
}

/**
 * Uma requisição só conta como humana se veio de uma página do próprio site
 * E o user-agent não é de bot conhecido.
 *
 * O referer é o sinal forte: os links de oferta só existem dentro do site, e
 * navegador manda referer em navegação normal (a política padrão
 * `strict-origin-when-cross-origin` preserva a origem). Quem chega sem ele
 * não passou por página nenhuma.
 */
export function pareceHumano(
  userAgent: string | null,
  referer: string | null
): boolean {
  return veioDoSite(referer) && !ehBot(userAgent);
}

/** Remove os parâmetros de afiliado. Devolve a URL intacta se não houver. */
export function semTagAfiliado(url: string): string {
  try {
    const u = new URL(url);
    let mexeu = false;
    for (const p of PARAMS_AFILIADO) {
      if (u.searchParams.has(p)) {
        u.searchParams.delete(p);
        mexeu = true;
      }
    }
    return mexeu ? u.toString() : url;
  } catch {
    return url; // URL malformada: melhor redirecionar como está do que quebrar
  }
}

/**
 * A URL final do redirect: com tag para gente, sem tag para o resto.
 */
export function urlDeRedirect(
  urlAfiliada: string,
  userAgent: string | null,
  referer: string | null
): { url: string; humano: boolean } {
  const humano = pareceHumano(userAgent, referer);
  return { url: humano ? urlAfiliada : semTagAfiliado(urlAfiliada), humano };
}
