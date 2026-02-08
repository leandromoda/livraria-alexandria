export const runtime = "edge";

import { notFound } from "next/navigation";
import { createClient } from "@supabase/supabase-js";

type PageProps = {
  params: Promise<{
    slug: string;
  }>;
};

export default async function LivroPage({
  params,
}: PageProps) {
  const { slug } = await params;

  const supabase = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
  );

  /**
   * Livro
   */
  const { data: livro } = await supabase
    .from("livros")
    .select("*")
    .eq("slug", slug)
    .single();

  if (!livro) {
    notFound();
  }

  /**
   * Ofertas
   */
  const { data: ofertas } = await supabase
    .from("ofertas")
    .select(`
      id,
      preco,
      url_afiliada,
      marketplace
    `)
    .eq("livro_id", livro.id)
    .eq("ativa", true);

  /**
   * Listas onde o livro aparece
   */
  const { data: listasPivot } = await supabase
    .from("lista_livros")
    .select(`
      listas (
        titulo,
        slug
      )
    `)
    .eq("livro_id", livro.id);

  const listas =
    listasPivot?.map((l: any) => l.listas) ?? [];

  return (
    <main className="max-w-3xl mx-auto px-6 py-10 space-y-10">
      {/* =========================
          Livro
      ========================== */}
      <section className="space-y-4">
        <h1 className="text-3xl font-bold">
          {livro.titulo}
        </h1>

        {livro.autor && (
          <p className="text-lg text-gray-600">
            por {livro.autor}
          </p>
        )}

        {livro.descricao && (
          <p className="text-gray-800 leading-relaxed">
            {livro.descricao}
          </p>
        )}
      </section>

      {/* =========================
          Listas relacionadas
      ========================== */}
      <section className="space-y-4">
        <h2 className="text-2xl font-semibold">
          Este livro aparece nas listas
        </h2>

        {!listas.length && (
          <p className="text-gray-500">
            Ainda não vinculado a listas editoriais.
          </p>
        )}

        <ul className="list-disc list-inside space-y-1">
          {listas.map((lista) => (
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
          Ofertas
      ========================== */}
      <section className="space-y-4">
        <h2 className="text-2xl font-semibold">
          Onde comprar
        </h2>

        {!ofertas?.length && (
          <p className="text-gray-500">
            Nenhuma oferta disponível no momento.
          </p>
        )}

        <ul className="space-y-3">
          {ofertas?.map((o) => (
            <li
              key={o.id}
              className="border p-4 rounded-lg flex items-center justify-between"
            >
              <div>
                <p className="font-medium">
                  {o.marketplace}
                </p>

                <p className="text-lg font-bold">
                  R$ {o.preco}
                </p>
              </div>

              <a
                href={`/api/click/${o.id}`}
                target="_blank"
                className="text-sm text-green-600 hover:underline"
              >
                Ver oferta →
              </a>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
