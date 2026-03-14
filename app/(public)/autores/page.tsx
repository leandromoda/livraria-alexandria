export const runtime = "edge";

import { createClient } from "@supabase/supabase-js";

export default async function AutoresPage() {

  const supabase = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
  );

  /**
   * Autores + contagem de livros
   */
  const { data: autores } = await supabase
    .from("autores")
    .select(`
      id,
      nome,
      slug,
      livros_autores (
        livro_id
      )
    `)
    .order("nome");

  return (
    <main className="p-10 max-w-4xl mx-auto space-y-6">

      <h1 className="text-2xl font-bold">
        Autores
      </h1>

      <ul className="space-y-3">

        {autores?.map((autor: any) => {

          const count = autor.livros_autores?.length ?? 0;

          return (

            <li
              key={autor.slug}
              className="flex justify-between border p-4 rounded-lg"
            >

              <a
                href={`/autores/${autor.slug}`}
                className="text-blue-600 hover:underline font-medium"
              >
                {autor.nome}
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
