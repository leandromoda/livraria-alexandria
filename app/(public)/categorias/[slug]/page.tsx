import { notFound } from "next/navigation";
import { supabase } from "@/lib/supabase";
import type { Metadata } from "next";

type PageProps = {
  params: Promise<{ slug: string }>;
};

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { slug } = await params;

  const { data: categoria } = await supabase
    .from("categorias")
    .select("nome")
    .eq("slug", slug)
    .single();

  if (!categoria) return {};

  return {
    title: categoria.nome,
    description: `Explore livros de ${categoria.nome} com sinopses e as melhores ofertas.`,
    alternates: { canonical: `/categorias/${slug}` },
  };
}

export default async function CategoriaPage({ params }: PageProps) {
  const { slug } = await params;

  /**
   * Categoria
   */
  const { data: categoria } = await supabase
    .from("categorias")
    .select("id, nome, slug")
    .eq("slug", slug)
    .single();

  if (!categoria) return notFound();

  /**
   * Listas editoriais
   */
  const { data: listasEditorial } = await supabase
    .from("listas_categorias")
    .select("weight, listas ( titulo, slug )")
    .eq("categoria_id", categoria.id)
    .order("weight", { ascending: false });

  const editoriais = listasEditorial?.map((l: any) => l.listas) ?? [];

  /**
   * Livros da categoria
   */
  const { data: livrosPivot } = await supabase
    .from("livros_categorias")
    .select("livros ( id, titulo, slug, imagem_url )")
    .eq("categoria_id", categoria.id);

  const livros = livrosPivot?.map((l: any) => l.livros) ?? [];

  /**
   * Listas automáticas
   */
  const livroIds = livros.map((l: any) => l.id);
  let automaticas: any[] = [];

  if (livroIds.length) {
    const { data: listasAuto } = await supabase
      .from("lista_livros")
      .select("listas ( titulo, slug )")
      .in("livro_id", livroIds)
      .limit(5);

    automaticas = listasAuto?.map((l: any) => l.listas) ?? [];
  }

  /**
   * Merge sem duplicar
   */
  const slugsEditorial = new Set(editoriais.map((l) => l.slug));
  const listas = [
    ...editoriais,
    ...automaticas.filter((l) => !slugsEditorial.has(l.slug)),
  ];

  return (
    <div className="space-y-10">

      {/* =========================
          HEADER
      ========================== */}
      <header className="bg-[#4A1628] rounded-2xl px-8 py-10 text-[#F5F0E8]">

        <p className="text-[#C9A84C] text-xs font-semibold uppercase tracking-widest mb-3">
          <a href="/categorias" className="hover:opacity-80 transition-opacity">Categorias</a>
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

          {livros.map((livro: any) => (
            <a
              key={livro.slug}
              href={`/livros/${livro.slug}`}
              className="group flex items-center gap-4 bg-white border border-[#E6DED3] rounded-xl px-5 py-4 hover:border-[#C9A84C] hover:shadow-sm transition-all"
            >

              {livro.imagem_url ? (
                <img
                  src={livro.imagem_url}
                  alt={livro.titulo}
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
