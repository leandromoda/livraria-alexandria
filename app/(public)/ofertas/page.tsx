// ISR: ofertas ativas mudam em lote pelo pipeline, não a cada request.
// Cache no edge + revalidação horária (o preço real vive no marketplace; o
// exibido já é um snapshot do scrape, então até 1h de staleness é aceitável).
export const revalidate = 3600;

import { supabase } from "@/lib/supabase";
import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { isOptimizableImage } from "@/lib/images";
import { toIsbn13 } from "@/lib/isbn";

export const metadata: Metadata = {
  title: "Ofertas de livros",
  description:
    "As melhores ofertas em literatura nacional e internacional com preços atualizados.",
  alternates: { canonical: "/ofertas" },
};

// Quantas ofertas a página renderiza. Medido em 2026-07-26: a versão anterior
// passava as ~4.500 ofertas inteiras como props para um client component que
// paginava com useState — o React serializa o array todo no payload RSC para
// hidratar, então o HTML da rota tinha 1,40 MB, dos quais 1,33 MB (95,5%) era
// só esse payload (a marcação das 48 linhas visíveis ocupava 0,06 MB).
// Renderizando no servidor um recorte fixo, o array nunca cruza a fronteira
// server→client e a rota continua estática (`○`), sem custo de invocação.
const LIMITE = 48;

const MARKETPLACE_LABELS: Record<string, string> = {
  amazon: "Amazon",
  mercadolivre: "Mercado Livre",
  mercado_livre: "Mercado Livre",
};

