// ISR on-demand: cada jogo renderiza no primeiro acesso e fica em cache no
// edge, revalidando de hora em hora (mesmo padrão de /livros/[slug]).
export const revalidate = 3600;
export async function generateStaticParams() {
  return [];
}

import { notFound } from "next/navigation";
import { unstable_cache } from "next/cache";
import { supabase } from "@/lib/supabase";
import type { Metadata } from "next";
import Image from "next/image";
import { isOptimizableImage } from "@/lib/images";
import Link from "next/link";

type PageProps = {
  params: Promise<{ slug: string }>;
};

const CATEGORIA_LABELS: Record<string, string> = {
  rpg: "RPG",
  "jogos-de-tabuleiro": "Jogos de Tabuleiro",
  "jogos-de-cartas": "Jogos de Cartas",
};

const MARKETPLACE_LABELS: Record<string, string> = {
  amazon: "Amazon",
  mercadolivre: "Mercado Livre",
  mercado_livre: "Mercado Livre",
};

const getJogo = unstable_cache(
  async (slug: string) => {
    const { data } = await supabase
      .from("jogos")
      .select("*")
      .eq("slug", slug)
      .eq("is_publishable", true)
      .single();
    return data;
  },
  ["jogo-detalhe"],
  { revalidate: 3600 },
);

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { slug } = await params;
  const jogo = await getJogo(slug);

  if (!jogo) return {};

  const description =
    jogo.descricao?.slice(0, 160) ??
    `Sinopse, ofertas e informações sobre ${jogo.titulo}.`;

  return {
    title: jogo.titulo,
    description,
    alternates: { canonical: `/jogos/${slug}` },
    openGraph: {
      title: jogo.titulo,
      description,
      ...(jogo.imagem_url ? { images: [{ url: jogo.imagem_url }] } : {}),
    },
  };
}

function formatPrice(value: unknown): string | null {
  const num = Number(value);
  if (!value || num === 0) return null;
  return num.toLocaleString("pt-BR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export default async function JogoPage({ params }: PageProps) {
  const { slug } = await params;
  const jogo = await getJogo(slug);

  if (!jogo) return notFound();

  const categoriaLabel = CATEGORIA_LABELS[jogo.categoria] ?? "Jogos";
  const marketplaceLabel =
    MARKETPLACE_LABELS[jogo.marketplace ?? ""] ?? "loja parceira";
  const preco = formatPrice(jogo.preco_atual);
  const ofertaAtiva = Boolean(jogo.url_afiliada) && jogo.offer_status !== "unavailable";

  // Google exige offers/review/aggregateRating em todo Product — sem preço não há Offer válido
  const ofertaJsonLd =
    ofertaAtiva && jogo.preco_atual
      ? {
          "@type": "Offer" as const,
          price: Number(jogo.preco_atual),
          priceCurrency: "BRL",
          availability: "https://schema.org/InStock",
        }
      : undefined;

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "Product",
    name: jogo.titulo,
    ...(jogo.descricao ? { description: jogo.descricao } : {}),
    ...(jogo.imagem_url ? { image: jogo.imagem_url } : {}),
    ...(jogo.autor ? { brand: { "@type": "Brand", name: jogo.autor } } : {}),
    category: categoriaLabel,
    ...(ofertaJsonLd ? { offers: ofertaJsonLd } : {}),
  };

  return (
    <div className="space-y-10">

      {/* Schema JSON-LD — só renderiza quando há offers para satisfazer requisito do Google */}
      {ofertaJsonLd && (
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
        />
      )}

      {/* =========================
          BREADCRUMB
      ========================== */}
      <p className="text-[#C9A84C] text-xs font-semibold uppercase tracking-widest">
        <Link href="/jogos" className="hover:opacity-80 transition-opacity">
          Jogos
        </Link>{" "}
        / {categoriaLabel}
      </p>

      {/* =========================
          CABEÇALHO DO JOGO
      ========================== */}
      <div className="flex flex-col sm:flex-row gap-8">

        {/* Imagem */}
        <div className="flex-shrink-0 w-40 h-40 overflow-hidden rounded-xl border border-[#E6DED3] bg-[#4A1628] flex items-center justify-center">
          {jogo.imagem_url ? (
            <Image
              src={jogo.imagem_url}
              alt={jogo.titulo}
              width={160}
              height={160}
              priority
              unoptimized={!isOptimizableImage(jogo.imagem_url)}
              className="w-full h-full object-cover"
            />
          ) : (
            <span className="text-[#C9A84C] text-3xl font-serif">A</span>
          )}
        </div>

        {/* Texto */}
        <div className="min-w-0">
          <h1 className="text-3xl font-serif font-semibold text-[#0D1B2A] leading-tight">
            {jogo.titulo}
          </h1>

          {jogo.autor && (
            <p className="text-sm text-[#7B5E3A] mt-2">{jogo.autor}</p>
          )}

          <p className="text-xs text-[#4A4A4A] mt-1">
            {categoriaLabel}
            {jogo.ano_publicacao ? ` · ${jogo.ano_publicacao}` : ""}
          </p>

          {/* Oferta */}
          {ofertaAtiva && (
            <div className="mt-6 bg-white border border-[#E6DED3] rounded-xl px-5 py-4 inline-flex items-center gap-6">
              <div>
                <p className="text-xs text-[#7B5E3A]">{marketplaceLabel}</p>
                {preco ? (
                  <p className="text-lg font-semibold text-[#0D1B2A]">
                    R$ {preco}
                  </p>
                ) : (
                  <p className="text-sm text-[#4A4A4A]">Ver preço na loja</p>
                )}
              </div>
              <a
                href={`/api/click-jogo/${jogo.id}`}
                rel="nofollow sponsored"
                className="bg-[#C9A84C] text-[#0D1B2A] text-sm font-semibold px-5 py-2.5 rounded-lg hover:opacity-90 transition-opacity whitespace-nowrap"
              >
                Ver oferta
              </a>
            </div>
          )}
        </div>

      </div>

      {/* =========================
          SINOPSE
      ========================== */}
      {jogo.descricao && (
        <section>
          <h2 className="text-xl font-serif font-semibold text-[#0D1B2A] mb-4">
            Sobre o jogo
          </h2>
          <p className="font-serif text-[#0D1B2A] leading-relaxed max-w-3xl whitespace-pre-line">
            {jogo.descricao}
          </p>
        </section>
      )}

      {/* =========================
          VOLTAR
      ========================== */}
      <p>
        <Link
          href="/jogos"
          className="text-sm font-medium text-[#C9A84C] hover:text-[#4A1628] transition-colors"
        >
          ← Todos os jogos
        </Link>
      </p>

    </div>
  );
}
