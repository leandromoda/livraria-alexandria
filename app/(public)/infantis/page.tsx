// ISR: hub de livros infantis renderiza no primeiro acesso e fica em cache no
// edge, revalidando de hora em hora — mesmo padrão das demais rotas públicas.
// Fonte: tabela `livros_infantis` (pipeline paralelo, independente do de livros).
export const revalidate = 3600;

import { unstable_cache } from "next/cache";
import { supabase } from "@/lib/supabase";
import type { Metadata } from "next";
import Image from "next/image";
import { isOptimizableImage } from "@/lib/images";
import Link from "next/link";

const MAX_POR_FAIXA = 12;

// Subcategorias por idade — espelham FAIXAS em scripts/steps/infantis_pipeline.py
const FAIXAS = [
  {
    slug: "0-2-anos",
    titulo: "0 a 2 anos",
    descricao: "Livros de pano, banho e cartonados para os primeiros contatos.",
  },
  {
    slug: "3-5-anos",
    titulo: "3 a 5 anos",
    descricao: "Livros ilustrados para ler junto, na pré-escola.",
  },
  {
    slug: "6-8-anos",
    titulo: "6 a 8 anos",
    descricao: "Primeiros leitores — texto curto e muita ilustração.",
  },
  {
    slug: "9-12-anos",
    titulo: "9 a 12 anos",
    descricao: "Leitores independentes — capítulos, séries e aventuras.",
  },
] as const;

type LivroInfantil = {
  titulo: string;
  slug: string;
  autor: string | null;
  ilustrador: string | null;
  faixa_etaria: string;
  imagem_url: string | null;
};

// Leitura memoizada no Data Cache — o fetch no-store do Supabase impediria o
// ISR de cachear o render. Tolerante à tabela ausente (antes da migração).
const getLivros = unstable_cache(
  async (): Promise<LivroInfantil[]> => {
    const { data } = await supabase
      .from("livros_infantis")
      .select("titulo, slug, autor, ilustrador, faixa_etaria, imagem_url")
      .eq("is_publishable", true)
      .order("titulo");
    return (data as LivroInfantil[] | null) ?? [];
  },
  ["infantis-hub"],
  { revalidate: 3600 },
);

export async function generateMetadata(): Promise<Metadata> {
  const livros = await getLivros();

  return {
    title: "Livros Infantis — por idade",
    description:
      "Livros infantis selecionados por faixa etária, de 0 a 12 anos, com sinopses e as melhores ofertas.",
    alternates: { canonical: "/infantis" },
    ...(livros.length === 0 ? { robots: { index: false } } : {}),
  };
}

export default async function InfantisPage() {
  const livros = await getLivros();

  return (
    <div className="space-y-10">

      {/* =========================
          HEADER
      ========================== */}
      <header className="bg-[#4A1628] rounded-2xl px-8 py-10 text-[#F5F0E8]">

        <p className="text-[#C9A84C] text-xs font-semibold uppercase tracking-widest mb-3">
          Livros Infantis
        </p>

        <h1 className="text-3xl font-serif font-semibold leading-tight mb-3">
          Cada livro na idade certa
        </h1>

        <p className="text-[#C8C0B4] text-sm max-w-2xl">
          Do primeiro livro de pano às primeiras séries de aventura: uma
          seleção organizada por faixa etária, para acertar na escolha.
        </p>

      </header>

      {/* =========================
          SEÇÕES POR FAIXA ETÁRIA
      ========================== */}
      {FAIXAS.map((faixa) => {
        const itens = livros
          .filter((l) => l.faixa_etaria === faixa.slug)
          .slice(0, MAX_POR_FAIXA);

        return (
          <section key={faixa.slug} id={faixa.slug}>

            <h2 className="text-xl font-serif font-semibold text-[#0D1B2A] mb-1">
              {faixa.titulo}
            </h2>

            <p className="text-sm text-[#4A4A4A] mb-5">{faixa.descricao}</p>

            {!itens.length && (
              <p className="text-[#7B5E3A] text-sm">
                Em breve — estamos montando esta prateleira.
              </p>
            )}

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">

              {itens.map((livro) => (
                <Link
                  key={livro.slug}
                  href={`/infantis/${livro.slug}`}
                  className="group flex items-center gap-4 bg-white border border-[#E6DED3] rounded-xl px-5 py-4 hover:border-[#C9A84C] hover:shadow-sm transition-all"
                >

                  {livro.imagem_url ? (
                    <Image
                      src={livro.imagem_url}
                      alt={livro.titulo}
                      width={40}
                      height={56}
                      unoptimized={!isOptimizableImage(livro.imagem_url)}
                      className="flex-shrink-0 w-10 h-14 object-cover rounded border border-[#E6DED3]"
                    />
                  ) : (
                    <div className="flex-shrink-0 w-10 h-14 rounded bg-[#4A1628] flex items-center justify-center">
                      <span className="text-[#C9A84C] text-sm font-serif">A</span>
                    </div>
                  )}

                  <span className="min-w-0">
                    <span className="block font-medium text-sm text-[#0D1B2A] leading-snug group-hover:text-[#4A1628] transition-colors">
                      {livro.titulo}
                    </span>
                    {livro.autor && (
                      <span className="block text-xs text-[#7B5E3A] mt-0.5 truncate">
                        {livro.autor}
                      </span>
                    )}
                  </span>

                </Link>
              ))}

            </div>

          </section>
        );
      })}

    </div>
  );
}
