// ISR: hub de jogos renderiza no primeiro acesso e fica em cache no edge,
// revalidando de hora em hora — mesmo padrão das demais rotas públicas.
// Fonte: tabela `jogos` (pipeline paralelo — independente do catálogo de livros).
export const revalidate = 3600;

import { unstable_cache } from "next/cache";
import { supabase } from "@/lib/supabase";
import type { Metadata } from "next";
import Image from "next/image";
import { isOptimizableImage } from "@/lib/images";
import Link from "next/link";

const MAX_POR_SECAO = 12;

const SECOES = [
  {
    slug: "rpg",
    titulo: "RPG",
    descricao: "Livros de regras, aventuras e suplementos de RPG de mesa.",
  },
  {
    slug: "jogos-de-tabuleiro",
    titulo: "Jogos de Tabuleiro",
    descricao: "Estratégia, jogos em família e clássicos modernos.",
  },
  {
    slug: "jogos-de-cartas",
    titulo: "Jogos de Cartas",
    descricao: "Card games, deck-building e jogos rápidos de mesa.",
  },
] as const;

type JogoCard = {
  titulo: string;
  slug: string;
  autor: string | null;
  categoria: string;
  imagem_url: string | null;
};

// Leituras memoizadas no Data Cache — o fetch no-store do Supabase impediria
// o ISR de cachear o render; unstable_cache torna o dado cacheável.
// Tolerante à tabela ausente (antes da migração SQL): erro → lista vazia.
const getJogos = unstable_cache(
  async (): Promise<JogoCard[]> => {
    const { data } = await supabase
      .from("jogos")
      .select("titulo, slug, autor, categoria, imagem_url")
      .eq("is_publishable", true)
      .order("titulo");
    return (data as JogoCard[] | null) ?? [];
  },
  ["jogos-hub"],
  { revalidate: 3600 },
);

export async function generateMetadata(): Promise<Metadata> {
  const jogos = await getJogos();

  return {
    title: "Jogos — RPG, Tabuleiro e Cartas",
    description:
      "Explore RPGs de mesa, jogos de tabuleiro e jogos de cartas com as melhores ofertas.",
    alternates: { canonical: "/jogos" },
    ...(jogos.length === 0 ? { robots: { index: false } } : {}),
  };
}

export default async function JogosPage() {
  const jogos = await getJogos();

  return (
    <div className="space-y-10">

      {/* =========================
          HEADER
      ========================== */}
      <header className="bg-[#4A1628] rounded-2xl px-8 py-10 text-[#F5F0E8]">

        <p className="text-[#C9A84C] text-xs font-semibold uppercase tracking-widest mb-3">
          Jogos
        </p>

        <h1 className="text-3xl font-serif font-semibold leading-tight mb-3">
          RPG, tabuleiro e cartas
        </h1>

        <p className="text-[#C8C0B4] text-sm max-w-2xl">
          Uma estante além dos livros: RPGs de mesa, jogos de tabuleiro e card
          games selecionados, com ofertas nos principais marketplaces.
        </p>

      </header>

      {/* =========================
          SEÇÕES POR CATEGORIA
      ========================== */}
      {SECOES.map((secao) => {
        const itens = jogos
          .filter((j) => j.categoria === secao.slug)
          .slice(0, MAX_POR_SECAO);

        return (
          <section key={secao.slug}>

            <h2 className="text-xl font-serif font-semibold text-[#0D1B2A] mb-1">
              {secao.titulo}
            </h2>

            <p className="text-sm text-[#4A4A4A] mb-5">{secao.descricao}</p>

            {!itens.length && (
              <p className="text-[#7B5E3A] text-sm">
                Em breve — estamos montando esta prateleira.
              </p>
            )}

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">

              {itens.map((jogo) => (
                <Link
                  key={jogo.slug}
                  href={`/jogos/${jogo.slug}`}
                  className="group flex items-center gap-4 bg-white border border-[#E6DED3] rounded-xl px-5 py-4 hover:border-[#C9A84C] hover:shadow-sm transition-all"
                >

                  {jogo.imagem_url ? (
                    <Image
                      src={jogo.imagem_url}
                      alt={jogo.titulo}
                      width={48}
                      height={48}
                      unoptimized={!isOptimizableImage(jogo.imagem_url)}
                      className="flex-shrink-0 w-12 h-12 object-cover rounded border border-[#E6DED3]"
                    />
                  ) : (
                    <div className="flex-shrink-0 w-12 h-12 rounded bg-[#4A1628] flex items-center justify-center">
                      <span className="text-[#C9A84C] text-sm font-serif">A</span>
                    </div>
                  )}

                  <span className="min-w-0">
                    <span className="block font-medium text-sm text-[#0D1B2A] leading-snug group-hover:text-[#4A1628] transition-colors">
                      {jogo.titulo}
                    </span>
                    {jogo.autor && (
                      <span className="block text-xs text-[#7B5E3A] mt-0.5 truncate">
                        {jogo.autor}
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
