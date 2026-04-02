export const dynamic = "force-dynamic";

import { supabase } from "@/lib/supabase";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Ofertas de livros",
  description:
    "As melhores ofertas em literatura nacional e internacional com preços atualizados.",
};

function formatPrice(value: unknown): string {
  return Number(value).toLocaleString("pt-BR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export default async function OfertasPage() {
  const { data: ofertas } = await supabase
    .from("ofertas")
    .select(`
      id,
      preco,
      marketplace,
      livros (
        titulo,
        slug,
        autor,
        imagem_url,
        isbn
      )
    `)
    .eq("ativa", true);

  const baseUrl =
    process.env.NEXT_PUBLIC_SITE_URL || "https://livrariaalexandria.com.br";

  /**
   * Schema.org
   */
  const schema = {
    "@context": "https://schema.org",
    "@type": "ItemList",
    name: "Ofertas de livros",
    itemListElement: ofertas?.map((o: any, index: number) => ({
      "@type": "ListItem",
      position: index + 1,
      item: {
        "@type": "Product",
        name: o.livros.titulo,
        image: o.livros.imagem_url || undefined,
        sku: o.livros.isbn,
        brand: {
          "@type": "Brand",
          name: o.livros.autor,
        },
        offers: {
          "@type": "Offer",
          price: o.preco,
          priceCurrency: "BRL",
          availability: "https://schema.org/InStock",
          url: `${baseUrl}/api/click/${o.id}`,
          seller: {
            "@type": "Organization",
            name: o.marketplace,
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
                {o.marketplace}
              </span>

            </div>

            {/* Preço + CTA */}
            <div className="flex-shrink-0 text-right">

              <p className="text-xl font-serif font-semibold text-[#4A1628] mb-2">
                R$ {formatPrice(o.preco)}
              </p>

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
