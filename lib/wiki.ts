// Fatos do Wikidata gravados pelo pipeline (scripts/steps/wikidata_enrich.py)
// em `livros.wiki` e `autores.wiki`. Contrato: chave ausente = sem dado. A
// página só renderiza o que existe — bloco de template com "não informado" em
// milhares de páginas é justamente o padrão de conteúdo em escala que o spam
// update de agosto/2026 puniu.

export type WikiLinks = { pt?: string; en?: string };

export type WikiLivro = {
  qid: string;
  wikipedia?: WikiLinks;
  titulo_original?: string;
  idioma_original?: string;
  publicacao?: number;
  generos?: string[];
  premios?: string[];
  serie?: { qid: string; nome: string; ordem?: string };
  adaptacoes?: { titulo: string; tipo?: string; ano?: number }[];
  openlibrary?: string;
};

export type WikiAutor = {
  qid: string;
  wikipedia?: WikiLinks;
  nascimento?: number;
  morte?: number;
  pais?: string;
};

/** Ano do Wikidata (negativo = a.C.) em texto. */
export function formatAno(ano: number): string {
  return ano < 0 ? `${-ano} a.C.` : String(ano);
}

/** Wikipedia em português quando existe; senão a inglesa, marcada como tal. */
export function wikipediaLink(w?: WikiLinks): { url: string; rotulo: string } | null {
  if (w?.pt) return { url: w.pt, rotulo: "Wikipédia" };
  if (w?.en) return { url: w.en, rotulo: "Wikipédia (em inglês)" };
  return null;
}

export const wikidataUrl = (qid: string) => `https://www.wikidata.org/wiki/${qid}`;

export const openLibraryUrl = (id: string) => `https://openlibrary.org/works/${id}`;

/** URLs para `sameAs` no JSON-LD: a mesma entidade em fontes de referência. */
export function sameAs(w?: { qid: string; wikipedia?: WikiLinks } | null): string[] {
  if (!w?.qid) return [];
  return [w.wikipedia?.pt, w.wikipedia?.en, wikidataUrl(w.qid)].filter(Boolean) as string[];
}

const normalizar = (s: string) =>
  s.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9]/g, "");

/** Título original só vale exibir quando difere do título da página. */
export function tituloOriginalDiferente(original: string | undefined, titulo: string): string | null {
  if (!original) return null;
  return normalizar(original) === normalizar(titulo) ? null : original;
}
