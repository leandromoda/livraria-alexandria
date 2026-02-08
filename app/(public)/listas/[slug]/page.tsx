export const runtime = "edge";

import { notFound } from "next/navigation";
import { supabase } from "@/lib/supabase";

type PageProps = {
  params: Promise<{
    slug: string;
  }>;
};

export default async function ListaPage({ params }: PageProps) {
  const { slug } = await params;

  /**
   * 1) Buscar a lista pelo slug
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
   * 2) Buscar listas relacionadas (pivot → ids → listas)
   */
  const { data: relacionadasPivot } = await supabase
    .from("listas_relacionadas")
    .select("lista_destino_id")
    .eq("lista_origem_id", lista.id);

  let listasRelacionadas: any[] = [];

  if (relacionadasPivot?.length) {
    const ids = relacionadasPivot.map(
      (r) => r.lista_destino_id
    );

    const { data } = await supabase
      .from("listas")
      .select("titulo, slug")
      .in("id", ids);

    listasRelacionadas = data ?? [];
  }

  /**
   * 3) Buscar livros da lista
   */
  const { data: livros } = await supabase
    .from("lista_livros")
    .select(`
      posicao,
      nota_editorial,
      livros (
        id,
        titulo,
        slug,
        autor
      )
    `)
    .eq("lista_id", lista.id)
    .order("posicao", { ascending: true });

  return (
    <main className="max-w-3xl mx-auto px-6 py-10 space-y-8">
      {/* =========================
          Cabeçalho
      ========================== */}
      <header className="space-y-4">
        <h1 className="text-3xl font-bold">
          {lista.titulo}
        </h1>

        <p className="text-lg text-gray-700">
          {lista.introducao}
        </p>
      </header>

      {/* =========================
          Listas relacionadas
      ========================== */}
      <section className="space-y-3">
        <h2 className="text-xl font-semibold">
          Veja também
        </h2>

        {!listasRelacionadas.length && (
          <p className="text-gray-500 text-sm">
            Ainda não há listas relacionadas.
          </p>
        )}

        <ul className="list-disc list-inside space-y-1">
          {listasRelacionadas.map((l) => (
            <li key={l.slug}>
              <a
                href={`/listas/${l.slug}`}
                className="text-blue-600 hover:underline"
              >
                {l.titulo}
              </a>
            </li>
          ))}
        </ul>
      </section>

      {/* =========================
          Ranking
      ========================== */}
      <section className="space-y-6">
        {livros?.map((item: any) => (
          <article key={item.livros.id} className="space-y-2">
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

            {item.nota_editorial && (
              <p className="text-gray-800">
                {item.nota_editorial}
              </p>
            )}
          </article>
        ))}
      </section>

      {/* =========================
          Aviso legal
      ========================== */}
      <footer className="pt-10 text-sm text-gray-500">
        Este site pode receber comissões por compras realizadas
        através dos links, sem custo adicional para você.
      </footer>
    </main>
  );
}
