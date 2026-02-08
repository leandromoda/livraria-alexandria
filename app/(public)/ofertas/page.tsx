export const runtime = "edge";

import { createClient } from "@supabase/supabase-js";

export default async function OfertasPage() {
  const supabase = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
  );

  /**
   * Ofertas + Livro
   */
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
    process.env.NEXT_PUBLIC_SITE_URL ||
    "http://localhost:3000";

  /**
   * =========================
   * Schema.org
   * =========================
   */
  const schema = {
    "@context": "https://schema.org",
    "@type": "ItemList",
    name: "Ofertas de livros",
    itemListElement: ofertas?.map(
      (o: any, index: number) => ({
        "@type": "ListItem",
        position: index + 1,
        item: {
          "@type": "Product",
          name: o.livros.titulo,
          image:
            o.livros.imagem_url || undefined,
          sku: o.livros.isbn,
          brand: {
            "@type": "Brand",
            name: o.livros.autor,
          },
          offers: {
            "@type": "Offer",
            price: o.preco,
            priceCurrency: "BRL",
            availability:
              "https://schema.org/InStock",
            url: `${baseUrl}/api/click/${o.id}`,
            seller: {
              "@type": "Organization",
              name: o.marketplace,
            },
          },
        },
      })
    ),
  };

  return (
    <main className="max-w-3xl mx-auto px-6 py-10 space-y-6">
      {/* Schema */}
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify(schema),
        }}
      />

      <h1 className="text-3xl font-bold">
        Ofertas de Livros
      </h1>

      <ul className="space-y-4">
        {ofertas?.map((o: any) => (
          <li
            key={o.id}
            className="border p-4 rounded-lg"
          >
            <a
              href={`/livros/${o.livros.slug}`}
              className="text-lg font-semibold text-blue-600 hover:underline block"
            >
              {o.livros.titulo}
            </a>

            <p className="text-gray-700">
              R$ {o.preco}
            </p>

            <a
              href={`/api/click/${o.id}`}
              target="_blank"
              className="text-sm text-green-600 hover:underline"
            >
              Ver oferta →
            </a>
          </li>
        ))}
      </ul>
    </main>
  );
}