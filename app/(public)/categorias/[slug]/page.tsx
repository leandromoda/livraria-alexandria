// ISR on-demand: página de categoria renderiza no primeiro acesso e fica em
// cache no edge, revalidando a cada 24h. generateStaticParams vazio
// habilita o ISR sem prerenderizar todos os slugs no build.
//
// TTL subiu de 1h para 24h em 2026-07-26 para conter a cota do free tier da
// Vercel — rationale e medição em app/(public)/livros/[slug]/page.tsx.
export const revalidate = 86400; // 24h
export async function generateStaticParams() {
  return [];
}

import { notFound } from "next/navigation";
import { unstable_cache } from "next/cache";
import { supabase } from "@/lib/supabase";
import type { Metadata } from "next";
import Image from "next/image";
import { isOptimizableImage } from "@/lib/images";
import Link from "next/link";

type PageProps = {
  params: Promise<{ slug: string }>;
};

// Leituras memoizadas no Data Cache — o fetch no-store do Supabase impediria o
// ISR on-demand de cachear o render; unstable_cache torna o dado cacheável
// (chave = slug/categoria_id) e o render vira static-eligible → HIT no edge.
const getCategoria = unstable_cache(
  async (slug: string) => {
    const { data } = await supabase
      .from("categorias")
      .select("id, nome, slug, livros_categorias(livro_id)")
      .eq("slug", slug)
      .single();
    return data;
  },
  ["categoria-detalhe"],
  { revalidate: 86400 },
);

// Conteúdo dependente (listas editoriais + livros + listas automáticas) numa
// única entrada de cache por categoria — evita usar o array de livroIds como
// chave de cache (variável e potencialmente enorme).
const getCategoriaConteudo = unstable_cache(
  async (categoriaId: string) => {
    const { data: listasEditorial } = await supabase
      .from("listas_categorias")
      .select("weight, listas ( titulo, slug )")
      .eq("categoria_id", categoriaId)
      .order("weight", { ascending: false });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const editoriais = listasEditorial?.map((l: any) => l.listas) ?? [];

    // `livrosQueryFailed` distingue QUERY FALHA de categoria realmente sem
    // livro. A distincao existe porque a pagina 404a categoria sem livro
    // publicavel: engolir o erro como lista vazia (o antigo `?? []` sozinho)
    // faria uma falha transitoria do Supabase virar 404 — e, com revalidate de
    // 24h, esse 404 ficaria CACHEADO por um dia numa categoria legitima. Mesma
    // armadilha que o #263 evitou nas paginas de autor.
    const { data: livrosPivot, error: livrosError } = await supabase
      .from("livros_categorias")
      .select("livros ( id, titulo, slug, imagem_url, is_publishable )")
      .eq("categoria_id", categoriaId);
    const livrosQueryFailed = Boolean(livrosError);
    const livros = (livrosPivot ?? [])
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      .map((l: any) => l.livros)
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      .filter((l: any) => l?.is_publishable === true);

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const livroIds = livros.map((l: any) => l.id);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let automaticas: any[] = [];
    if (livroIds.length) {
      const { data: listasAuto } = await supabase
        .from("lista_livros")
        .select("listas ( titulo, slug )")
        .in("livro_id", livroIds)
        .limit(5);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      automaticas = listasAuto?.map((l: any) => l.listas) ?? [];
    }

    return { editoriais, livros, automaticas, livrosQueryFailed };
  },
  ["categoria-conteudo"],
  { revalidate: 86400 },
);

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { slug } = await params;

  const categoria = await getCategoria(slug);

  if (!categoria) return {};

  const temLivros = (categoria.livros_categorias?.length ?? 0) > 0;

  return {
    title: categoria.nome,
    description: `Explore livros de ${categoria.nome} com sinopses e as melhores ofertas.`,
    alternates: { canonical: `/categorias/${slug}` },
    ...(!temLivros ? { robots: { index: false } } : {}),
  };
}

