export const dynamic = "force-dynamic";

import { supabase } from "@/lib/supabase";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Livros",
  description:
    "Explore todos os livros com sinopses, autores e as melhores ofertas disponíveis.",
};

export default async function LivrosIndex() {
  const { data: livros } = await supabase
    .from("livros")
    .select("titulo, slug, imagem_url, autor")
    .order("titulo");

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
          Todos os livros
        </h1>

        <p className="text-[#4A4A4A] text-sm mt-2">
          {livros?.length ?? 0} {(livros?.length ?? 0) === 1 ? "livro" : "livros"} no catálogo
        </p>

      </header>

      {/* =========================
          LISTA
      ========================== */}
      <div className="divide-y divide-[#E6DED3]">

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
