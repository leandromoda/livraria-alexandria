// ISR: ofertas ativas mudam em lote pelo pipeline, não a cada request.
// Cache no edge + revalidação horária (o preço real vive no marketplace; o
// exibido já é um snapshot do scrape, então até 1h de staleness é aceitável).
export const revalidate = 3600;

import { supabase } from "@/lib/supabase";
import type { Metadata } from "next";
import OfertasList from "./OfertasList";

export const metadata: Metadata = {
  title: "Ofertas de livros",
  description:
    "As melhores ofertas em literatura nacional e internacional com preços atualizados.",
  alternates: { canonical: "/ofertas" },
};

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
          LISTA DE OFERTAS (paginada no client)
      ========================== */}
      <OfertasList
        ofertas={ofertas.map((o) => ({
          id: o.id,
          preco: o.preco,
          marketplace: o.marketplace,
          livros: {
            titulo: o.livros!.titulo,
            slug: o.livros!.slug,
            autor: o.livros!.autor,
            imagem_url: o.livros!.imagem_url,
          },
        }))}
      />

    </div>
  );
}
