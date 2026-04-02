export const dynamic = "force-dynamic";

import { supabase } from "@/lib/supabase";

export default async function ListasPage() {

  /**
   * Listas
   */
  const { data: listas } = await supabase
    .from("listas")
    .select("id, titulo, slug, introducao")
    .order("titulo");

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
          {listas?.length ?? 0} {(listas?.length ?? 0) === 1 ? "lista disponível" : "listas disponíveis"}
        </p>

      </header>

      {/* Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">

        {listas?.map((l: any) => (

          <a
            key={l.slug}
            href={`/listas/${l.slug}`}
            className="group block bg-white border border-[#E6DED3] rounded-xl px-5 py-5 hover:border-[#C9A84C] hover:shadow-sm transition-all"
          >

            <span className="text-[#C9A84C] text-xs font-semibold uppercase tracking-wider mb-2 block">
              Lista editorial
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
  );
}