function formatPrice(value: unknown): string | null {
  const num = Number(value);
  if (!value || num === 0 || isNaN(num)) return null;
  return num.toLocaleString("pt-BR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

type OfertaRow = {
  id: string;
  preco: number | null;
  marketplace: string;
  url_afiliada: string | null;
  livros: {
    titulo: string;
    slug: string;
    autor: string | null;
    imagem_url: string | null;
    isbn: string | null;
  } | null;
};

// `livros!inner` + filtro no recurso embutido deixa o "só publicáveis" no
// PostgREST, em vez de buscar tudo e filtrar em JS — assim o LIMITE conta
// linhas que realmente vão para a tela, e o total bate com o que é exibido.
// A ordem põe quem tem preço primeiro (nullslast): é uma página de ofertas, e
// hoje a esmagadora maioria das linhas está sem preço no banco.
async function fetchOffers(): Promise<{ ofertas: OfertaRow[]; total: number }> {
  const { data, error, count } = await supabase
    .from("ofertas")
    .select(
      `
        id,
        preco,
        marketplace,
        url_afiliada,
        livros!inner (
          titulo,
          slug,
          autor,
          imagem_url,
          isbn
        )
      `,
      { count: "exact" },
    )
    .eq("ativa", true)
    .eq("livros.is_publishable", true)
    .order("preco", { ascending: false, nullsFirst: false })
    .limit(LIMITE);

  if (error || !data) return { ofertas: [], total: 0 };
  return {
    ofertas: data as unknown as OfertaRow[],
    total: count ?? data.length,
  };
}

export default async function OfertasPage() {
  const { ofertas, total } = await fetchOffers();

  const baseUrl =
    process.env.NEXT_PUBLIC_SITE_URL || "https://livrariaalexandria.com.br";

  /**
   * Schema.org — o ItemList descreve o que ESTA página mostra, então cobre só
   * as ofertas renderizadas. O Google exige `price` em todo `Offer`, então as
   * sem preço ficam de fora.
   */
  const schema = {
    "@context": "https://schema.org",
    "@type": "ItemList",
    name: "Ofertas de livros",
    itemListElement: ofertas
      .filter((o) => o.livros && Number(o.preco) > 0)
      .map((o, index) => ({
        "@type": "ListItem",
        position: index + 1,
        item: {
          "@type": "Product",
          name: o.livros!.titulo,
          image: o.livros!.imagem_url || undefined,
          // Mesmo cuidado de `livros/[slug]`: ISBN cru rendeu "Valor ISBN13
          // invalido" no GSC (2026-08-21). Ver `lib/isbn.ts`.
          ...(toIsbn13(o.livros!.isbn)
            ? { isbn: toIsbn13(o.livros!.isbn)! }
            : {}),
          ...(o.livros!.autor
            ? { brand: { "@type": "Brand", name: o.livros!.autor } }
            : {}),
          offers: {
            "@type": "Offer",
            price: Number(o.preco),
            priceCurrency: "BRL",
            availability: "https://schema.org/InStock",
            url: o.url_afiliada || `${baseUrl}/livros/${o.livros!.slug}`,
            seller: {
              "@type": "Organization",
              name: MARKETPLACE_LABELS[o.marketplace] ?? o.marketplace,
            },
          },
        },
      })),
  };

  return (
    <div className="space-y-8">

      {/* Schema */}
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(schema) }}
      />

      {/* =========================
          HEADER
      ========================== */}
      <header>

        <p className="text-[#C9A84C] text-xs font-semibold uppercase tracking-widest mb-2">
          Promoções
        </p>

        <h1 className="text-3xl font-serif font-semibold text-[#0D1B2A]">
          Ofertas de livros
        </h1>

        <p className="text-[#4A4A4A] text-sm mt-2">
          {total > ofertas.length ? (
            <>
              Uma seleção de {ofertas.length} entre {total} ofertas disponíveis.{" "}
              <Link
                href="/livros"
                className="text-[#4A1628] underline underline-offset-2 hover:text-[#C9A84C] transition-colors"
              >
                Ver o catálogo completo
              </Link>
              .
            </>
          ) : (
            <>
              {total} {total === 1 ? "oferta disponível" : "ofertas disponíveis"}
            </>
          )}
        </p>

      </header>

      {/* =========================
          LISTA DE OFERTAS
      ========================== */}
      <div className="space-y-4">
        {ofertas.map((o) => {
          const price = formatPrice(o.preco);
          return (
            <div
              key={o.id}
              className="flex items-center gap-5 bg-white border border-[#E6DED3] rounded-xl px-6 py-5 hover:border-[#C9A84C] hover:shadow-sm transition-all"
            >

              {/* Capa */}
              {o.livros?.imagem_url ? (
                <Image
                  src={o.livros.imagem_url}
                  alt={o.livros.titulo}
                  width={48}
                  height={64}
                  unoptimized={!isOptimizableImage(o.livros.imagem_url)}
                  className="flex-shrink-0 w-12 h-16 object-cover rounded border border-[#E6DED3]"
                />
              ) : (
                <div className="flex-shrink-0 w-12 h-16 rounded bg-[#4A1628] flex items-center justify-center">
                  <span className="text-[#C9A84C] text-base font-serif">A</span>
                </div>
              )}

              {/* Dados */}
              <div className="flex-1 min-w-0">
                <a
                  href={`/livros/${o.livros!.slug}`}
                  className="block font-serif font-semibold text-base text-[#0D1B2A] leading-snug hover:text-[#4A1628] transition-colors"
                >
                  {o.livros!.titulo}
                </a>

                {o.livros!.autor && (
                  <p className="text-sm text-[#4A4A4A] mt-0.5">
                    por {o.livros!.autor}
                  </p>
                )}

                <span className="text-xs text-[#7B5E3A] bg-[#F5F0E8] border border-[#E6DED3] px-2.5 py-0.5 rounded-full mt-2 inline-block">
                  {MARKETPLACE_LABELS[o.marketplace] ?? o.marketplace}
                </span>
              </div>

              {/* Preço + CTA */}
              <div className="flex-shrink-0 text-right">
                {price ? (
                  <p className="text-xl font-serif font-semibold text-[#4A1628] mb-2">
                    R$ {price}
                  </p>
                ) : (
                  <p className="text-sm text-[#7B5E3A] mb-2">
                    Consulte o site
                  </p>
                )}

                <a
                  href={`/api/click/${o.id}`}
                  target="_blank"
                  rel="noopener noreferrer nofollow sponsored"
                  className="inline-block px-4 py-2 bg-[#C9A84C] text-[#4A1628] text-xs font-semibold rounded-lg hover:bg-[#e0bc5e] transition-colors"
                >
                  Ver oferta →
                </a>
              </div>

            </div>
          );
        })}
      </div>

    </div>
  );
}
