export const runtime = "edge";

import { notFound } from "next/navigation";
import { createClient } from "@supabase/supabase-js";

type PageProps = {
  params: Promise<{
    slug: string;
  }>;
};

export default async function AutorPage({
  params,
}: PageProps) {

  const { slug } = await params;

  const supabase = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
  );

  /**
   * =========================
   * Autor
   * =========================
   */
  const { data: autor } = await supabase
    .from("autores")
    .select("id, nome, slug, nacionalidade")
    .eq("slug", slug)
    .single();

  if (!autor) return notFound();

  /**
   * =========================
   * Livros do autor
   * =========================
   */
  const { data: livrosPivot } = await supabase
    .from("livros_autores")
    .select(`
      livros (
        id,
        titulo,
        slug,
        imagem_url
      )
    `)
    .eq("autor_id", autor.id);

  const livros = livrosPivot?.map((l: any) => l.livros) ?? [];

  return (
    <main className="p-10 max-w-5xl mx-auto space-y-10">

      {/* =========================
          Header
      ========================== */}
      <section className="space-y-2">

        <h1 className="text-3xl font-bold">
          {autor.nome}
        </h1>

        {autor.nacionalidade && (
          <p className="text-gray-600">
            {autor.nacionalidade}
          </p>
        )}

        <p className="text-gray-500 text-sm">
          {livros.length} livro{livros.length !== 1 ? "s" : ""} publicado{livros.length !== 1 ? "s" : ""}
        </p>

      </section>

      {/* =========================
          Livros
      ========================== */}
      <section className="space-y-4">

        <h2 className="text-xl font-semibold">
          Livros
        </h2>

        {!livros.length && (
          <p className="text-gray-500">
            Nenhum livro publicado ainda.
          </p>
        )}

        <ul className="space-y-4">

          {livros.map((livro: any) => (

            <li
              key={livro.slug}
              className="flex items-center gap-4 border p-4 rounded-lg"
            >

              {livro.imagem_url && (
                <img
                  src={livro.imagem_url}
                  alt={livro.titulo}
                  className="w-12 h-16 object-cover rounded"
                />
              )}

              <a
                href={`/livros/${livro.slug}`}
                className="text-blue-600 hover:underline font-medium"
              >
                {livro.titulo}
              </a>

            </li>

          ))}

        </ul>

      </section>

    </main>
  );
}