export default async function CategoriaPage({ params }: PageProps) {
  const { slug } = await params;

  /**
   * Categoria
   */
  const categoria = await getCategoria(slug);

  if (!categoria) return notFound();

  /**
   * Listas editoriais + livros + listas automáticas (cacheados juntos)
   */
  const { editoriais, livros, automaticas, livrosQueryFailed } =
    await getCategoriaConteudo(categoria.id);

  // Categoria sem nenhum livro publicavel nao tem pagina: 404.
  //
  // Antes isto respondia 200 com `robots: noindex`. Mas noindex desindexa e NAO
  // impede o crawl — e, pior, mantinha o bucket "Excluida pela tag noindex"
  // vivo: em 2026-08-20 a validacao desse bucket (604 URLs) voltou FALHA no
  // GSC, e o unico exemplo rastreado depois do #263 era
  // `/categorias/mentalidade-financeira` (14/08), ainda 200 + noindex. As
  // outras 594 URLs eram `/autores/*` obsoletas (nenhuma rastreada depois de
  // 08/08). Sao 6 de 170 categorias sem livro publicavel (medido 2026-08-20 via
  // PostgREST: educacao-financeira, economia, mentalidade-financeira,
  // estoicismo-filosofia, estrategia, politica-economia) — ja fora do sitemap
  // (inner join no pivot) e do indice /categorias (filtro count > 0), entao o
  // 404 fecha a ultima porta de crawl. Mesmo rationale do #263.
  //
  // `livrosQueryFailed` significa QUERY FALHA, nao ausencia de livro — nesse
  // caso nao 404a, para nao cachear um 404 de 24h em cima de erro transitorio.
  if (!livrosQueryFailed && livros.length === 0) return notFound();

  /**
   * Merge sem duplicar
   */
  const seenSlugs = new Set(editoriais.map((l) => l.slug));
  const listas = [
    ...editoriais,
    ...automaticas.filter((l) => {
      if (seenSlugs.has(l.slug)) return false;
      seenSlugs.add(l.slug);
      return true;
    }),
  ];

  return (
    <div className="space-y-10">

      {/* =========================
          HEADER
      ========================== */}
      <header className="bg-[#4A1628] rounded-2xl px-8 py-10 text-[#F5F0E8]">

        <p className="text-[#C9A84C] text-xs font-semibold uppercase tracking-widest mb-3">
          <Link href="/categorias" className="hover:opacity-80 transition-opacity">Categorias</Link>
          {" "}/ {categoria.nome}
        </p>

        <h1 className="text-3xl font-serif font-semibold leading-tight mb-3">
          {categoria.nome}
        </h1>

        <p className="text-[#C8C0B4] text-sm">
          {livros.length} {livros.length === 1 ? "livro" : "livros"} nesta categoria
        </p>

      </header>

      {/* =========================
          LISTAS RELACIONADAS
      ========================== */}
      <section>

        <h2 className="text-xl font-serif font-semibold text-[#0D1B2A] mb-5">
          Listas relacionadas
        </h2>

        {!listas.length && (
          <p className="text-[#7B5E3A] text-sm">
            Nenhuma lista relacionada ainda.
          </p>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">

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

      {/* =========================
          LIVROS DA CATEGORIA
      ========================== */}
      <section>

        <h2 className="text-xl font-serif font-semibold text-[#0D1B2A] mb-5">
          Livros da categoria
        </h2>

        {!livros.length && (
          <p className="text-[#7B5E3A] text-sm">
            Nenhum livro nesta categoria ainda.
          </p>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">

          {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
          {livros.map((livro: any) => (
            <a
              key={livro.slug}
              href={`/livros/${livro.slug}`}
              className="group flex items-center gap-4 bg-white border border-[#E6DED3] rounded-xl px-5 py-4 hover:border-[#C9A84C] hover:shadow-sm transition-all"
            >

              {livro.imagem_url ? (
                <Image
                  src={livro.imagem_url}
                  alt={livro.titulo}
                  width={40}
                  height={56}
                  unoptimized={!isOptimizableImage(livro.imagem_url)}
                  className="flex-shrink-0 w-10 h-14 object-cover rounded border border-[#E6DED3]"
                />
              ) : (
                <div className="flex-shrink-0 w-10 h-14 rounded bg-[#4A1628] flex items-center justify-center">
                  <span className="text-[#C9A84C] text-sm font-serif">A</span>
                </div>
              )}

              <span className="font-medium text-sm text-[#0D1B2A] leading-snug group-hover:text-[#4A1628] transition-colors">
                {livro.titulo}
              </span>

            </a>
          ))}

        </div>

      </section>

    </div>
  );
}
