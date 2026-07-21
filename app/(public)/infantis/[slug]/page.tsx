// ISR on-demand: cada livro infantil renderiza no primeiro acesso e fica em
// cache no edge, revalidando de hora em hora (padrão de /livros/[slug]).
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

const FAIXA_LABELS: Record<string, string> = {
  "0-2-anos": "0 a 2 anos",
  "3-5-anos": "3 a 5 anos",
  "6-8-anos": "6 a 8 anos",
  "9-12-anos": "9 a 12 anos",
};

const MARKETPLACE_LABELS: Record<string, string> = {
  amazon: "Amazon",
  mercadolivre: "Mercado Livre",
  mercado_livre: "Mercado Livre",
};

const getLivro = unstable_cache(
  async (slug: string) => {
    const { data } = await supabase
      .from("livros_infantis")
      .select("*")
      .eq("slug", slug)
      .eq("is_publishable", true)
      .single();
    return data;
  },
  ["infantil-detalhe"],
  { revalidate: 3600 },
);

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { slug } = await params;
  const livro = await getLivro(slug);

  if (!livro) return {};

  const description =
    livro.descricao?.slice(0, 160) ??
    `Sinopse, faixa etária e ofertas de ${livro.titulo}.`;

  return {
    title: livro.titulo,
    description,
    alternates: { canonical: `/infantis/${slug}` },
    openGraph: {
      title: livro.titulo,
      description,
      ...(livro.imagem_url ? { images: [{ url: livro.imagem_url }] } : {}),
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

export default async function LivroInfantilPage({ params }: PageProps) {
  const { slug } = await params;
  const livro = await getLivro(slug);

  if (!livro) return notFound();

  const faixaLabel = FAIXA_LABELS[livro.faixa_etaria] ?? "Infantil";
  const marketplaceLabel =
    MARKETPLACE_LABELS[livro.marketplace ?? ""] ?? "loja parceira";
  const preco = formatPrice(livro.preco_atual);
  const ofertaAtiva =
    Boolean(livro.url_afiliada) && livro.offer_status !== "unavailable";

  // Google exige offers/review/aggregateRating em todo Product — sem preço
  // não há Offer válido, então o JSON-LD só é emitido quando há oferta com preço.
  const ofertaJsonLd =
    ofertaAtiva && livro.preco_atual
      ? {
          "@type": "Offer" as const,
          price: Number(livro.preco_atual),
          priceCurrency: "BRL",
          availability: "https://schema.org/InStock",
        }
      : undefined;

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "Book",
    name: livro.titulo,
    ...(livro.descricao ? { description: livro.descricao } : {}),
    ...(livro.imagem_url ? { image: livro.imagem_url } : {}),
    ...(livro.autor
      ? { author: { "@type": "Person", name: livro.autor } }
      : {}),
    ...(livro.ilustrador
      ? { illustrator: { "@type": "Person", name: livro.ilustrador } }
      : {}),
    typicalAgeRange: `${livro.idade_min}-${livro.idade_max}`,
    ...(ofertaJsonLd ? { offers: ofertaJsonLd } : {}),
  };

  return (
    <div className="space-y-10">

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
        <Link href="/infantis" className="hover:opacity-80 transition-opacity">
          Livros Infantis
        </Link>{" "}
        /{" "}
        <Link
          href={`/infantis#${livro.faixa_etaria}`}
          className="hover:opacity-80 transition-opacity"
        >
          {faixaLabel}
        </Link>
      </p>

      {/* =========================
          CABEÇALHO
      ========================== */}
      <div className="flex flex-col sm:flex-row gap-8">

        <div className="flex-shrink-0 w-32 h-44 overflow-hidden rounded-xl border border-[#E6DED3] bg-[#4A1628] flex items-center justify-center">
          {livro.imagem_url ? (
            <Image
              src={livro.imagem_url}
              alt={livro.titulo}
              width={128}
              height={176}
              priority
              unoptimized={!isOptimizableImage(livro.imagem_url)}
              className="w-full h-full object-cover"
            />
          ) : (
            <span className="text-[#C9A84C] text-3xl font-serif">A</span>
          )}
        </div>

        <div className="min-w-0">
          <h1 className="text-3xl font-serif font-semibold text-[#0D1B2A] leading-tight">
            {livro.titulo}
          </h1>

          {livro.autor && (
            <p className="text-sm text-[#7B5E3A] mt-2">{livro.autor}</p>
          )}

          {livro.ilustrador && (
            <p className="text-xs text-[#7B5E3A] mt-0.5">
              Ilustrações de {livro.ilustrador}
            </p>
          )}

          {/* Faixa etária em destaque — é o eixo da seção */}
          <p className="mt-3">
            <span className="inline-block bg-[#C9A84C] text-[#0D1B2A] text-xs font-semibold px-3 py-1 rounded-full">
              {faixaLabel}
            </span>
          </p>

          {livro.ano_publicacao && (
            <p className="text-xs text-[#4A4A4A] mt-2">{livro.ano_publicacao}</p>
          )}

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
                href={`/api/click-infantil/${livro.id}`}
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
      {livro.descricao && (
        <section>
          <h2 className="text-xl font-serif font-semibold text-[#0D1B2A] mb-4">
            Sobre o livro
          </h2>
          <p className="font-serif text-[#0D1B2A] leading-relaxed max-w-3xl whitespace-pre-line">
            {livro.descricao}
          </p>
        </section>
      )}

      <p>
        <Link
          href="/infantis"
          className="text-sm font-medium text-[#C9A84C] hover:text-[#4A1628] transition-colors"
        >
          ← Todos os livros infantis
        </Link>
      </p>

    </div>
  );
}
