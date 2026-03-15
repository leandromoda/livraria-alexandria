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
    <div className="space-y-8">

      {/* Header */}
      <header>

        <p className="text-[#C9A84C] text-xs font-semibold uppercase tracking-widest mb-2">
          Navegação
        </p>

        <h1 className="text-3xl font-serif font-semibold text-[#0D1B2A]">
          Autores
        </h1>

      </header>

      {/* Grid */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">

        {autores?.map((autor: any) => {

          const count = autor.livros_autores?.length ?? 0;

          return (

            <a
              key={autor.slug}
              href={`/autores/${autor.slug}`}
              className="group block bg-white border border-[#E6DED3] rounded-xl px-4 py-4 hover:border-[#C9A84C] hover:shadow-sm transition-all"
            >

              {/* Inicial */}
              <div className="w-9 h-9 rounded-full bg-[#4A1628] flex items-center justify-center mb-3">
                <span className="text-[#C9A84C] text-sm font-serif font-semibold">
                  {autor.nome.charAt(0).toUpperCase()}
                </span>
              </div>

              <span className="block font-medium text-[#0D1B2A] text-sm leading-snug group-hover:text-[#4A1628] transition-colors">
                {autor.nome}
              </span>

              <span className="text-xs text-[#7B5E3A] mt-1 block">
                {count} {count === 1 ? "livro" : "livros"}
              </span>

            </a>

          );

        })}

      </div>

    </div>
  );
}
