import type { Metadata } from "next";
import { unstable_cache } from "next/cache";
import { supabase } from "@/lib/supabase";
import Link from "next/link";
import Pagination from "@/app/_components/Pagination";

export const metadata: Metadata = {
  title: "Autores",
  description:
    "Conheça os autores do acervo da Livraria Alexandria. Explore biografias, nacionalidades e todas as obras disponíveis por autor.",
  alternates: { canonical: "/autores" },
};

const ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");
const PAGE_SIZE = 48;

type PageProps = {
  searchParams: Promise<{ letra?: string; page?: string }>;
};

type AutorLista = {
  id: string;
  nome: string;
  slug: string;
  livros_autores: { livro_id: string }[];
};

// A tabela `autores` do Supabase NÃO tem coluna `status_publish`. Usamos inner
// join com livros_autores para listar apenas autores com ao menos um livro
// publicado (evita ~6,7k páginas vazias) e paginamos via .range() para driblar
// o teto de 1000 do PostgREST. O fetch é memoizado no Data Cache — antes a
// varredura completa rodava a cada request (era force-dynamic).
const fetchPublishedAuthors = unstable_cache(
  async (): Promise<AutorLista[]> => {
    const PAGE = 1000;
    const all: AutorLista[] = [];
    for (let from = 0; ; from += PAGE) {
      const { data, error } = await supabase
        .from("autores")
        .select("id, nome, slug, livros_autores!inner(livro_id)")
        .not("nome", "is", null)
        .order("nome")
        .range(from, from + PAGE - 1);
      if (error || !data || data.length === 0) break;
      all.push(...(data as unknown as AutorLista[]));
      if (data.length < PAGE) break;
    }
    return all.filter((a) => (a.nome ?? "").trim() !== "");
  },
  ["autores-index"],
  { revalidate: 3600 },
);

export default async function AutoresPage({ searchParams }: PageProps) {
  const { letra: rawLetra, page: rawPage } = await searchParams;
  const letra = rawLetra?.toUpperCase() ?? "";

  const todosAutores = await fetchPublishedAuthors();

  const letrasComAutores = new Set(
    todosAutores
      .map((a) => a.nome.charAt(0).toUpperCase())
      .filter((c) => /[A-Z]/.test(c))
  );

  const autores = letra
    ? todosAutores.filter((a) => a.nome.toUpperCase().startsWith(letra))
    : todosAutores;

  // Paginação server-side — evita renderizar milhares de autores de uma vez.
  const totalPages = Math.max(1, Math.ceil(autores.length / PAGE_SIZE));
  const currentPage = Math.min(Math.max(1, Number(rawPage) || 1), totalPages);
  const pageItems = autores.slice(
    (currentPage - 1) * PAGE_SIZE,
    currentPage * PAGE_SIZE
  );

  const makeHref = (p: number) => {
    const params = new URLSearchParams();
    if (letra) params.set("letra", letra);
    if (p > 1) params.set("page", String(p));
    const qs = params.toString();
    return qs ? `/autores?${qs}` : "/autores";
  };

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
          {autores.length} {autores.length === 1 ? "autor" : "autores"}
          {letra ? ` com "${letra}"` : ""}
        </p>
      </header>

      {/* Layout com sidebar */}
      <div className="flex gap-8 items-start">

        {/* Sidebar de letras */}
        <nav className="hidden lg:flex flex-col gap-0.5 flex-shrink-0 w-10 sticky top-6">

          <Link
            href="/autores"
            className={`text-xs font-semibold text-center py-1 rounded transition-colors ${
              !letra
                ? "bg-[#4A1628] text-[#C9A84C]"
                : "text-[#7B5E3A] hover:text-[#4A1628]"
            }`}
          >
            Todos
          </Link>

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

            {pageItems.map((autor) => {
              const count = autor.livros_autores?.length ?? 0;
              return (
                <a
                  key={autor.slug}
                  href={`/autores/${autor.slug}`}
                  className="group block bg-white border border-[#E6DED3] rounded-xl px-4 py-4 hover:border-[#C9A84C] hover:shadow-sm transition-all"
                >
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

          <Pagination
            currentPage={currentPage}
            totalPages={totalPages}
            makeHref={makeHref}
          />

        </div>

      </div>

    </div>
  );
}
