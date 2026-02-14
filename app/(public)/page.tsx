export const runtime = "edge";

import { createClient } from "@supabase/supabase-js";

export default async function Home() {
  const supabase = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
  );

  /**
   * Listas (hub primário SEO)
   */
  const { data: listas } = await supabase
    .from("listas")
    .select("titulo, slug")
    .limit(6);

  /**
   * Livros (discovery)
   */
  const { data: livros } = await supabase
    .from("livros")
    .select("titulo, slug")
    .limit(6);

  /**
   * Ofertas (monetização)
   */
  const { data: ofertas } = await supabase
    .from("ofertas")
    .select(`
      id,
      livros (
        titulo,
        slug
      )
    `)
    .eq("ativa", true)
    .limit(6);

  return (
    <main className="p-10 max-w-3xl mx-auto space-y-10">

      {/* =========================
          Header + Nav
      ========================== */}
      <header className="space-y-4">

        <h1 className="text-3xl font-bold">
          Livraria Alexandria
        </h1>

        <p className="text-lg text-gray-700">
          [livros].
        </p>

        {/* NAV PRIMÁRIA */}
        <nav className="flex gap-6 pt-2 text-blue-600 font-medium">
          <a href="/listas" className="hover:underline">
            Ver todas as listas →
          </a>

          <a href="/livros" className="hover:underline">
            Ver todos os livros →
          </a>
        </nav>

      </header>

      {/* =========================
          Listas
      ========================== */}
      <section className="space-y-4">
        <h2 className="text-xl font-semibold">
          Listas recomendadas
        </h2>

        <ul className="list-disc list-inside space-y-1">
          {listas?.map((l) => (
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
          Livros
      ========================== */}
      <section className="space-y-4">
        <h2 className="text-xl font-semibold">
          Livros em destaque
        </h2>

        <ul className="list-disc list-inside space-y-1">
          {livros?.map((l) => (
            <li key={l.slug}>
              <a
                href={`/livros/${l.slug}`}
                className="text-blue-600 hover:underline"
              >
                {l.titulo}
              </a>
            </li>
          ))}
        </ul>
      </section>

      {/* =========================
          Ofertas
      ========================== */}
      <section className="space-y-4">
        <h2 className="text-xl font-semibold">
          Ofertas ativas
        </h2>

        <ul className="list-disc list-inside space-y-1">
          {ofertas?.map((o: any) => (
            <li key={o.id}>
              <a
                href={`/livros/${o.livros.slug}`}
                className="text-blue-600 hover:underline"
              >
                {o.livros.titulo}
              </a>
            </li>
          ))}
        </ul>
      </section>

    </main>
  );
}
