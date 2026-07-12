import { unstable_cache } from "next/cache";
import { supabase } from "@/lib/supabase";
import type { Metadata } from "next";
import Image from "next/image";
import { isOptimizableImage } from "@/lib/images";
import Link from "next/link";
import Pagination from "@/app/_components/Pagination";

export const metadata: Metadata = {
  title: "Livros",
  description:
    "Explore todos os livros com sinopses, autores e as melhores ofertas disponíveis.",
  alternates: { canonical: "/livros" },
};

const ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");
const PAGE_SIZE = 48;

type PageProps = {
  searchParams: Promise<{ q?: string; letra?: string; page?: string }>;
};

type LivroLista = {
  titulo: string;
  slug: string;
  imagem_url: string | null;
  autor: string | null;
};

// A página lê searchParams (q/letra) e por isso renderiza no servidor sob
// demanda — o que preserva SEO (todos os links no HTML) e mantém o payload
// pequeno (só o subconjunto filtrado). O custo antes era refazer a varredura
// completa do catálogo no Supabase a cada request; agora o fetch é memoizado
// no Data Cache (unstable_cache, revalida de hora em hora).
const fetchAllPublishableBooks = unstable_cache(
  async (): Promise<LivroLista[]> => {
    const PAGE = 1000;
    const all: LivroLista[] = [];
    for (let from = 0; ; from += PAGE) {
      const { data, error } = await supabase
        .from("livros")
        .select("titulo, slug, imagem_url, autor")
        .eq("is_publishable", true)
        .not("titulo", "is", null)
        .order("titulo")
        .range(from, from + PAGE - 1);
      if (error || !data || data.length === 0) break;
      all.push(...(data as LivroLista[]));
      if (data.length < PAGE) break;
    }
    return all.filter((l) => (l.titulo ?? "").trim() !== "");
  },
  ["livros-index"],
  { revalidate: 3600 },
);

export default async function LivrosIndex({ searchParams }: PageProps) {
  const { q: rawQ, letra: rawLetra, page: rawPage } = await searchParams;
  const q = rawQ?.trim() ?? "";
  const letra = rawLetra?.toUpperCase() ?? "";

  const todos = await fetchAllPublishableBooks();

  const letrasComLivros = new Set(
    todos
      .map((l) => l.titulo.charAt(0).toUpperCase())
      .filter((c) => /[A-Z]/.test(c))
  );

  let livros = todos;

  if (q) {
    const qLower = q.toLowerCase();
    livros = livros.filter(
      (l) =>
        l.titulo.toLowerCase().includes(qLower) ||
        (l.autor ?? "").toLowerCase().includes(qLower)
    );
  } else if (letra) {
    livros = livros.filter((l) => l.titulo.toUpperCase().startsWith(letra));
  }

  // Paginação server-side: renderizar o catálogo inteiro (>3400 itens) gerava
  // um HTML de vários MB e render lento. Aqui servimos PAGE_SIZE por vez.
  const totalPages = Math.max(1, Math.ceil(livros.length / PAGE_SIZE));
  const currentPage = Math.min(
    Math.max(1, Number(rawPage) || 1),
    totalPages
  );
  const pageItems = livros.slice(
    (currentPage - 1) * PAGE_SIZE,
    currentPage * PAGE_SIZE
  );

  const makeHref = (p: number) => {
    const params = new URLSearchParams();
    if (q) params.set("q", q);
    if (letra) params.set("letra", letra);
    if (p > 1) params.set("page", String(p));
    const qs = params.toString();
    return qs ? `/livros?${qs}` : "/livros";
  };

  const totalLabel = q
    ? `${livros.length} ${livros.length === 1 ? "resultado" : "resultados"} para "${q}"`
    : letra
      ? `${livros.length} ${livros.length === 1 ? "livro" : "livros"} com "${letra}"`
      : `${livros.length} ${livros.length === 1 ? "livro" : "livros"} no catálogo`;

  return (
    <div className="space-y-8">

      {/* HEADER */}
      <header>
        <p className="text-[#C9A84C] text-xs font-semibold uppercase tracking-widest mb-2">
          Catálogo
        </p>
        <h1 className="text-3xl font-serif font-semibold text-[#0D1B2A]">
          {q ? "Resultados da busca" : "Todos os livros"}
        </h1>
        <p className="text-[#4A4A4A] text-sm mt-2">{totalLabel}</p>
      </header>

      {/* LAYOUT COM SIDEBAR */}
      <div className="flex gap-8 items-start">

        {/* Sidebar de letras */}
        {!q && (
          <nav className="hidden lg:flex flex-col gap-0.5 flex-shrink-0 w-10 sticky top-6">

            <Link
              href="/livros"
              className={`text-xs font-semibold text-center py-1 rounded transition-colors ${
                !letra
                  ? "bg-[#4A1628] text-[#C9A84C]"
                  : "text-[#7B5E3A] hover:text-[#4A1628]"
              }`}
            >
              Todos
            </Link>

            {ALPHABET.map((c) => {
              const disponivel = letrasComLivros.has(c);
              const ativa = letra === c;
              return disponivel ? (
                <a
                  key={c}
                  href={`/livros?letra=${c}`}
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
                  className="text-xs font-semibold text-center py-1 rounded text-[#E6DED3] select-none"
                >
                  {c}
                </span>
              );
            })}

          </nav>
        )}

        {/* Lista de livros */}
        <div className="flex-1 min-w-0">

          <div className="divide-y divide-[#E6DED3]">

          {livros.length === 0 && q && (
            <p className="text-sm text-[#4A4A4A] py-4">
              Nenhum livro encontrado para &ldquo;{q}&rdquo;. Tente outros termos.
            </p>
          )}

          {livros.length === 0 && letra && !q && (
            <p className="text-sm text-[#4A4A4A] py-4">
              Nenhum livro encontrado com a letra &ldquo;{letra}&rdquo;.
            </p>
          )}

          {pageItems.map((l) => (
            <a
              key={l.slug}
              href={`/livros/${l.slug}`}
              className="flex gap-4 items-center py-4 px-2 rounded-xl hover:bg-white hover:shadow-sm transition-all group"
            >

              {/* Capa */}
              <div className="flex-shrink-0 w-10 h-14 overflow-hidden rounded border border-[#E6DED3] bg-[#4A1628] flex items-center justify-center">
                {l.imagem_url ? (
                  <Image
                    src={l.imagem_url}
                    alt={l.titulo}
                    width={40}
                    height={56}
                    unoptimized={!isOptimizableImage(l.imagem_url)}
                    className="w-full h-full object-cover"
                  />
                ) : (
                  <span className="text-[#C9A84C] text-sm font-serif">A</span>
                )}
              </div>

              {/* Texto */}
              <div className="leading-tight">
                <p className="font-serif font-semibold text-[#0D1B2A] group-hover:text-[#4A1628] transition-colors">
                  {l.titulo}
                </p>
                {l.autor && (
                  <p className="text-sm text-[#7B5E3A] mt-0.5">
                    {l.autor}
                  </p>
                )}
              </div>

            </a>
          ))}

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
