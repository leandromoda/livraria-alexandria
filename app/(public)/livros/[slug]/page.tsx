// ISR on-demand: cada livro renderiza no primeiro acesso e fica em cache no
// edge, revalidando a cada 24h. O generateStaticParams vazio habilita o
// cache ISR sem prerenderizar os milhares de slugs no build (evita N queries
// ao Supabase) — dynamicParams (default) gera cada página sob demanda.
//
// TTL subiu de 1h para 24h em 2026-07-26 para conter a cota do free tier da
// Vercel. Método: painel de Usage (janela de 30 dias, lido em 2026-07-26)
// marcava 139K/200K ISR Writes e 3h09m/4h de Fluid Active CPU, com 219K edge
// requests — ou seja, ~63% dos requests terminavam em regeneração, sintoma de
// catálogo de cauda longa com TTL curto (página raramente revisitada dentro da
// hora → quase toda visita de crawler era miss). Tradeoff aceito: o preço
// exibido (que já é snapshot do scrape) fica até 24h defasado.
export const revalidate = 86400; // 24h
export async function generateStaticParams() {
  return [];
}

import { notFound } from "next/navigation";
import { unstable_cache } from "next/cache";
import { supabase } from "@/lib/supabase";
import { toIsbn13 } from "@/lib/isbn";
import { slugCanonicoLivro } from "@/lib/duplicatas";
import { livroIndexavel, robotsSeNaoIndexavel } from "@/lib/indexavel";
import {
  type WikiLivro,
  formatAno,
  wikipediaLink,
  wikidataUrl,
  openLibraryUrl,
  sameAs,
  tituloOriginalDiferente,
} from "@/lib/wiki";
import type { Metadata } from "next";
import BookCover from "@/app/_components/BookCover";
import Link from "next/link";

type PageProps = {
  params: Promise<{ slug: string }>;
};

// Leituras memoizadas no Data Cache do Next. O client do Supabase faz fetch com
// `no-store`, o que impediria o ISR on-demand de cachear o render; envolver as
// queries em unstable_cache torna o dado cacheável (chave = slug/livro_id) e o
// render vira static-eligible → HIT no cache do edge. Revalida junto com a rota.
const getLivro = unstable_cache(
  async (slug: string) => {
    const { data } = await supabase
      .from("livros")
      .select(`
        *,
        livros_categorias (
          categorias (
            nome,
            slug
          )
        ),
        livros_autores (
          autores (
            nome,
            slug
          )
        )
      `)
      .eq("slug", slug)
      .eq("is_publishable", true)
      .single();
    return data;
  },
  ["livro-detalhe"],
  { revalidate: 86400 },
);

const getOfertas = unstable_cache(
  async (livroId: string) => {
    const { data } = await supabase
      .from("ofertas")
      .select("id, preco, marketplace, url_afiliada")
      .eq("livro_id", livroId)
      .eq("ativa", true);
    return data ?? [];
  },
  ["livro-ofertas"],
  { revalidate: 86400 },
);

const getListasDoLivro = unstable_cache(
  async (livroId: string) => {
    const { data } = await supabase
      .from("lista_livros")
      .select("listas ( titulo, slug )")
      .eq("livro_id", livroId);
    return data ?? [];
  },
  ["livro-listas"],
  { revalidate: 86400 },
);

