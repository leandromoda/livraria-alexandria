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
    <div className="space-y-16">

      {/* =========================
          HERO
      ========================== */}
      <section className="relative rounded-2xl overflow-hidden bg-[#4A1628] px-10 py-14 text-[#F5F0E8]">

        <div className="relative z-10 max-w-xl">

          <p className="text-[#C9A84C] text-sm font-semibold uppercase tracking-widest mb-3">
            Livraria Alexandria
          </p>

          <h1 className="text-4xl font-serif font-semibold leading-tight mb-4">
            Descubra sua próxima grande leitura
          </h1>

          <p className="text-[#C8C0B4] text-base mb-8 leading-relaxed">
            Listas editoriais, sinopses e as melhores ofertas em literatura nacional e internacional.
          </p>

          <div className="flex flex-wrap gap-3">

            <a
              href="/listas"
              className="px-5 py-2.5 bg-[#C9A84C] text-[#4A1628] text-sm font-semibold rounded-lg hover:bg-[#e0bc5e] transition-colors"
            >
              Ver listas
            </a>

            <a
              href="/livros"
              className="px-5 py-2.5 border border-[#C8C0B4] text-[#F5F0E8] text-sm font-semibold rounded-lg hover:border-[#C9A84C] hover:text-[#C9A84C] transition-colors"
            >
              Explorar livros
            </a>

          </div>

        </div>

        {/* Decorative element */}
        <div className="absolute right-10 top-8 text-[#6B2238] text-[160px] font-serif leading-none select-none pointer-events-none opacity-40">
          A
        </div>

      </section>

      {/* =========================
          LISTAS
      ========================== */}
      <section>

        <div className="flex items-center justify-between mb-6">

          <h2 className="text-2xl font-serif font-semibold text-[#0D1B2A]">
            Listas recomendadas
          </h2>

          <a href="/listas" className="text-sm text-[#C9A84C] font-medium hover:underline">
            Ver todas →
          </a>

        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">

          {listas?.map((l) => (
            <a
              key={l.slug}
              href={`/listas/${l.slug}`}
              className="group block bg-white border border-[#E6DED3] rounded-xl px-5 py-4 hover:border-[#C9A84C] hover:shadow-sm transition-all"
            >

              <span className="text-[#C9A84C] text-xs font-semibold uppercase tracking-wider mb-2 block">
                Lista editorial
              </span>

              <span className="text-[#0D1B2A] font-serif font-semibold text-base leading-snug group-hover:text-[#4A1628] transition-colors">
                {l.titulo}
              </span>

            </a>
          ))}

        </div>

      </section>

      {/* =========================
          LIVROS
      ========================== */}
      <section>

        <div className="flex items-center justify-between mb-6">

          <h2 className="text-2xl font-serif font-semibold text-[#0D1B2A]">
            Livros em destaque
          </h2>

          <a href="/livros" className="text-sm text-[#C9A84C] font-medium hover:underline">
            Ver todos →
          </a>

        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">

          {livros?.map((l) => (
            <a
              key={l.slug}
              href={`/livros/${l.slug}`}
              className="group block bg-white border border-[#E6DED3] rounded-xl px-5 py-4 hover:border-[#C9A84C] hover:shadow-sm transition-all"
            >

              <span className="text-[#0D1B2A] font-medium text-sm leading-snug group-hover:text-[#4A1628] transition-colors">
                {l.titulo}
              </span>

            </a>
          ))}

        </div>

      </section>

      {/* =========================
          CATEGORIAS
      ========================== */}
      <section>

        <div className="flex items-center justify-between mb-6">

          <h2 className="text-2xl font-serif font-semibold text-[#0D1B2A]">
            Categorias
          </h2>

          <a href="/categorias" className="text-sm text-[#C9A84C] font-medium hover:underline">
            Ver todas →
          </a>

        </div>

        <div className="flex flex-wrap gap-3">

          {categorias?.map((cat: any) => {
            const count = cat.livros_categorias?.length ?? 0;
            return (
              <a
                key={cat.slug}
                href={`/categorias/${cat.slug}`}
                className="inline-flex items-center gap-2 px-4 py-2 bg-white border border-[#E6DED3] rounded-full text-sm text-[#0D1B2A] font-medium hover:border-[#C9A84C] hover:text-[#4A1628] transition-all"
              >
                {cat.nome}
                <span className="text-xs text-[#7B5E3A] bg-[#F5F0E8] px-1.5 py-0.5 rounded-full">
                  {count}
                </span>
              </a>
            );
          })}

        </div>

      </section>

      {/* =========================
          AUTORES
      ========================== */}
      <section>

        <div className="flex items-center justify-between mb-6">

          <h2 className="text-2xl font-serif font-semibold text-[#0D1B2A]">
            Autores
          </h2>

          <a href="/autores" className="text-sm text-[#C9A84C] font-medium hover:underline">
            Ver todos →
          </a>

        </div>

        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">

          {autores?.map((a: any) => {
            const count = a.livros_autores?.length ?? 0;
            return (
              <a
                key={a.slug}
                href={`/autores/${a.slug}`}
                className="group block bg-white border border-[#E6DED3] rounded-xl px-4 py-3 hover:border-[#C9A84C] hover:shadow-sm transition-all"
              >

                <span className="block text-[#0D1B2A] font-medium text-sm group-hover:text-[#4A1628] transition-colors">
                  {a.nome}
                </span>

                <span className="text-xs text-[#7B5E3A] mt-1 block">
                  {count} {count === 1 ? "livro" : "livros"}
                </span>

              </a>
            );
          })}

        </div>

      </section>

      {/* =========================
          OFERTAS
      ========================== */}
      <section>

        <div className="flex items-center justify-between mb-6">

          <h2 className="text-2xl font-serif font-semibold text-[#0D1B2A]">
            Ofertas ativas
          </h2>

          <a href="/ofertas" className="text-sm text-[#C9A84C] font-medium hover:underline">
            Ver todas →
          </a>

        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">

          {ofertas?.map((o: any) => (
            <a
              key={o.id}
              href={`/livros/${o.livros.slug}`}
              className="group flex items-center gap-3 bg-white border border-[#E6DED3] rounded-xl px-5 py-4 hover:border-[#C9A84C] hover:shadow-sm transition-all"
            >

              <span className="flex-shrink-0 w-2 h-2 rounded-full bg-[#C9A84C]" />

              <span className="text-[#0D1B2A] font-medium text-sm leading-snug group-hover:text-[#4A1628] transition-colors">
                {o.livros.titulo}
              </span>

            </a>
          ))}

        </div>

      </section>

    </div>
  );
}
