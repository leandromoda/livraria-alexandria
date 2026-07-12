import type { Metadata } from "next";
import { unstable_cache } from "next/cache";
import { supabase } from "@/lib/supabase";
import { SLUG_TO_GROUP, GRUPOS_ORDEM } from "@/lib/taxonomy-groups";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Categorias",
  description: "Explore livros por categoria literária na Livraria Alexandria.",
  alternates: { canonical: "/categorias" },
};

type PageProps = {
  searchParams: Promise<{ grupo?: string }>;
};

type CategoriaRow = {
  id: string;
  nome: string;
  slug: string;
  livros_categorias: { livro_id: string }[] | null;
};

type CategoriaLista = {
  nome: string;
  slug: string;
  grupo: string;
  count: number;
};

// Fetch + enriquecimento (grupo/contagem) memoizados no Data Cache — antes a
// query rodava a cada request (era force-dynamic). A página lê searchParams
// (grupo) e filtra no servidor, preservando SEO e payload pequeno.
const fetchCategorias = unstable_cache(
  async (): Promise<CategoriaLista[]> => {
    const { data } = await supabase
      .from("categorias")
      .select("id, nome, slug, livros_categorias ( livro_id )")
      .eq("status_publish", true)
      .order("nome");

    return ((data ?? []) as CategoriaRow[])
      .map((cat) => ({
        nome: cat.nome,
        slug: cat.slug,
        grupo: SLUG_TO_GROUP[cat.slug] ?? "Outros",
        count: cat.livros_categorias?.length ?? 0,
      }))
      // Só categorias com livros — evita cards "0 livros" (links mortos).
      .filter((cat) => cat.count > 0);
  },
  ["categorias-index"],
  { revalidate: 3600 },
);

export default async function CategoriasPage({ searchParams }: PageProps) {
  const { grupo: grupoParam } = await searchParams;
  const grupoAtivo = grupoParam?.trim() ?? "";

  const todas = await fetchCategorias();

  const gruposDisponiveis = [
    ...GRUPOS_ORDEM.filter((g) => todas.some((c) => c.grupo === g)),
    ...(todas.some((c) => c.grupo === "Outros") ? ["Outros"] : []),
  ];

  const categorias = grupoAtivo
    ? todas.filter((c) => c.grupo === grupoAtivo)
    : todas;

  return (
    <div className="space-y-8">

      {/* Header */}
      <header>
        <p className="text-[#C9A84C] text-xs font-semibold uppercase tracking-widest mb-2">
          Navegação
        </p>
        <h1 className="text-3xl font-serif font-semibold text-[#0D1B2A]">
          Categorias
        </h1>
        {grupoAtivo && (
          <p className="text-[#4A4A4A] text-sm mt-2">
            {categorias.length}{" "}
            {categorias.length === 1 ? "categoria" : "categorias"} em{" "}
            <span className="font-medium text-[#4A1628]">{grupoAtivo}</span>
          </p>
        )}
      </header>

      {/* Macrocategorias */}
      {gruposDisponiveis.length > 0 && (
        <section>
          <p className="text-xs font-semibold text-[#7B5E3A] uppercase tracking-widest mb-3">
            Explorar por área
          </p>

          <div className="flex flex-wrap gap-2">

            <Link
              href="/categorias"
              className={`text-xs font-semibold px-3 py-1.5 rounded-full border transition-colors ${
                !grupoAtivo
                  ? "bg-[#4A1628] text-[#C9A84C] border-[#4A1628]"
                  : "text-[#4A4A4A] border-[#E6DED3] hover:border-[#C9A84C] hover:text-[#4A1628] bg-white"
              }`}
            >
              Todas
            </Link>

            {gruposDisponiveis.map((g) => (
              <a
                key={g}
                href={`/categorias?grupo=${encodeURIComponent(g)}`}
                className={`text-xs font-semibold px-3 py-1.5 rounded-full border transition-colors ${
                  grupoAtivo === g
                    ? "bg-[#4A1628] text-[#C9A84C] border-[#4A1628]"
                    : "text-[#4A4A4A] border-[#E6DED3] hover:border-[#C9A84C] hover:text-[#4A1628] bg-white"
                }`}
              >
                {g}
              </a>
            ))}

          </div>
        </section>
      )}

      {/* Grid de categorias */}
      {!categorias.length ? (
        <p className="text-sm text-[#4A4A4A]">
          Nenhuma categoria disponível{grupoAtivo ? " nesta área" : ""}.
        </p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">

          {categorias.map((cat) => (
            <a
              key={cat.slug}
              href={`/categorias/${cat.slug}`}
              className="group flex items-center justify-between bg-white border border-[#E6DED3] rounded-xl px-5 py-4 hover:border-[#C9A84C] hover:shadow-sm transition-all"
            >
              <span className="font-medium text-[#0D1B2A] group-hover:text-[#4A1628] transition-colors text-sm">
                {cat.nome}
              </span>

              <span className="text-xs text-[#7B5E3A] bg-[#F5F0E8] px-2.5 py-1 rounded-full border border-[#E6DED3] flex-shrink-0 ml-3">
                {cat.count} livros
              </span>
            </a>
          ))}

        </div>
      )}

    </div>
  );
}