// Outros volumes da mesma série (Wikidata P179) que existem no catálogo. É
// link interno entre páginas que de fato se relacionam — o oposto do link de
// template. Filtra pelo JSON: `wiki->serie->>qid`.
const getVolumesDaSerie = unstable_cache(
  async (serieQid: string) => {
    const { data } = await supabase
      .from("livros")
      .select("titulo, slug, wiki")
      .eq("is_publishable", true)
      .eq("wiki->serie->>qid", serieQid)
      .limit(30);
    return data ?? [];
  },
  ["livro-serie"],
  { revalidate: 86400 },
);

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { slug } = await params;

  const livro = await getLivro(slug);

  if (!livro) return {};

  // Mesma leitura (memoizada) que a página usa — sem query extra.
  const ofertas = await getOfertas(livro.id);

  // No Supabase, `descricao` já contém a sinopse editorial gerada (publish.py
  // envia o campo `sinopse` do SQLite para a coluna `descricao`).
  const description = livro.descricao?.slice(0, 160)
    ?? `Sinopse, ofertas e informações sobre ${livro.titulo}${livro.autor ? ` de ${livro.autor}` : ""}.`;

  return {
    title: livro.titulo,
    description,
    // Duplicata aponta a canonical para a página mantida — ver lib/duplicatas.ts.
    alternates: { canonical: `/livros/${slugCanonicoLivro(slug)}` },
    // Sem oferta com preço = link de busca apenas: fora do índice até o
    // monitor confirmar o produto — ver livroIndexavel em lib/indexavel.ts.
    ...robotsSeNaoIndexavel(livroIndexavel(ofertas)),
    openGraph: {
      title: livro.titulo,
      description,
      ...(livro.imagem_url ? { images: [{ url: livro.imagem_url }] } : {}),
    },
    // Sem twitter:card o X monta o card pequeno (ou nenhum) — a capa só
    // aparece grande com summary_large_image. Usado pelo "livro do dia"
    // (scripts/steps/social_x.py).
    twitter: {
      card: livro.imagem_url ? "summary_large_image" : "summary",
      title: livro.titulo,
      description,
      ...(livro.imagem_url ? { images: [livro.imagem_url] } : {}),
    },
  };
}

