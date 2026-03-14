export const runtime = "edge";

import { notFound } from "next/navigation";
import { supabase } from "@/lib/supabase";

type PageProps = {
  params: Promise<{
    slug: string;
  }>;
};

export default async function ListaPage({
  params,
}: PageProps) {
  const { slug } = await params;

  /**
   * Lista
   */
  const { data: lista } = await supabase
    .from("listas")
    .select("id, titulo, introducao")
    .eq("slug", slug)
    .single();

  if (!lista) {
    notFound();
  }

  /**
   * Livros
   */
  const { data: livros } = await supabase
    .from("lista_livros")
    .select(`
      posicao,
      livros (
        id,
        titulo,
        slug,
        autor,
        imagem_url
      )
    `)
    .eq("lista_id", lista.id)
    .order("posicao", { ascending: true });

  /**
   * =========================
   * Schema.org ItemList
   * =========================
   */
  const schema = {
    "@context": "https://schema.org",
    "@type": "ItemList",
    name: lista.titulo,
    description: lista.introducao,
    itemListElement: livros?.map(
      (item: any, index: number) => ({
        "@type": "ListItem",
        position: index + 1,
        item: {
          "@type": "Book",
          name: item.livros.titulo,
          image:
            item.livros.imagem_url || undefined,
          author: {
            "@type": "Person",
            name: item.livros.autor,
          },
        },
      })
    ),
  };

  return (
    <div className="max-w-3xl mx-auto space-y-10">

      {/* Schema */}
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify(schema),
        }}
      />

      {/* =========================
          HEADER DA LISTA
      ========================== */}
      <header className="bg-[#4A1628] rounded-2xl px-8 py-10 text-[#F5F0E8]">

        <p className="text-[#C9A84C] text-xs font-semibold uppercase tracking-widest mb-3">
          <a href="/listas" className="hover:opacity-80 transition-opacity">Listas</a>
          {" "}/ Lista editorial
        </p>

        <h1 className="text-3xl font-serif font-semibold leading-tight mb-4">
          {lista.titulo}
        </h1>

        {lista.introducao && (
          <p className="text-[#C8C0B4] text-base leading-relaxed">
            {lista.introducao}
          </p>
        )}

        <p className="text-[#C9A84C] text-sm font-medium mt-5">
          {livros?.length ?? 0} livros nesta lista
        </p>

      </header>

      {/* =========================
          RANKING DE LIVROS
      ========================== */}
      <section className="space-y-4">

        {livros?.map((item: any) => (

          <article
            key={item.livros.id}
            className="flex items-start gap-5 bg-white border border-[#E6DED3] rounded-xl px-6 py-5 hover:border-[#C9A84C] hover:shadow-sm transition-all group"
          >

            {/* Número */}
            <span className="flex-shrink-0 w-8 h-8 rounded-full bg-[#F5F0E8] border border-[#E6DED3] flex items-center justify-center text-sm font-semibold text-[#7B5E3A]">
              {item.posicao}
            </span>

            {/* Capa (se houver) */}
            {item.livros.imagem_url && (
              <img
                src={item.livros.imagem_url}
                alt={item.livros.titulo}
                className="flex-shrink-0 w-12 h-16 object-cover rounded-md border border-[#E6DED3]"
              />
            )}

            {/* Dados */}
            <div className="flex-1 min-w-0">

              <h2 className="text-base font-serif font-semibold text-[#0D1B2A] leading-snug group-hover:text-[#4A1628] transition-colors">
                <a href={`/livros/${item.livros.slug}`}>
                  {item.livros.titulo}
                </a>
              </h2>

              {item.livros.autor && (
                <p className="text-sm text-[#4A4A4A] mt-1">
                  por {item.livros.autor}
                </p>
              )}

            </div>

            {/* CTA */}
            <a
              href={`/livros/${item.livros.slug}`}
              className="flex-shrink-0 text-xs text-[#C9A84C] font-semibold hover:underline"
            >
              Ver →
            </a>

          </article>

        ))}

      </section>

    </div>
  );
}
