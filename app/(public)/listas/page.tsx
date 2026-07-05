export const dynamic = "force-dynamic";

import type { Metadata } from "next";
import { supabase } from "@/lib/supabase";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Listas editoriais",
  description:
    "Seleções temáticas de livros organizadas por gênero, época e estilo. Encontre sua próxima leitura nas listas editoriais da Livraria Alexandria.",
};

type PageProps = {
  searchParams: Promise<{ categoria?: string }>;
};

type ListaRow = {
  id: string;
  titulo: string;
  slug: string;
  introducao: string | null;
  lista_livros: { livro_id: string }[];
};

// A tabela `listas` do Supabase NÃO tem coluna `status_publish` — o filtro
// antigo .eq("status_publish", true) causava erro 400 e a página mostrava
// "0 listas". A tabela só recebe listas publicadas (upsert do pipeline);
// usamos inner join com lista_livros para trazer só listas com livros e
// paginamos via .range() para não perder listas no teto de 1000 do PostgREST.
async function fetchPublishedLists(): Promise<ListaRow[]> {
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
}

export default async function ListasPage({ searchParams }: PageProps) {
  const { categoria: rawCategoria } = await searchParams;
  const categoriaAtiva = rawCategoria?.trim() ?? "";

  const todasListasData = await fetchPublishedLists();

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const todasListas: any[] = todasListasData.map((l) => ({
    ...l,
    livro_count: l.lista_livros?.length ?? 0,
    macrocategoria: null,
  }));

  // Apenas listas com livros (válidas)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const listasValidas = todasListas.filter((l: any) => l.livro_count > 0);

  /* Macrocategorias disponíveis (campo opcional — degrade se ausente) */
  const macrocategorias = [
    ...new Set(
      listasValidas
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        .map((l: any) => l.macrocategoria as string | null)
        .filter((c): c is string => !!c)
    ),
  ].sort();

  const temSidebar = macrocategorias.length > 0;

  const listas = categoriaAtiva
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ? listasValidas.filter((l: any) => l.macrocategoria === categoriaAtiva)
    : listasValidas;

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
          {listas.length === 1
            ? "lista disponível"
            : "listas disponíveis"}
          {categoriaAtiva ? ` em ${categoriaAtiva}` : ""}
        </p>

      </header>

      {/* Layout com sidebar */}
      <div className="flex gap-8 items-start">

        {/* Sidebar de macrocategorias */}
        {temSidebar && (
          <nav className="hidden lg:flex flex-col gap-1 flex-shrink-0 w-44 sticky top-6">

            <Link
              href="/listas"
              className={`text-sm px-3 py-2 rounded-lg transition-colors ${
                !categoriaAtiva
                  ? "bg-[#4A1628] text-[#C9A84C] font-semibold"
                  : "text-[#4A4A4A] hover:text-[#4A1628] hover:bg-[#F5F0E8]"
              }`}
            >
              Todas
            </Link>

            {macrocategorias.map((cat) => (
              <a
                key={cat}
                href={`/listas?categoria=${encodeURIComponent(cat)}`}
                className={`text-sm px-3 py-2 rounded-lg transition-colors ${
                  categoriaAtiva === cat
                    ? "bg-[#4A1628] text-[#C9A84C] font-semibold"
                    : "text-[#4A4A4A] hover:text-[#4A1628] hover:bg-[#F5F0E8]"
                }`}
              >
                {cat}
              </a>
            ))}

          </nav>
        )}

        {/* Grid de listas */}
        <div className="flex-1 min-w-0">

          {!listas.length ? (
            <p className="text-sm text-[#4A4A4A]">
              Nenhuma lista disponível no momento.
            </p>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">

              {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
              {listas.map((l: any) => (

                <a
                  key={l.slug}
                  href={`/listas/${l.slug}`}
                  className="group block bg-white border border-[#E6DED3] rounded-xl px-5 py-5 hover:border-[#C9A84C] hover:shadow-sm transition-all"
                >

                  <div className="flex items-center justify-between mb-2">
                    <span className="text-[#C9A84C] text-xs font-semibold uppercase tracking-wider">
                      {l.macrocategoria ?? "Lista editorial"}
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
          )}

        </div>

      </div>

    </div>
  );
}
