import { MetadataRoute } from "next";
import { supabase } from "@/lib/supabase";

const base = "https://livrariaalexandria.com.br";

type SlugComCategoriaCount = {
  slug: string;
  livros_categorias: { livro_id: string }[] | null;
};

type SlugComAutorCount = {
  slug: string;
  livros_autores: { livro_id: string }[] | null;
};

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const [livros, listas, categorias, autores, jogos] = await Promise.all([
    supabase.from("livros").select("slug, updated_at").eq("status", "publish"),
    supabase.from("listas").select("slug").eq("status_publish", true),
    // Inclui apenas categorias com ao menos 1 livro — evita páginas vazias no sitemap
    supabase
      .from("categorias")
      .select("slug, livros_categorias(livro_id)")
      .eq("status_publish", true),
    // Inclui apenas autores com ao menos 1 livro — evita páginas vazias no sitemap
    supabase
      .from("autores")
      .select("slug, livros_autores(livro_id)")
      .eq("status_publish", true),
    // Seção Jogos (tabela própria do pipeline paralelo); enquanto a migração
    // não for aplicada, a query retorna erro e a lista sai vazia
    supabase.from("jogos").select("slug, updated_at").eq("is_publishable", true),
  ]);

  const staticPages: MetadataRoute.Sitemap = [
    "/",
    "/livros",
    "/jogos",
    "/listas",
    "/categorias",
    "/autores",
    "/ofertas",
  ].map((url) => ({
    url: `${base}${url}`,
    changeFrequency: "weekly",
    priority: 0.8,
  }));

  const livroPages: MetadataRoute.Sitemap = (livros.data ?? []).map((l) => ({
    url: `${base}/livros/${l.slug}`,
    lastModified: l.updated_at ?? undefined,
    changeFrequency: "monthly",
    priority: 0.9,
  }));

  const listaPages: MetadataRoute.Sitemap = (listas.data ?? []).map((l) => ({
    url: `${base}/listas/${l.slug}`,
    changeFrequency: "weekly",
    priority: 0.7,
  }));

  const categoriaPages: MetadataRoute.Sitemap = (
    (categorias.data ?? []) as SlugComCategoriaCount[]
  )
    .filter((c) => (c.livros_categorias?.length ?? 0) > 0)
    .map((c) => ({
      url: `${base}/categorias/${c.slug}`,
      changeFrequency: "weekly",
      priority: 0.6,
    }));

  const autorPages: MetadataRoute.Sitemap = (
    (autores.data ?? []) as SlugComAutorCount[]
  )
    .filter((a) => (a.livros_autores?.length ?? 0) > 0)
    .map((a) => ({
      url: `${base}/autores/${a.slug}`,
      changeFrequency: "monthly",
      priority: 0.6,
    }));

  const jogoPages: MetadataRoute.Sitemap = (jogos.data ?? []).map((j) => ({
    url: `${base}/jogos/${j.slug}`,
    lastModified: j.updated_at ?? undefined,
    changeFrequency: "monthly",
    priority: 0.7,
  }));

  return [
    ...staticPages,
    ...livroPages,
    ...listaPages,
    ...categoriaPages,
    ...autorPages,
    ...jogoPages,
  ];
}
