export const dynamic = "force-dynamic";

import { supabase } from "@/lib/supabase";
import type { Metadata } from "next";
import Image from "next/image";
import { isOptimizableImage } from "@/lib/images";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Livros",
  description:
    "Explore todos os livros com sinopses, autores e as melhores ofertas disponíveis.",
  alternates: { canonical: "/livros" },
};

const ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");

type PageProps = {
  searchParams: Promise<{ q?: string; letra?: string }>;
};

type LivroLista = {
  titulo: string;
  slug: string;
  imagem_url: string | null;
  autor: string | null;
};

// O PostgREST retorna no máximo 1000 linhas por request. O catálogo tem
// >3400 livros publicados; sem paginação, o índice mostrava só os 1000
// primeiros. Aqui paginamos via .range() até esgotar e descartamos registros
// sem título (dado inconsistente que renderizava um card quebrado no topo).
async function fetchAllPublishableBooks(): Promise<LivroLista[]> {
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
}

export default async function LivrosIndex({ searchParams }: PageProps) {
  const { q: rawQ, letra: rawLetra } = await searchParams;
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

  const totalLabel = q
    ? `${livros.length} ${livros.length === 1 ? "resultado" : "resultados"} para "${q}"`
    : letra
      ? `${livros.length} ${livros.length === 1 ? "livro" : "livros"} com "${letra}"`
      : `${livros.length} ${livros.length === 1 ? "livro" : "livros"} no catálogo`;

  return (
    <div className="space-y-8">

      {/* =========================
          HEADER
      ========================== */}
      <header>

        <p className="text-[#C9A84C] text-xs font-semibold uppercase tracking-widest mb-2">
          Catálogo
        </p>

        <h1 className="text-3xl font-serif font-semibold text-[#0D1B2A]">
          {q ? "Resultados da busca" : "Todos os livros"}
        </h1>

        <p className="text-[#4A4A4A] text-sm mt-2">{totalLabel}</p>

      </header>

      {/* =========================
          LAYOUT COM SIDEBAR
      ========================== */}
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
        <div className="flex-1 min-w-0 divide-y divide-[#E6DED3]">

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

          {livros.map((l) => (
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

      </div>

    </div>
  );
}
