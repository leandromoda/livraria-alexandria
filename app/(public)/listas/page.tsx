// ISR: listas publicadas mudam quando o pipeline publica, não a cada request.
export const revalidate = 3600;

import type { Metadata } from "next";
import { unstable_cache } from "next/cache";
import { supabase } from "@/lib/supabase";
import Pagination from "@/app/_components/Pagination";

export const metadata: Metadata = {
  title: "Listas editoriais",
  description:
    "Seleções temáticas de livros organizadas por gênero, época e estilo. Encontre sua próxima leitura nas listas editoriais da Livraria Alexandria.",
  alternates: { canonical: "/listas" },
};

const PAGE_SIZE = 48;

type PageProps = {
  searchParams: Promise<{ page?: string }>;
};

type ListaRow = {
  id: string;
  titulo: string;
  slug: string;
  introducao: string | null;
  lista_livros: { livro_id: string }[];
};

// A tabela `listas` do Supabase NÃO tem coluna `status_publish` (o filtro antigo
// .eq("status_publish", true) dava erro 400). Ela só recebe listas publicadas;
// usamos inner join com lista_livros para trazer só listas com livros e
// paginamos via .range() para não perder listas no teto de 1000 do PostgREST.
const fetchPublishedLists = unstable_cache(
  async (): Promise<ListaRow[]> => {
    const PAGE = 1000;
    const all: ListaRow[] = [];
    for (let from = 0; ; from += PAGE) {
      const { data, error } = await supabase
        .from("listas")
        .select("id, titulo, slug, introducao, lista_livros!inner(livro_id)")
        .order("titulo")
        .range(from, from + PAGE - 1);
      if (error || !data || data.length === 0) break;
      all.push(...(data as unknown as ListaRow[]));
      if (data.length < PAGE) break;
    }
    return all;
  },
  ["listas-index"],
  { revalidate: 3600 },
);

export default async function ListasPage({ searchParams }: PageProps) {
  const { page: rawPage } = await searchParams;

  const todas = await fetchPublishedLists();

  // Apenas listas com livros (válidas).
  const listas = todas
    .map((l) => ({ ...l, livro_count: l.lista_livros?.length ?? 0 }))
    .filter((l) => l.livro_count > 0);

  // Paginação server-side — 612 cards com introdução geravam ~1,2 MB de HTML.
  const totalPages = Math.max(1, Math.ceil(listas.length / PAGE_SIZE));
  const currentPage = Math.min(Math.max(1, Number(rawPage) || 1), totalPages);
  const pageItems = listas.slice(
    (currentPage - 1) * PAGE_SIZE,
    currentPage * PAGE_SIZE
  );

  const makeHref = (p: number) => (p > 1 ? `/listas?page=${p}` : "/listas");

  return (
    <div className="space-y-8">

      {/* Header */}
      <header>
        <p className="text-[#C9A84C] text-xs font-semibold uppercase tracking-widest mb-2">
          Navegação
        </p>
        <h1 className="text-3xl font-serif font-semibold text-[#0D1B2A]">
          Listas editoriais
        </h1>
        <p className="text-[#4A4A4A] text-sm mt-2">
          {listas.length}{" "}
          {listas.length === 1 ? "lista disponível" : "listas disponíveis"}
        </p>
      </header>

      {/* Grid de listas */}
      {!listas.length ? (
        <p className="text-sm text-[#4A4A4A]">
          Nenhuma lista disponível no momento.
        </p>
      ) : (
        <>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">

          {pageItems.map((l) => (
            <a
              key={l.slug}
              href={`/listas/${l.slug}`}
              className="group block bg-white border border-[#E6DED3] rounded-xl px-5 py-5 hover:border-[#C9A84C] hover:shadow-sm transition-all"
            >
              <div className="flex items-center justify-between mb-2">
                <span className="text-[#C9A84C] text-xs font-semibold uppercase tracking-wider">
                  Lista editorial
                </span>
                <span className="text-xs text-[#7B5E3A] bg-[#F5F0E8] px-2 py-0.5 rounded-full border border-[#E6DED3] flex-shrink-0 ml-2">
                  {l.livro_count} {l.livro_count === 1 ? "livro" : "livros"}
                </span>
              </div>

              <span className="block text-[#0D1B2A] font-serif font-semibold text-base leading-snug group-hover:text-[#4A1628] transition-colors mb-2">
                {l.titulo}
              </span>

              {l.introducao && (
                <span className="block text-[#4A4A4A] text-xs leading-relaxed line-clamp-2">
                  {l.introducao}
                </span>
              )}
            </a>
          ))}

        </div>

        <Pagination
          currentPage={currentPage}
          totalPages={totalPages}
          makeHref={makeHref}
        />
        </>
      )}

    </div>
  );
}
