import { MetadataRoute } from "next";
import { supabase } from "@/lib/supabase";

const base = "https://www.livrariaalexandria.com.br";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const [livros, listas, categorias, autores] = await Promise.all([
    supabase.from("livros").select("slug, updated_at").eq("status", "publish"),
    supabase.from("listas").select("slug").eq("status_publish", true),
    supabase.from("categorias").select("slug").eq("status_publish", true),
    supabase.from("autores").select("slug").eq("status_publish", true),
  ]);

  const staticPages: MetadataRoute.Sitemap = [
    "/",
    "/livros",
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

  const categoriaPages: MetadataRoute.Sitemap = (categorias.data ?? []).map((c) => ({
    url: `${base}/categorias/${c.slug}`,
    changeFrequency: "weekly",
    priority: 0.6,
  }));

  const autorPages: MetadataRoute.Sitemap = (autores.data ?? []).map((a) => ({
    url: `${base}/autores/${a.slug}`,
    changeFrequency: "monthly",
    priority: 0.6,
  }));

  return [...staticPages, ...livroPages, ...listaPages, ...categoriaPages, ...autorPages];
}
