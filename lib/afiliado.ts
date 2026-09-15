/**
 * Classificação de tráfego e limpeza de tag de afiliado nas rotas de click.
 *
 * ⚠ POR QUE EXISTE — medido em 2026-09-04, cinco dias depois de o tracking
 * voltar a gravar (#312).
 *
 * A tabela `oferta_clicks` acumulou **3.182 cliques em 5 dias**, contra os
 * **518 que o GSC registra em 5 MESES**. O perfil não era de audiência: 86%
 * sem referer, 2.191 livros distintos para 3.182 cliques (varredura de
 * catálogo), 732 `ip_hash` com o maior fazendo 78 cliques em intervalos de
 * 1-3 min, user-agents repetidos. O `robots.txt` bloqueia `/api/click/`, mas
 * esse tráfego não obedece — e cada requisição ia para a Amazon COM a tag.
 *
 * O contrato de Associados proíbe clique artificial, e milhares deles com
 * conversão zero é o padrão que encerra conta. Decisão do Leandro em
 * 2026-09-04: **redirecionar mesmo assim, mas sem a tag**. Nada quebra para
 * quem for classificado errado — a pessoa chega ao produto normalmente, só não
 * gera comissão naquele clique.
 *
 * ---------------------------------------------------------------------------
 * ⚠ A PRIMEIRA VERSÃO DA REGRA (#315) ESTAVA INVERTIDA — corrigida em 2026-09-15
 * ---------------------------------------------------------------------------
 *
 * Ela classificava como humano quem chegasse com Referer do próprio site. Só
 * que os links de oferta de livro (`livros/[slug]`, `ofertas`) levam
 * `rel="noopener noreferrer nofollow sponsored"` — e `noreferrer` faz o
 * navegador NÃO enviar Referer. Medido em 2026-09-15, sobre os 4.366 cliques
 * gravados desde a migração `is_bot` (05/09 10:33):
 *
 *   - clique humano de verdade chegava SEM referer → marcado bot → tag removida;
 *   - os 1.010 marcados "humanos" eram bots forjando referer:
 *       841 com Referer = home, onde NÃO existe link de oferta (conferido no
 *           código: `/api/click` só aparece em livros/[slug], ofertas, jogos
 *           e infantis);
 *       169 com Referer = a própria rota `/api/click`;
 *       ZERO vindos de `/livros/<slug>`;
 *       462 livros distintos, user-agents rotativos;
 *   - o painel de Associados, fonte independente, confirmava: 3.789 cliques em
 *     06/08–04/09 contra 3.421 em 16/08–14/09 (~114/dia), 0 pedidos — o
 *     vazamento seguia praticamente no mesmo ritmo depois do #315.
 *
 * Ou seja: o risco de conta que o #315 deveria fechar seguia aberto, e ainda
 * cortava a comissão de quem clicava de verdade.
 *
 * O SINAL CERTO é o que o navegador manda numa navegação ativada pelo usuário
 * e que sobrevive ao `noreferrer`: o Fetch Metadata — `Sec-Fetch-User: ?1`
 * (a navegação foi disparada por gesto do usuário) + `Sec-Fetch-Site:
 * same-origin` (a partir de uma página deste mesmo site). Chrome, Edge,
 * Firefox e Safari 16.4+ enviam esses cabeçalhos.
 *
 * E o Referer, que não servia como sinal de humano, vira sinal de BOT onde o
 * link é `noreferrer`: ali, um Referer do próprio site só pode ser forjado.
 *
 * Suposto, não medido: que os bots atuais não mandam `Sec-Fetch-*`. A tabela
 * não grava esses cabeçalhos, então não há como afirmar hoje — o que se sabe é
 * que eles forjam Referer, o que já os derruba pela regra acima.
 *
 * FALHA SEGURA: se algum proxy no caminho (Cloudflare → Vercel Edge) removesse
 * `Sec-Fetch-*`, tudo viraria "bot" e nenhum clique levaria tag — perda de
 * comissão, nunca risco de conta. O teste pós-deploy com clique real no Chrome
 * é o que confirma que os cabeçalhos chegam.
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
 * Navegação disparada por gesto do usuário, a partir de uma página deste mesmo
 * site — segundo o próprio navegador (Fetch Metadata).
 */
export function cliqueDeUsuario(h: Headers): boolean {
  return (
    h.get("sec-fetch-user") === "?1" &&
    h.get("sec-fetch-site") === "same-origin"
  );
}

export type OpcoesClique = {
  /**
   * O link de origem leva `rel="noreferrer"`? Livros (`livros/[slug]`,
   * `ofertas`): sim. Jogos e infantis (`rel="nofollow sponsored"`): não.
   * Quando leva, um Referer do próprio site é impossível num clique real.
   */
  linkSemReferer: boolean;
};

export function pareceHumano(h: Headers, opts: OpcoesClique): boolean {
  if (ehBot(h.get("user-agent"))) return false;
  if (opts.linkSemReferer && veioDoSite(h.get("referer"))) return false; // forjado
  return cliqueDeUsuario(h);
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
  h: Headers,
  opts: OpcoesClique
): { url: string; humano: boolean } {
  const humano = pareceHumano(h, opts);
  return { url: humano ? urlAfiliada : semTagAfiliado(urlAfiliada), humano };
}
