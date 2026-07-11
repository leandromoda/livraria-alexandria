// ISR: ofertas ativas mudam em lote pelo pipeline, não a cada request.
// Cache no edge + revalidação horária (o preço real vive no marketplace; o
// exibido já é um snapshot do scrape, então até 1h de staleness é aceitável).
export const revalidate = 3600;

import { supabase } from "@/lib/supabase";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Ofertas de livros",
  description:
    "As melhores ofertas em literatura nacional e internacional com preços atualizados.",
  alternates: { canonical: "/ofertas" },
};

function formatPrice(value: unknown): string | null {
  const num = Number(value);
  if (!value || num === 0 || isNaN(num)) return null;
  return num.toLocaleString("pt-BR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

const MARKETPLACE_LABELS: Record<string, string> = {
  amazon: "Amazon",
  mercadolivre: "Mercado Livre",
  mercado_livre: "Mercado Livre",
};

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
    is_publishable: boolean;
  } | null;
};

// O PostgREST corta em 1.000 linhas por request e há >3.500 ofertas ativas —
// sem paginação, a maioria ficava fora da página (e do schema:ItemList).
async function fetchActiveOffers(): Promise<OfertaRow[]> {
  const PAGE = 1000;
  const all: OfertaRow[] = [];
  for (let from = 0; ; from += PAGE) {
    const { data, error } = await supabase
      .from("ofertas")
      .select(`
        id,
        preco,
        marketplace,
        url_afiliada,
        livros (
          titulo,
          slug,
          autor,
          imagem_url,
          isbn,
          is_publishable
        )
      `)
      .eq("ativa", true)
      .order("id")
      .range(from, from + PAGE - 1);
    if (error || !data || data.length === 0) break;
    all.push(...(data as unknown as OfertaRow[]));
    if (data.length < PAGE) break;
  }
  return all;
}

export default async function OfertasPage() {
  const ofertas = (await fetchActiveOffers()).filter(
    (o) => o.livros?.is_publishable === true
  );

  const baseUrl =
    process.env.NEXT_PUBLIC_SITE_URL || "https://livrariaalexandria.com.br";

  /**
   * Schema.org
   */
  const schema = {
    "@context": "https://schema.org",
    "@type": "ItemList",
    name: "Ofertas de livros",
    // Google requires price on every Offer — only include offers with valid price in schema
    itemListElement: (ofertas ?? [])
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      .filter((o: any) => Number(o.preco) > 0)
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      .map((o: any, index: number) => ({
        "@type": "ListItem",
        position: index + 1,
        item: {
          "@type": "Product",
          name: o.livros.titulo,
          image: o.livros.imagem_url || undefined,
          ...(o.livros.isbn ? { isbn: o.livros.isbn } : {}),
          ...(o.livros.autor ? { brand: { "@type": "Brand", name: o.livros.autor } } : {}),
          offers: {
            "@type": "Offer",
            price: Number(o.preco),
            priceCurrency: "BRL",
            availability: "https://schema.org/InStock",
            url: o.url_afiliada || `${baseUrl}/livros/${o.livros.slug}`,
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
          {ofertas?.length ?? 0}{" "}
          {(ofertas?.length ?? 0) === 1 ? "oferta disponível" : "ofertas disponíveis"}
        </p>

      </header>

      {/* =========================
          LISTA DE OFERTAS
      ========================== */}
      <div className="space-y-4">

        {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
        {ofertas?.map((o: any) => (
          <div
            key={o.id}
            className="flex items-center gap-5 bg-white border border-[#E6DED3] rounded-xl px-6 py-5 hover:border-[#C9A84C] hover:shadow-sm transition-all"
          >

            {/* Capa */}
            {o.livros.imagem_url ? (
              <img
                src={o.livros.imagem_url}
                alt={o.livros.titulo}
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
                href={`/livros/${o.livros.slug}`}
                className="block font-serif font-semibold text-base text-[#0D1B2A] leading-snug hover:text-[#4A1628] transition-colors"
              >
                {o.livros.titulo}
              </a>

              {o.livros.autor && (
                <p className="text-sm text-[#4A4A4A] mt-0.5">
                  por {o.livros.autor}
                </p>
              )}

              <span className="text-xs text-[#7B5E3A] bg-[#F5F0E8] border border-[#E6DED3] px-2.5 py-0.5 rounded-full mt-2 inline-block">
                {MARKETPLACE_LABELS[o.marketplace] ?? o.marketplace}
              </span>

            </div>

            {/* Preço + CTA */}
            <div className="flex-shrink-0 text-right">

              {(() => {
                const price = formatPrice(o.preco);
                return price ? (
                  <p className="text-xl font-serif font-semibold text-[#4A1628] mb-2">
                    R$ {price}
                  </p>
                ) : (
                  <p className="text-sm text-[#7B5E3A] mb-2">
                    Consulte o site
                  </p>
                );
              })()}

              <a
                href={`/api/click/${o.id}`}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-block px-4 py-2 bg-[#C9A84C] text-[#4A1628] text-xs font-semibold rounded-lg hover:bg-[#e0bc5e] transition-colors"
              >
                Ver oferta →
              </a>

            </div>

          </div>
        ))}

      </div>

    </div>
  );
}
