export const dynamic = "force-dynamic";

import { supabase } from "@/lib/supabase";

type PageProps = {
  searchParams: Promise<{ categoria?: string }>;
};

export default async function ListasPage({ searchParams }: PageProps) {
  const { categoria: rawCategoria } = await searchParams;
  const categoriaAtiva = rawCategoria?.trim() ?? "";

  const { data: todas } = await supabase
    .from("listas")
    .select("id, titulo, slug, introducao, macrocategoria")
    .order("titulo");

  const todasListas = todas ?? [];

  /* Macrocategorias disponíveis (campo opcional — degrade se ausente) */
  const macrocategorias = [
    ...new Set(
      todasListas
        .map((l: any) => l.macrocategoria as string | null)
        .filter((c): c is string => !!c)
    ),
  ].sort();

  const temSidebar = macrocategorias.length > 0;

  const listas = categoriaAtiva
    ? todasListas.filter((l: any) => l.macrocategoria === categoriaAtiva)
    : todasListas;

  return (
    <div className="space-y-8">

      {/* Header */}
      <header>

        <p className="text-[#C9A84C] text-xs font-semibold uppercase tracking-widest mb-2">
          Navegação
        </p>

        <h1 className="text-3xl font-serif font-semibold text-[#0D1B2A]">
          Listas editoriais
        </h1>

        <p className="text-[#4A4A4A] text-sm mt-2">
          {listas.length}{" "}
          {listas.length === 1
            ? "lista disponível"
            : "listas disponíveis"}
          {categoriaAtiva ? ` em ${categoriaAtiva}` : ""}
        </p>

      </header>

      {/* Layout com sidebar */}
      <div className="flex gap-8 items-start">

        {/* Sidebar de macrocategorias */}
        {temSidebar && (
          <nav className="hidden lg:flex flex-col gap-1 flex-shrink-0 w-44 sticky top-6">

            <a
              href="/listas"
              className={`text-sm px-3 py-2 rounded-lg transition-colors ${
                !categoriaAtiva
                  ? "bg-[#4A1628] text-[#C9A84C] font-semibold"
                  : "text-[#4A4A4A] hover:text-[#4A1628] hover:bg-[#F5F0E8]"
              }`}
            >
              Todas
            </a>

            {macrocategorias.map((cat) => (
              <a
                key={cat}
                href={`/listas?categoria=${encodeURIComponent(cat)}`}
                className={`text-sm px-3 py-2 rounded-lg transition-colors ${
                  categoriaAtiva === cat
                    ? "bg-[#4A1628] text-[#C9A84C] font-semibold"
                    : "text-[#4A4A4A] hover:text-[#4A1628] hover:bg-[#F5F0E8]"
                }`}
              >
                {cat}
              </a>
            ))}

          </nav>
        )}

        {/* Grid de listas */}
        <div className="flex-1 min-w-0">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">

            {listas.map((l: any) => (

              <a
                key={l.slug}
                href={`/listas/${l.slug}`}
                className="group block bg-white border border-[#E6DED3] rounded-xl px-5 py-5 hover:border-[#C9A84C] hover:shadow-sm transition-all"
              >

                <span className="text-[#C9A84C] text-xs font-semibold uppercase tracking-wider mb-2 block">
                  {l.macrocategoria ?? "Lista editorial"}
                </span>

                <span className="block text-[#0D1B2A] font-serif font-semibold text-base leading-snug group-hover:text-[#4A1628] transition-colors mb-2">
                  {l.titulo}
                </span>

                {l.introducao && (
                  <span className="block text-[#4A4A4A] text-xs leading-relaxed line-clamp-2">
                    {l.introducao}
                  </span>
                )}

              </a>

            ))}

          </div>
        </div>

      </div>

    </div>
  );
}
