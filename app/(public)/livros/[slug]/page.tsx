import { notFound } from "next/navigation";
import { supabase } from "@/lib/supabase";
import type { Metadata } from "next";

type PageProps = {
  params: Promise<{ slug: string }>;
};

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { slug } = await params;

  const { data: livro } = await supabase
    .from("livros")
    .select("titulo, descricao, sinopse, autor, imagem_url")
    .eq("slug", slug)
    .single();

  if (!livro) return {};

  const description = (livro.sinopse ?? livro.descricao)?.slice(0, 160)
    ?? `Sinopse, ofertas e informações sobre ${livro.titulo}${livro.autor ? ` de ${livro.autor}` : ""}.`;

  return {
    title: livro.titulo,
    description,
    alternates: { canonical: `/livros/${slug}` },
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

const MARKETPLACE_LABELS: Record<string, string> = {
  amazon:         "Amazon",
  mercadolivre:   "Mercado Livre",
  mercado_livre:  "Mercado Livre",
};

export default async function LivroPage({ params }: PageProps) {
  const { slug } = await params;

  /**
   * Livro + Categorias
   */
  const { data: livro } = await supabase
    .from("livros")
    .select(`
      *,
      livros_categorias (
        categorias (
          nome,
          slug
        )
      )
    `)
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
    .select("id, preco, marketplace")
    .eq("livro_id", livro.id)
    .eq("ativa", true);

  /**
   * Listas relacionadas
   */
  const { data: listasPivot } = await supabase
    .from("lista_livros")
    .select("listas ( titulo, slug )")
    .eq("livro_id", livro.id);

  const listas = listasPivot?.map((l: any) => l.listas).filter(Boolean) ?? [];

  /**
   * Schema.org
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
    <div className="max-w-4xl mx-auto space-y-10">

      {/* Schema JSON-LD */}
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(schema) }}
      />

      {/* =========================
          HERO DO LIVRO
      ========================== */}
      <section className="flex flex-col sm:flex-row gap-8">

        {/* Capa */}
        <div className="flex-shrink-0">
          {livro.imagem_url ? (
            <img
              src={livro.imagem_url}
              alt={livro.titulo}
              className="w-44 rounded-xl shadow-md border border-[#E6DED3]"
              onError={(e) => {
                const target = e.currentTarget;
                target.style.display = "none";
                const fallback = target.nextElementSibling as HTMLElement | null;
                if (fallback) fallback.style.display = "flex";
              }}
            />
          ) : null}
          <div
            className="w-44 h-64 rounded-xl bg-[#4A1628] items-center justify-center"
            style={{ display: livro.imagem_url ? "none" : "flex" }}
          >
            <span className="text-[#C9A84C] text-5xl font-serif">A</span>
          </div>
        </div>

        {/* Dados */}
        <div className="space-y-4">

          {/* Breadcrumb */}
          <p className="text-xs text-[#7B5E3A] uppercase tracking-widest font-medium">
            <a href="/livros" className="hover:text-[#C9A84C] transition-colors">
              Livros
            </a>
            {" "}/ <span>{livro.titulo}</span>
          </p>

          <h1 className="text-3xl font-serif font-semibold text-[#0D1B2A] leading-tight">
            {livro.titulo}
          </h1>

          {livro.autor && (
            <p className="text-base text-[#4A4A4A]">
              por <span className="font-medium text-[#0D1B2A]">{livro.autor}</span>
            </p>
          )}

          {/* Metadados */}
          <div className="flex flex-wrap gap-2 pt-1">

            {livro.ano_publicacao && (
              <span className="text-xs bg-[#F5F0E8] border border-[#E6DED3] text-[#7B5E3A] px-3 py-1 rounded-full">
                {livro.ano_publicacao}
              </span>
            )}

            {livro.idioma && (
              <span className="text-xs bg-[#F5F0E8] border border-[#E6DED3] text-[#7B5E3A] px-3 py-1 rounded-full">
                {livro.idioma}
              </span>
            )}

            {livro.livros_categorias
              ?.filter((rel: any) => rel.categorias)
              .map((rel: any) => (
                <a
                  key={rel.categorias.slug}
                  href={`/categorias/${rel.categorias.slug}`}
                  className="text-xs bg-[#4A1628] text-[#F5F0E8] px-3 py-1 rounded-full hover:bg-[#6B2238] transition-colors"
                >
                  {rel.categorias.nome}
                </a>
              ))}

          </div>

          {/* CTA principal */}
          {ofertas && ofertas.length > 0 && (
            <div className="pt-2">
              <a
                href={`/api/click/${ofertas[0].id}`}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 px-5 py-2.5 bg-[#C9A84C] text-[#4A1628] text-sm font-semibold rounded-lg hover:bg-[#e0bc5e] transition-colors"
              >
                {(() => {
                  const price = formatPrice(ofertas[0].preco);
                  return price ? `Ver melhor oferta — R$ ${price}` : "Ver melhor oferta";
                })()}
              </a>
            </div>
          )}

        </div>

      </section>

      {/* =========================
          SINOPSE
      ========================== */}
      {(livro.sinopse ?? livro.descricao) && (
        <section className="bg-white border border-[#E6DED3] rounded-2xl px-8 py-7">

          <h2 className="text-lg font-serif font-semibold text-[#0D1B2A] mb-4">
            Sinopse
          </h2>

          <p className="text-[#4A4A4A] leading-relaxed text-base">
            {livro.sinopse ?? livro.descricao}
          </p>

        </section>
      )}

      {/* =========================
          ONDE COMPRAR
      ========================== */}
      <section>

        <h2 className="text-xl font-serif font-semibold text-[#0D1B2A] mb-5">
          Onde comprar
        </h2>

        {!ofertas?.length && (
          <p className="text-[#7B5E3A] text-sm">
            Nenhuma oferta disponível no momento.
          </p>
        )}

        <div className="space-y-3">

          {ofertas?.map((o: any) => {
            const price = formatPrice(o.preco);
            const label = MARKETPLACE_LABELS[o.marketplace] ?? o.marketplace;
            return (
              <div
                key={o.id}
                className="flex items-center justify-between bg-white border border-[#E6DED3] rounded-xl px-6 py-4 hover:border-[#C9A84C] transition-all"
              >

                <div>
                  <p className="font-medium text-[#0D1B2A] text-sm">
                    {label}
                  </p>
                  {price ? (
                    <p className="text-xl font-serif font-semibold text-[#4A1628] mt-0.5">
                      R$ {price}
                    </p>
                  ) : (
                    <p className="text-sm text-[#7B5E3A] mt-0.5">
                      Consulte o site
                    </p>
                  )}
                </div>

                <a
                  href={`/api/click/${o.id}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="px-4 py-2 bg-[#C9A84C] text-[#4A1628] text-sm font-semibold rounded-lg hover:bg-[#e0bc5e] transition-colors"
                >
                  Ver oferta →
                </a>

              </div>
            );
          })}

        </div>

      </section>

      {/* =========================
          LISTAS RELACIONADAS
      ========================== */}
      <section>

        <h2 className="text-xl font-serif font-semibold text-[#0D1B2A] mb-5">
          Este livro aparece nas listas
        </h2>

        {!listas.length && (
          <p className="text-[#7B5E3A] text-sm">
            Ainda não vinculado a listas editoriais.
          </p>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">

          {listas.map((lista: any) => (
            <a
              key={lista.slug}
              href={`/listas/${lista.slug}`}
              className="group block bg-white border border-[#E6DED3] rounded-xl px-5 py-4 hover:border-[#C9A84C] hover:shadow-sm transition-all"
            >
              <span className="text-[#C9A84C] text-xs font-semibold uppercase tracking-wider mb-1 block">
                Lista editorial
              </span>
              <span className="text-[#0D1B2A] font-serif font-semibold text-sm leading-snug group-hover:text-[#4A1628] transition-colors">
                {lista.titulo}
              </span>
            </a>
          ))}

        </div>

      </section>

    </div>
  );
}
