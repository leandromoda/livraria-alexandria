export const runtime = "edge";

import { createClient } from "@supabase/supabase-js";

export default async function CategoriasPage() {

  const supabase = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
  );

  /**
   * Categorias + contagem
   */
  const { data: categorias } = await supabase
    .from("categorias")
    .select(`
      id,
      nome,
      slug,
      livros_categorias (
        id
      )
    `)
    .order("nome");

  return (
    <main className="p-10 max-w-4xl mx-auto space-y-6">

      <h1 className="text-2xl font-bold">
        Categorias
      </h1>

      <ul className="space-y-3">

        {categorias?.map((cat: any) => {

          const count =
            cat.livros_categorias?.length ?? 0;

          return (

            <li
              key={cat.slug}
              className="flex justify-between border p-4 rounded-lg"
            >

              <a
                href={`/categorias/${cat.slug}`}
                className="text-blue-600 hover:underline font-medium"
              >
                {cat.nome}
              </a>

              <span className="text-sm text-gray-500">
                {count} livros
              </span>

            </li>

          );

        })}

      </ul>

    </main>
  );
}
