export const dynamic = "force-dynamic";

import { supabase } from "@/lib/supabase";

const ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");

type PageProps = {
  searchParams: Promise<{ letra?: string }>;
};

export default async function AutoresPage({ searchParams }: PageProps) {
  const { letra: rawLetra } = await searchParams;
  const letra = rawLetra?.toUpperCase() ?? "";

  const { data: todos } = await supabase
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

  const todosAutores = todos ?? [];

  const letrasComAutores = new Set(
    todosAutores
      .map((a) => a.nome.charAt(0).toUpperCase())
      .filter((c) => /[A-Z]/.test(c))
  );

  const autores = letra
    ? todosAutores.filter((a) => a.nome.toUpperCase().startsWith(letra))
    : todosAutores;

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

        <p className="text-[#4A4A4A] text-sm mt-2">
          {autores.length}{" "}
          {autores.length === 1 ? "autor" : "autores"}
          {letra ? ` com "${letra}"` : ""}
        </p>

      </header>

      {/* Layout com sidebar */}
      <div className="flex gap-8 items-start">

        {/* Sidebar de letras */}
        <nav className="hidden lg:flex flex-col gap-0.5 flex-shrink-0 w-10 sticky top-6">

          <a
            href="/autores"
            className={`text-xs font-semibold text-center py-1 rounded transition-colors ${
              !letra
                ? "bg-[#4A1628] text-[#C9A84C]"
                : "text-[#7B5E3A] hover:text-[#4A1628]"
            }`}
          >
            Todos
          </a>

          {ALPHABET.map((c) => {
            const disponivel = letrasComAutores.has(c);
            const ativa = letra === c;
            return disponivel ? (
              <a
                key={c}
                href={`/autores?letra=${c}`}
                className={`text-xs font-semibold text-center py-1 rounded transition-colors ${
                  ativa
                    ? "bg-[#4A1628] text-[#C9A84C]"
                    : "text-[#0D1B2A] hover:text-[#4A1628]"
                }`}
              >
                {c}
              </a>
            ) : (
              <span
                key={c}
                className="text-xs font-semibold text-center py-1 rounded text-[#C4B9AE] select-none"
              >
                {c}
              </span>
            );
          })}

        </nav>

        {/* Grid de autores */}
        <div className="flex-1 min-w-0">
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">

            {autores.map((autor: any) => {

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

      </div>

    </div>
  );
}
