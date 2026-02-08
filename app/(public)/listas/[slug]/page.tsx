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
    <main className="max-w-3xl mx-auto px-6 py-10 space-y-8">
      {/* Schema */}
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify(schema),
        }}
      />

      {/* Header */}
      <header className="space-y-4">
        <h1 className="text-3xl font-bold">
          {lista.titulo}
        </h1>

        <p className="text-lg text-gray-700">
          {lista.introducao}
        </p>
      </header>

      {/* Ranking */}
      <section className="space-y-6">
        {livros?.map((item: any) => (
          <article
            key={item.livros.id}
            className="space-y-2"
          >
            <h2 className="text-xl font-semibold">
              {item.posicao}.{" "}
              <a
                href={`/livros/${item.livros.slug}`}
                className="text-blue-600 hover:underline"
              >
                {item.livros.titulo}
              </a>
            </h2>

            <p className="text-sm text-gray-600">
              por {item.livros.autor}
            </p>
          </article>
        ))}
      </section>
    </main>
  );
}
