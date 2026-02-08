export const runtime = "edge";

import { notFound } from "next/navigation";
import { createClient } from "@supabase/supabase-js";

type PageProps = {
  params: Promise<{
    slug: string;
  }>;
};

export default async function LivroPage({
  params,
}: PageProps) {
  const { slug } = await params;

  const supabase = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
  );

  /**
   * Livro
   */
  const { data: livro } = await supabase
    .from("livros")
    .select("*")
    .eq("slug", slug)
    .single();

  if (!livro) {
    notFound();
  }

  /**
   * Ofertas
   */
  const { data: ofertas } = await supabase
    .from("ofertas")
    .select(`
      id,
      preco,
      marketplace
    `)
    .eq("livro_id", livro.id)
    .eq("ativa", true);

  /**
   * Listas relacionadas
   */
  const { data: listasPivot } = await supabase
    .from("lista_livros")
    .select(`
      listas (
        titulo,
        slug
      )
    `)
    .eq("livro_id", livro.id);

  const listas =
    listasPivot?.map((l: any) => l.listas) ?? [];

  /**
   * =========================
   * Schema.org Product-first
   * =========================
   */
  const schema = {
    "@context": "https://schema.org",
    "@type": "Product",
    name: livro.titulo,
    description: livro.descricao,
    image: livro.imagem_url || undefined,
    sku: livro.isbn,
    brand: {
      "@type": "Brand",
      name: livro.autor,
    },
    additionalProperty: [
      {
        "@type": "PropertyValue",
        name: "Autor",
        value: livro.autor,
      },
      {
        "@type": "PropertyValue",
        name: "Ano de publicação",
        value: livro.ano_publicacao,
      },
    ],
    offers: ofertas?.map((o: any) => ({
      "@type": "Offer",
      price: o.preco,
      priceCurrency: "BRL",
      availability: "https://schema.org/InStock",
      url: `${process.env.NEXT_PUBLIC_SITE_URL}/api/click/${o.id}`,
      seller: {
        "@type": "Organization",
        name: o.marketplace,
      },
    })),
  };

  return (
    <main className="max-w-3xl mx-auto px-6 py-10 space-y-10">
      {/* Schema JSON-LD */}
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify(schema),
        }}
      />

      {/* =========================
          Livro
      ========================== */}
      <section className="space-y-4">
        <h1 className="text-3xl font-bold">
          {livro.titulo}
        </h1>

        {livro.autor && (
          <p className="text-lg text-gray-600">
            por {livro.autor}
          </p>
        )}

        {livro.descricao && (
          <p className="text-gray-800 leading-relaxed">
            {livro.descricao}
          </p>
        )}
      </section>

      {/* =========================
          Listas relacionadas
      ========================== */}
      <section className="space-y-4">
        <h2 className="text-2xl font-semibold">
          Este livro aparece nas listas
        </h2>

        {!listas.length && (
          <p className="text-gray-500">
            Ainda não vinculado a listas editoriais.
          </p>
        )}

        <ul className="list-disc list-inside space-y-1">
          {listas.map((lista: any) => (
            <li key={lista.slug}>
              <a
                href={`/listas/${lista.slug}`}
                className="text-blue-600 hover:underline"
              >
                {lista.titulo}
              </a>
            </li>
          ))}
        </ul>
      </section>

      {/* =========================
          Ofertas
      ========================== */}
      <section className="space-y-4">
        <h2 className="text-2xl font-semibold">
          Onde comprar
        </h2>

        {!ofertas?.length && (
          <p className="text-gray-500">
            Nenhuma oferta disponível no momento.
          </p>
        )}

        <ul className="space-y-3">
          {ofertas?.map((o: any) => (
            <li
              key={o.id}
              className="border p-4 rounded-lg flex items-center justify-between"
            >
              <div>
                <p className="font-medium">
                  {o.marketplace}
                </p>

                <p className="text-lg font-bold">
                  R$ {o.preco}
                </p>
              </div>

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
      </section>
    </main>
  );
}