function formatPrice(value: unknown): string | null {
  const num = Number(value);
  if (!value || num === 0) return null;
  return num.toLocaleString("pt-BR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

const MARKETPLACE_LABELS: Record<string, string> = {
  amazon:         "Amazon",
  mercadolivre:   "Mercado Livre",
  mercado_livre:  "Mercado Livre",
};

export default async function LivroPage({ params }: PageProps) {
  const { slug } = await params;

  /**
   * Livro + Categorias
   */
  const livro = await getLivro(slug);

  if (!livro) {
    notFound();
  }

  /**
   * Ofertas + listas relacionadas (independentes → em paralelo)
   */
  const wiki = (livro.wiki ?? null) as WikiLivro | null;

  const [ofertas, listasPivot, volumesPivot] = await Promise.all([
    getOfertas(livro.id),
    getListasDoLivro(livro.id),
    wiki?.serie?.qid ? getVolumesDaSerie(wiki.serie.qid) : Promise.resolve([]),
  ]);

  // Volumes da série, sem o próprio livro, na ordem do Wikidata (P1545);
  // quem não tem ordem vai para o fim, por título.
  const ordemNum = (o?: string) => (o && /^\d+$/.test(o) ? Number(o) : Infinity);
  const outrosVolumes = volumesPivot
    .filter((v) => v.slug !== slug)
    .sort(
      (a, b) =>
        ordemNum((a.wiki as WikiLivro | null)?.serie?.ordem) -
          ordemNum((b.wiki as WikiLivro | null)?.serie?.ordem) ||
        a.titulo.localeCompare(b.titulo, "pt-BR"),
    );

  // Linhas de "Sobre a obra". Cada uma só entra com dado — nunca "não
  // informado" (ver lib/wiki.ts).
  const sobreAObra: { rotulo: string; valor: string }[] = [];
  if (wiki) {
    const original = tituloOriginalDiferente(wiki.titulo_original, livro.titulo);
    if (original) sobreAObra.push({ rotulo: "Título original", valor: original });
    if (wiki.idioma_original) sobreAObra.push({ rotulo: "Idioma original", valor: wiki.idioma_original });
    if (wiki.publicacao != null) sobreAObra.push({ rotulo: "Primeira publicação", valor: formatAno(wiki.publicacao) });
    if (wiki.generos?.length) sobreAObra.push({ rotulo: wiki.generos.length > 1 ? "Gêneros" : "Gênero", valor: wiki.generos.join(", ") });
    if (wiki.serie) {
      sobreAObra.push({
        rotulo: "Série",
        valor: wiki.serie.ordem ? `${wiki.serie.nome} (volume ${wiki.serie.ordem})` : wiki.serie.nome,
      });
    }
    if (wiki.premios?.length) sobreAObra.push({ rotulo: wiki.premios.length > 1 ? "Prêmios" : "Prêmio", valor: wiki.premios.join("; ") });
    if (wiki.adaptacoes?.length) {
      sobreAObra.push({
        rotulo: wiki.adaptacoes.length > 1 ? "Adaptações" : "Adaptação",
        valor: wiki.adaptacoes
          .map((a) => {
            const extra = [a.tipo, a.ano != null ? formatAno(a.ano) : null].filter(Boolean).join(", ");
            return extra ? `${a.titulo} (${extra})` : a.titulo;
          })
          .join("; "),
      });
    }
  }

  const wikipedia = wikipediaLink(wiki?.wikipedia);
  const fontes = wiki
    ? [
        ...(wikipedia ? [wikipedia] : []),
        { url: wikidataUrl(wiki.qid), rotulo: "Wikidata" },
        ...(wiki.openlibrary ? [{ url: openLibraryUrl(wiki.openlibrary), rotulo: "Open Library" }] : []),
      ]
    : [];

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const listas = listasPivot?.map((l: any) => l.listas).filter(Boolean) ?? [];

  /**
   * Schema.org
   */

  // Um ISBN-13 é um GTIN-13 válido, e `gtin13` é o identificador global que o
  // relatório "Listagens do comerciante" do Search Console pede (avisos de
  // 2026-07-30 e 31: "nenhum identificador global fornecido"). O aviso é não
  // crítico e não bloqueia rich result.
  //
  // Só resolve os poucos livros que têm ISBN: numa amostra de 300 livros
  // publicados em 2026-08-06, 297 estavam SEM isbn no banco. O resto é lacuna
  // de dado do pipeline, não do site.
  //
  // `toIsbn13` valida o dígito verificador em vez de só contar dígitos. A
  // checagem antiga (`length === 13`) deixava passar checksum errado, e o
  // `isbn` abaixo saía cru — o que rendeu "Valor ISBN13 inválido para `isbn`"
  // no GSC em 2026-08-21 ([WNC-10030322]). Ver `lib/isbn.ts`.
  const isbn13 = toIsbn13(livro.isbn);

  const schema = {
    "@context": "https://schema.org",
    "@type": "Product",
    name: livro.titulo,
    url: `${process.env.NEXT_PUBLIC_SITE_URL}/livros/${slug}`,
    description: livro.descricao ?? undefined,
    image: livro.imagem_url || undefined,
    // Condicionais: sem isbn, `sku: livro.isbn` emitia `"sku": null` no JSON-LD.
    // `sku` é identificador livre e não é validado pelo Google, então segue o
    // valor do banco; `isbn`/`gtin13` só saem quando o ISBN é de fato válido.
    ...(livro.isbn ? { sku: livro.isbn } : {}),
    ...(isbn13 ? { isbn: isbn13, gtin13: isbn13 } : {}),
    ...(livro.autor?.trim() ? { brand: { "@type": "Brand", name: livro.autor.trim().substring(0, 70) } } : {}),
    // A mesma obra em fontes de referência (Wikipedia/Wikidata), quando o
    // pipeline casou o livro no Wikidata.
    ...(sameAs(wiki).length ? { sameAs: sameAs(wiki) } : {}),
    additionalProperty: [
      {
        "@type": "PropertyValue",
        name: "Autor",
        value: livro.autor,
      },
      {
        "@type": "PropertyValue",
        name: "Ano de publicação",
        value: livro.ano_publicacao,
      },
    ],
    offers: (() => {
      // Apenas ofertas com preço válido — Google exige price em todo Offer
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const ofertasComPreco = (ofertas ?? []).filter((o: any) => Number(o.preco) > 0);
      if (!ofertasComPreco.length) return undefined;

      const pageUrl = `${process.env.NEXT_PUBLIC_SITE_URL}/livros/${slug}`;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const offerList = ofertasComPreco.map((o: any) => ({
        "@type": "Offer" as const,
        price: Number(o.preco),
        priceCurrency: "BRL",
        availability: "https://schema.org/InStock",
        url: o.url_afiliada || pageUrl,
        seller: { "@type": "Organization" as const, name: o.marketplace },
      }));

      if (offerList.length === 1) return offerList[0];

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const prices = ofertasComPreco.map((o: any) => Number(o.preco));
      return {
        "@type": "AggregateOffer" as const,
        lowPrice: Math.min(...prices),
        highPrice: Math.max(...prices),
        priceCurrency: "BRL",
        offerCount: offerList.length,
        offers: offerList,
      };
    })(),
  };

  return (
    <div className="max-w-4xl mx-auto space-y-10">

      {/* Schema JSON-LD — só renderiza quando há offers para satisfazer requisito do Google */}
      {schema.offers && (
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(schema) }}
        />
      )}

      {/* =========================
          HERO DO LIVRO
      ========================== */}
      <section className="flex flex-col sm:flex-row gap-8">

        {/* Capa */}
        <div className="flex-shrink-0">
          <BookCover src={livro.imagem_url} alt={livro.titulo} />
        </div>

        {/* Dados */}
        <div className="space-y-4">

          {/* Breadcrumb */}
          <p className="text-xs text-[#7B5E3A] uppercase tracking-widest font-medium">
            <Link href="/livros" className="hover:text-[#C9A84C] transition-colors">
              Livros
            </Link>
            {" "}/ <span>{livro.titulo}</span>
          </p>

          <h1 className="text-3xl font-serif font-semibold text-[#0D1B2A] leading-tight">
            {livro.titulo}
          </h1>

          {livro.autor && (() => {
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const autorEntry = livro.livros_autores?.[0]?.autores as any;
            return (
              <p className="text-base text-[#4A4A4A]">
                por{" "}
                {autorEntry?.slug ? (
                  <Link
                    href={`/autores/${autorEntry.slug}`}
                    className="font-medium text-[#0D1B2A] hover:text-[#4A1628] transition-colors"
                  >
                    {livro.autor}
                  </Link>
                ) : (
                  <span className="font-medium text-[#0D1B2A]">{livro.autor}</span>
                )}
              </p>
            );
          })()}

          {/* Metadados */}
          <div className="flex flex-wrap gap-2 pt-1">

            {livro.ano_publicacao && (
              <span className="text-xs bg-[#F5F0E8] border border-[#E6DED3] text-[#7B5E3A] px-3 py-1 rounded-full">
                {livro.ano_publicacao}
              </span>
            )}

            {livro.idioma && (
              <span className="text-xs bg-[#F5F0E8] border border-[#E6DED3] text-[#7B5E3A] px-3 py-1 rounded-full">
                {livro.idioma}
              </span>
            )}

            {livro.livros_categorias
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              ?.filter((rel: any) => rel.categorias)
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              .map((rel: any) => (
                <a
                  key={rel.categorias.slug}
                  href={`/categorias/${rel.categorias.slug}`}
                  className="text-xs bg-[#4A1628] text-[#F5F0E8] px-3 py-1 rounded-full hover:bg-[#6B2238] transition-colors"
                >
                  {rel.categorias.nome}
                </a>
              ))}

          </div>

          {/* CTA principal */}
          {ofertas && ofertas.length > 0 && (
            <div className="pt-2">
              <a
                href={`/api/click/${ofertas[0].id}`}
                target="_blank"
                rel="noopener noreferrer nofollow sponsored"
                className="inline-flex items-center gap-2 px-5 py-2.5 bg-[#C9A84C] text-[#4A1628] text-sm font-semibold rounded-lg hover:bg-[#e0bc5e] transition-colors"
              >
                {(() => {
                  const price = formatPrice(ofertas[0].preco);
                  return price ? `Ver melhor oferta — R$ ${price}` : "Ver melhor oferta";
                })()}
              </a>
            </div>
          )}

        </div>

      </section>

      {/* =========================
          SINOPSE
      ========================== */}
      {livro.descricao && (
        <section className="bg-white border border-[#E6DED3] rounded-2xl px-8 py-7">

          <h2 className="text-lg font-serif font-semibold text-[#0D1B2A] mb-4">
            Sinopse
          </h2>

          <p className="text-[#4A4A4A] leading-relaxed text-base">
            {livro.descricao}
          </p>

        </section>
      )}

      {/* =========================
          SOBRE A OBRA (Wikidata)
          Só renderiza com dado — ver lib/wiki.ts.
      ========================== */}
      {(sobreAObra.length > 0 || outrosVolumes.length > 0 || fontes.length > 0) && (
        <section className="bg-white border border-[#E6DED3] rounded-2xl px-8 py-7 space-y-6">

          {sobreAObra.length > 0 && (
            <div>
              <h2 className="text-lg font-serif font-semibold text-[#0D1B2A] mb-4">
                Sobre a obra
              </h2>
              <dl className="grid grid-cols-1 sm:grid-cols-[max-content_1fr] gap-x-6 gap-y-2 text-sm">
                {sobreAObra.map((linha) => (
                  <div key={linha.rotulo} className="contents">
                    <dt className="text-[#7B5E3A] font-medium">{linha.rotulo}</dt>
                    <dd className="text-[#4A4A4A] mb-2 sm:mb-0">{linha.valor}</dd>
                  </div>
                ))}
              </dl>
            </div>
          )}

          {outrosVolumes.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-[#0D1B2A] mb-2">
                Outros volumes da série no catálogo
              </h3>
              <ul className="flex flex-wrap gap-2">
                {outrosVolumes.map((v) => (
                  <li key={v.slug}>
                    <Link
                      href={`/livros/${v.slug}`}
                      className="inline-block text-xs bg-[#F5F0E8] border border-[#E6DED3] text-[#4A1628] px-3 py-1 rounded-full hover:border-[#C9A84C] transition-colors"
                    >
                      {v.titulo}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {fontes.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-[#0D1B2A] mb-2">
                Para saber mais
              </h3>
              {/* Citação editorial, não afiliado: sem nofollow/sponsored. */}
              <ul className="flex flex-wrap gap-x-5 gap-y-1 text-sm">
                {fontes.map((f) => (
                  <li key={f.url}>
                    <a
                      href={f.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-[#4A1628] underline decoration-[#C9A84C] underline-offset-2 hover:text-[#C9A84C] transition-colors"
                    >
                      {f.rotulo} ↗
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          )}

        </section>
      )}

      {/* =========================
          ONDE COMPRAR
      ========================== */}
      <section>

        <h2 className="text-xl font-serif font-semibold text-[#0D1B2A] mb-5">
          Onde comprar
        </h2>

        {!ofertas?.length && (
          <p className="text-[#7B5E3A] text-sm">
            Nenhuma oferta disponível no momento.
          </p>
        )}

        <div className="space-y-3">

          {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
          {ofertas?.map((o: any) => {
            const price = formatPrice(o.preco);
            const label = MARKETPLACE_LABELS[o.marketplace] ?? o.marketplace;
            return (
              <div
                key={o.id}
                className="flex items-center justify-between bg-white border border-[#E6DED3] rounded-xl px-6 py-4 hover:border-[#C9A84C] transition-all"
              >

                <div>
                  <p className="font-medium text-[#0D1B2A] text-sm">
                    {label}
                  </p>
                  {price ? (
                    <p className="text-xl font-serif font-semibold text-[#4A1628] mt-0.5">
                      R$ {price}
                    </p>
                  ) : (
                    <p className="text-sm text-[#7B5E3A] mt-0.5">
                      Consulte o site
                    </p>
                  )}
                </div>

                <a
                  href={`/api/click/${o.id}`}
                  target="_blank"
                  rel="noopener noreferrer nofollow sponsored"
                  className="px-4 py-2 bg-[#C9A84C] text-[#4A1628] text-sm font-semibold rounded-lg hover:bg-[#e0bc5e] transition-colors"
                >
                  Ver oferta →
                </a>

              </div>
            );
          })}

        </div>

      </section>

      {/* =========================
          LISTAS RELACIONADAS
      ========================== */}
      <section>

        <h2 className="text-xl font-serif font-semibold text-[#0D1B2A] mb-5">
          Este livro aparece nas listas
        </h2>

        {!listas.length && (
          <p className="text-[#7B5E3A] text-sm">
            Ainda não vinculado a listas editoriais.
          </p>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">

          {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
          {listas.map((lista: any) => (
            <a
              key={lista.slug}
              href={`/listas/${lista.slug}`}
              className="group block bg-white border border-[#E6DED3] rounded-xl px-5 py-4 hover:border-[#C9A84C] hover:shadow-sm transition-all"
            >
              <span className="text-[#C9A84C] text-xs font-semibold uppercase tracking-wider mb-1 block">
                Lista editorial
              </span>
              <span className="text-[#0D1B2A] font-serif font-semibold text-sm leading-snug group-hover:text-[#4A1628] transition-colors">
                {lista.titulo}
              </span>
            </a>
          ))}

        </div>

      </section>

    </div>
  );
}
