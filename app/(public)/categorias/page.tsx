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
    <div className="space-y-8">

      {/* Header */}
      <header>

        <p className="text-[#C9A84C] text-xs font-semibold uppercase tracking-widest mb-2">
          Navegação
        </p>

        <h1 className="text-3xl font-serif font-semibold text-[#0D1B2A]">
          Categorias
        </h1>

      </header>

      {/* Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">

        {categorias?.map((cat: any) => {

          const count =
            cat.livros_categorias?.length ?? 0;

          return (

            <a
              key={cat.slug}
              href={`/categorias/${cat.slug}`}
              className="group flex items-center justify-between bg-white border border-[#E6DED3] rounded-xl px-5 py-4 hover:border-[#C9A84C] hover:shadow-sm transition-all"
            >

              <span className="font-medium text-[#0D1B2A] group-hover:text-[#4A1628] transition-colors text-sm">
                {cat.nome}
              </span>

              <span className="text-xs text-[#7B5E3A] bg-[#F5F0E8] px-2.5 py-1 rounded-full border border-[#E6DED3]">
                {count} livros
              </span>

            </a>

          );

        })}

      </div>

    </div>
  );
}
