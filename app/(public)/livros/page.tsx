export const dynamic = "force-dynamic";

import { supabase } from "@/lib/supabase";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Livros",
  description:
    "Explore todos os livros com sinopses, autores e as melhores ofertas disponíveis.",
};

type PageProps = {
  searchParams: Promise<{ q?: string }>;
};

export default async function LivrosIndex({ searchParams }: PageProps) {
  const { q: rawQ } = await searchParams;
  const q = rawQ?.trim() ?? "";

  let query = supabase
    .from("livros")
    .select("titulo, slug, imagem_url, autor")
    .order("titulo");

  if (q) {
    query = query.or(`titulo.ilike.%${q}%,autor.ilike.%${q}%`);
  }

  const { data: livros } = await query;

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

        {q ? (
          <p className="text-[#4A4A4A] text-sm mt-2">
            {livros?.length ?? 0}{" "}
            {(livros?.length ?? 0) === 1 ? "resultado" : "resultados"} para{" "}
            <span className="font-medium text-[#0D1B2A]">"{q}"</span>
          </p>
        ) : (
          <p className="text-[#4A4A4A] text-sm mt-2">
            {livros?.length ?? 0}{" "}
            {(livros?.length ?? 0) === 1 ? "livro" : "livros"} no catálogo
          </p>
        )}

      </header>

      {/* =========================
          LISTA
      ========================== */}
      <div className="divide-y divide-[#E6DED3]">

        {livros?.length === 0 && q && (
          <p className="text-sm text-[#4A4A4A] py-4">
            Nenhum livro encontrado para "{q}". Tente outros termos.
          </p>
        )}

        {livros?.map((l) => (
          <a
            key={l.slug}
            href={`/livros/${l.slug}`}
            className="flex gap-4 items-center py-4 px-2 rounded-xl hover:bg-white hover:shadow-sm transition-all group"
          >

            {/* Capa */}
            <div className="flex-shrink-0 w-10 h-14 overflow-hidden rounded border border-[#E6DED3] bg-[#4A1628] flex items-center justify-center">
              {l.imagem_url ? (
                <img
                  src={l.imagem_url}
                  alt={l.titulo}
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
  );
}
