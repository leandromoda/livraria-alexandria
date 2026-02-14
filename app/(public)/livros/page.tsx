export const runtime = "edge";

import { createClient } from "@supabase/supabase-js";

export default async function LivrosIndex() {
  const supabase = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
  );

  const { data: livros } = await supabase
    .from("livros")
    .select("titulo, slug, imagem_url, autor")
    .order("titulo");

  return (
    <main className="p-10 max-w-4xl mx-auto space-y-6">

      <h1 className="text-2xl font-bold">
        Todos os livros
      </h1>

      <ul className="divide-y">

        {livros?.map((l) => (

          <li key={l.slug} className="py-4">

            <a
              href={`/livros/${l.slug}`}
              className="flex gap-4 items-center hover:bg-gray-50 p-2 rounded"
            >

              {/* CAPA MINI */}
              <div className="w-12 h-16 bg-gray-100 flex-shrink-0 overflow-hidden rounded">

                {l.imagem_url ? (
                  <img
                    src={l.imagem_url}
                    alt={l.titulo}
                    className="w-full h-full object-cover"
                  />
                ) : (
                  <div className="w-full h-full flex items-center justify-center text-[10px] text-gray-400">
                    —
                  </div>
                )}

              </div>

              {/* TEXTO */}
              <div className="leading-tight">

                <p className="font-medium">
                  {l.titulo}
                </p>

                {l.autor && (
                  <p className="text-sm text-gray-500">
                    {l.autor}
                  </p>
                )}

              </div>

            </a>

          </li>

        ))}

      </ul>

    </main>
  );
}
