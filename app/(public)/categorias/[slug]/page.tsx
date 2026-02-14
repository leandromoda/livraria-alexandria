export const runtime = "edge";

import { notFound } from "next/navigation";
import { createClient } from "@supabase/supabase-js";

type PageProps = {
  params: Promise<{
    slug: string;
  }>;
};

export default async function CategoriaPage({
  params,
}: PageProps) {

  const { slug } = await params;

  const supabase = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
  );

  /**
   * =========================
   * Categoria
   * =========================
   */
  const { data: categoria } = await supabase
    .from("categorias")
    .select("id, nome, slug")
    .eq("slug", slug)
    .single();

  if (!categoria) return notFound();

  /**
   * =========================
   * Listas editoriais
   * =========================
   */
  const { data: listasEditorial } = await supabase
    .from("listas_categorias")
    .select(`
      weight,
      listas (
        titulo,
        slug
      )
    `)
    .eq("categoria_id", categoria.id)
    .order("weight", { ascending: false });

  const editoriais =
    listasEditorial?.map((l: any) => l.listas) ?? [];

  /**
   * =========================
   * Livros da categoria
   * =========================
   */
  const { data: livrosPivot } = await supabase
    .from("livros_categorias")
    .select(`
      livros (
        id,
        titulo,
        slug,
        imagem_url
      )
    `)
    .eq("categoria_id", categoria.id);

  const livros =
    livrosPivot?.map((l: any) => l.livros) ?? [];

  /**
   * =========================
   * Listas automáticas
   * =========================
   */
  const livroIds = livros.map((l: any) => l.id);

  let automaticas: any[] = [];

  if (livroIds.length) {

    const { data: listasAuto } = await supabase
      .from("lista_livros")
      .select(`
        listas (
          titulo,
          slug
        )
      `)
      .in("livro_id", livroIds)
      .limit(5);

    automaticas =
      listasAuto?.map((l: any) => l.listas) ?? [];
  }

  /**
   * =========================
   * Merge sem duplicar
   * =========================
   */
  const slugsEditorial =
    new Set(editoriais.map((l) => l.slug));

  const listas = [
    ...editoriais,
    ...automaticas.filter(
      (l) => !slugsEditorial.has(l.slug)
    ),
  ];

  return (
    <main className="p-10 max-w-5xl mx-auto space-y-10">

      {/* =========================
          Header
      ========================== */}
      <section className="space-y-2">

        <h1 className="text-3xl font-bold">
          {categoria.nome}
        </h1>

        <p className="text-gray-600">
          Livros classificados nesta categoria.
        </p>

      </section>

      {/* =========================
          Listas relacionadas
      ========================== */}
      <section className="space-y-4">

        <h2 className="text-xl font-semibold">
          Listas relacionadas
        </h2>

        {!listas.length && (
          <p className="text-gray-500">
            Nenhuma lista relacionada ainda.
          </p>
        )}

        <ul className="list-disc list-inside space-y-1">

          {listas.map((lista: any) => (

            <li key={lista.slug}>

              <a
                href={`/listas/${lista.slug}`}
                className="text-blue-600 hover:underline"
              >
                {lista.titulo}
              </a>

            </li>

          ))}

        </ul>

      </section>

      {/* =========================
          Livros
      ========================== */}
      <section className="space-y-4">

        <h2 className="text-xl font-semibold">
          Livros da categoria
        </h2>

        {!livros.length && (
          <p className="text-gray-500">
            Nenhum livro nesta categoria ainda.
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
