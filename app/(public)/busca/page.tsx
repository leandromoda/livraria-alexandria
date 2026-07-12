// Busca abrangente: livros, autores, categorias (gêneros) e listas. Lê
// searchParams (q) → renderiza sob demanda no servidor. `noindex` porque
// páginas de resultado de busca não devem ser indexadas (boa prática de SEO).

import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { supabase } from "@/lib/supabase";
import { isOptimizableImage } from "@/lib/images";

type PageProps = {
  searchParams: Promise<{ q?: string }>;
};

export const metadata: Metadata = {
  title: "Busca",
  robots: { index: false, follow: true },
  alternates: { canonical: "/busca" },
};

// Remove caracteres que quebram a sintaxe de filtro do PostgREST (vírgula,
// parênteses, aspas) e os curingas do ilike — evita "injeção" de padrão.
function sanitize(q: string): string {
  return q.replace(/[%,()"\\*]/g, " ").replace(/\s+/g, " ").trim();
}

type Livro = { titulo: string; slug: string; autor: string | null; imagem_url: string | null };
type Autor = { nome: string; slug: string; livros_autores: { livro_id: string }[] };
type Categoria = { nome: string; slug: string };
type Lista = { titulo: string; slug: string; lista_livros: { livro_id: string }[] };

const LIVROS_LIMIT = 24;
const OUTROS_LIMIT = 12;

async function searchAll(safe: string) {
  const like = `%${safe}%`;
  const [livrosRes, autoresRes, categoriasRes, listasRes] = await Promise.all([
    supabase
      .from("livros")
      .select("titulo, slug, autor, imagem_url")
      .eq("is_publishable", true)
      .or(`titulo.ilike.${like},autor.ilike.${like}`)
      .order("titulo")
      .limit(LIVROS_LIMIT),
    supabase
      .from("autores")
      .select("nome, slug, livros_autores!inner(livro_id)")
      .ilike("nome", like)
      .order("nome")
      .limit(OUTROS_LIMIT),
    supabase
      .from("categorias")
      .select("nome, slug, livros_categorias!inner(livro_id)")
      .eq("status_publish", true)
      .ilike("nome", like)
      .order("nome")
      .limit(OUTROS_LIMIT),
    supabase
      .from("listas")
      .select("titulo, slug, lista_livros!inner(livro_id)")
      .ilike("titulo", like)
      .order("titulo")
      .limit(OUTROS_LIMIT),
  ]);

  return {
    livros: (livrosRes.data ?? []) as Livro[],
    autores: (autoresRes.data ?? []) as unknown as Autor[],
    categorias: (categoriasRes.data ?? []) as unknown as Categoria[],
    listas: (listasRes.data ?? []) as unknown as Lista[],
  };
}

export default async function BuscaPage({ searchParams }: PageProps) {
  const { q: rawQ } = await searchParams;
  const q = (rawQ ?? "").trim();
  const safe = sanitize(q);

  const resultados = safe
    ? await searchAll(safe)
    : { livros: [], autores: [], categorias: [], listas: [] };

  const total =
    resultados.livros.length +
    resultados.autores.length +
    resultados.categorias.length +
    resultados.listas.length;

  return (
    <div className="space-y-10">

      {/* HEADER */}
      <header>
        <p className="text-[#C9A84C] text-xs font-semibold uppercase tracking-widest mb-2">
          Busca
        </p>
        <h1 className="text-3xl font-serif font-semibold text-[#0D1B2A]">
          {q ? <>Resultados para &ldquo;{q}&rdquo;</> : "Buscar no acervo"}
        </h1>
        {q && (
          <p className="text-[#4A4A4A] text-sm mt-2">
            {total} {total === 1 ? "resultado" : "resultados"} em livros, autores, gêneros e listas
          </p>
        )}
      </header>

      {/* Formulário (funciona sem JS) */}
      <form action="/busca" className="flex gap-2 max-w-xl">
        <input
          type="search"
          name="q"
          defaultValue={q}
          placeholder="Buscar livros, autores, gêneros, listas..."
          aria-label="Termo de busca"
          className="flex-1 px-4 py-2.5 rounded-lg bg-white border border-[#E6DED3] text-sm text-[#0D1B2A] placeholder-[#7B5E3A] focus:outline-none focus:border-[#C9A84C] transition-colors"
        />
        <button
          type="submit"
          className="px-5 py-2.5 bg-[#C9A84C] text-[#4A1628] text-sm font-semibold rounded-lg hover:bg-[#e0bc5e] transition-colors"
        >
          Buscar
        </button>
      </form>

      {!q && (
        <p className="text-sm text-[#4A4A4A]">
          Digite um termo para buscar em livros, autores, gêneros e listas.
        </p>
      )}

      {q && total === 0 && (
        <p className="text-sm text-[#4A4A4A]">
          Nenhum resultado para &ldquo;{q}&rdquo;. Tente outros termos.
        </p>
      )}

      {/* LIVROS */}
      {resultados.livros.length > 0 && (
        <section className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-xl font-serif font-semibold text-[#0D1B2A]">Livros</h2>
            <Link
              href={`/livros?q=${encodeURIComponent(q)}`}
              className="text-sm text-[#C9A84C] font-medium hover:underline"
            >
              Ver todos →
            </Link>
          </div>

          <div className="divide-y divide-[#E6DED3]">
            {resultados.livros.map((l) => (
              <a
                key={l.slug}
                href={`/livros/${l.slug}`}
                className="flex gap-4 items-center py-4 px-2 rounded-xl hover:bg-white hover:shadow-sm transition-all group"
              >
                <div className="flex-shrink-0 w-10 h-14 overflow-hidden rounded border border-[#E6DED3] bg-[#4A1628] flex items-center justify-center">
                  {l.imagem_url ? (
                    <Image
                      src={l.imagem_url}
                      alt={l.titulo}
                      width={40}
                      height={56}
                      unoptimized={!isOptimizableImage(l.imagem_url)}
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <span className="text-[#C9A84C] text-sm font-serif">A</span>
                  )}
                </div>
                <div className="leading-tight">
                  <p className="font-serif font-semibold text-[#0D1B2A] group-hover:text-[#4A1628] transition-colors">
                    {l.titulo}
                  </p>
                  {l.autor && (
                    <p className="text-sm text-[#7B5E3A] mt-0.5">{l.autor}</p>
                  )}
                </div>
              </a>
            ))}
          </div>
        </section>
      )}

      {/* AUTORES */}
      {resultados.autores.length > 0 && (
        <section className="space-y-4">
          <h2 className="text-xl font-serif font-semibold text-[#0D1B2A]">Autores</h2>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
            {resultados.autores.map((a) => {
              const count = a.livros_autores?.length ?? 0;
              return (
                <a
                  key={a.slug}
                  href={`/autores/${a.slug}`}
                  className="group block bg-white border border-[#E6DED3] rounded-xl px-4 py-4 hover:border-[#C9A84C] hover:shadow-sm transition-all"
                >
                  <div className="w-9 h-9 rounded-full bg-[#4A1628] flex items-center justify-center mb-3">
                    <span className="text-[#C9A84C] text-sm font-serif font-semibold">
                      {a.nome.charAt(0).toUpperCase()}
                    </span>
                  </div>
                  <span className="block font-medium text-[#0D1B2A] text-sm leading-snug group-hover:text-[#4A1628] transition-colors">
                    {a.nome}
                  </span>
                  <span className="text-xs text-[#7B5E3A] mt-1 block">
                    {count} {count === 1 ? "livro" : "livros"}
                  </span>
                </a>
              );
            })}
          </div>
        </section>
      )}

      {/* CATEGORIAS / GÊNEROS */}
      {resultados.categorias.length > 0 && (
        <section className="space-y-4">
          <h2 className="text-xl font-serif font-semibold text-[#0D1B2A]">Gêneros</h2>
          <div className="flex flex-wrap gap-2">
            {resultados.categorias.map((c) => (
              <a
                key={c.slug}
                href={`/categorias/${c.slug}`}
                className="text-sm font-semibold px-4 py-2 rounded-full border border-[#E6DED3] bg-white text-[#4A4A4A] hover:border-[#C9A84C] hover:text-[#4A1628] transition-colors"
              >
                {c.nome}
              </a>
            ))}
          </div>
        </section>
      )}

      {/* LISTAS */}
      {resultados.listas.length > 0 && (
        <section className="space-y-4">
          <h2 className="text-xl font-serif font-semibold text-[#0D1B2A]">Listas</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {resultados.listas.map((l) => {
              const count = l.lista_livros?.length ?? 0;
              return (
                <a
                  key={l.slug}
                  href={`/listas/${l.slug}`}
                  className="group block bg-white border border-[#E6DED3] rounded-xl px-5 py-4 hover:border-[#C9A84C] hover:shadow-sm transition-all"
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[#C9A84C] text-xs font-semibold uppercase tracking-wider">
                      Lista editorial
                    </span>
                    <span className="text-xs text-[#7B5E3A] bg-[#F5F0E8] px-2 py-0.5 rounded-full border border-[#E6DED3] flex-shrink-0 ml-2">
                      {count} {count === 1 ? "livro" : "livros"}
                    </span>
                  </div>
                  <span className="block text-[#0D1B2A] font-serif font-semibold text-sm leading-snug group-hover:text-[#4A1628] transition-colors">
                    {l.titulo}
                  </span>
                </a>
              );
            })}
          </div>
        </section>
      )}

    </div>
  );
}
