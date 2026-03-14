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

  /**
   * Categorias (navegação)
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
    .order("nome")
    .limit(8);

  /**
   * Autores (discovery)
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
    .order("nome")
    .limit(8);

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
          Categorias
      ========================== */}
      <section className="space-y-4">
        <h2 className="text-xl font-semibold">
          Categorias
        </h2>

        <ul className="list-disc list-inside space-y-1">
          {categorias?.map((cat: any) => {
            const count = cat.livros_categorias?.length ?? 0;
            return (
              <li key={cat.slug}>
                <a
                  href={`/categorias/${cat.slug}`}
                  className="text-blue-600 hover:underline"
                >
                  {cat.nome}
                </a>
                <span className="text-sm text-gray-500 ml-2">
                  ({count} livros)
                </span>
              </li>
            );
          })}
        </ul>

        <a
          href="/categorias"
          className="inline-block text-blue-600 font-medium hover:underline"
        >
          Ver todas as categorias →
        </a>
      </section>

      {/* =========================
          Autores
      ========================== */}
      <section className="space-y-4">
        <h2 className="text-xl font-semibold">
          Autores
        </h2>

        <ul className="list-disc list-inside space-y-1">
          {autores?.map((a: any) => {
            const count = a.livros_autores?.length ?? 0;
            return (
              <li key={a.slug}>
                <a
                  href={`/autores/${a.slug}`}
                  className="text-blue-600 hover:underline"
                >
                  {a.nome}
                </a>
                <span className="text-sm text-gray-500 ml-2">
                  ({count} livros)
                </span>
              </li>
            );
          })}
        </ul>

        <a
          href="/autores"
          className="inline-block text-blue-600 font-medium hover:underline"
        >
          Ver todos os autores →
        </a>
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
