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

  const { data: autor } = await supabase
    .from("autores")
    .select("nome, nacionalidade")
    .eq("slug", slug)
    .single();

  if (!autor) return {};

  return {
    title: autor.nome,
    description: `Livros de ${autor.nome}${autor.nacionalidade ? `, escritor(a) ${autor.nacionalidade}` : ""} disponíveis na Livraria Alexandria.`,
    alternates: { canonical: `/autores/${slug}` },
  };
}

export default async function AutorPage({ params }: PageProps) {
  const { slug } = await params;

  /**
   * Autor
   */
  const { data: autor } = await supabase
    .from("autores")
    .select("id, nome, slug, nacionalidade")
    .eq("slug", slug)
    .single();

  if (!autor) return notFound();

  /**
   * Livros do autor
   */
  const { data: livrosPivot } = await supabase
    .from("livros_autores")
    .select("livros ( id, titulo, slug, imagem_url )")
    .eq("autor_id", autor.id);

  const livros = livrosPivot?.map((l: any) => l.livros) ?? [];

  return (
    <div className="space-y-10">

      {/* =========================
          HEADER
      ========================== */}
      <header className="flex items-start gap-6">

        {/* Avatar */}
        <div className="flex-shrink-0 w-16 h-16 rounded-full bg-[#4A1628] flex items-center justify-center">
          <span className="text-[#C9A84C] text-2xl font-serif font-semibold">
            {autor.nome.charAt(0).toUpperCase()}
          </span>
        </div>

        <div>

          <p className="text-[#C9A84C] text-xs font-semibold uppercase tracking-widest mb-1">
            <a href="/autores" className="hover:opacity-80 transition-opacity">Autores</a>
            {" "}/ {autor.nome}
          </p>

          <h1 className="text-3xl font-serif font-semibold text-[#0D1B2A] leading-tight">
            {autor.nome}
          </h1>

          <div className="flex items-center gap-3 mt-2">

            {autor.nacionalidade && (
              <span className="text-xs bg-[#F5F0E8] border border-[#E6DED3] text-[#7B5E3A] px-3 py-1 rounded-full">
                {autor.nacionalidade}
              </span>
            )}

            <span className="text-xs bg-[#F5F0E8] border border-[#E6DED3] text-[#7B5E3A] px-3 py-1 rounded-full">
              {livros.length} {livros.length === 1 ? "livro" : "livros"}
            </span>

          </div>

        </div>

      </header>

      {/* =========================
          LIVROS DO AUTOR
      ========================== */}
      <section>

        <h2 className="text-xl font-serif font-semibold text-[#0D1B2A] mb-5">
          Livros
        </h2>

        {!livros.length && (
          <p className="text-[#7B5E3A] text-sm">
            Nenhum livro publicado ainda.
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
