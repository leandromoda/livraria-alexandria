import { MetadataRoute } from "next";
import { supabase } from "@/lib/supabase";
import { autorIndexavel, listaIndexavel } from "@/lib/indexavel";

const base = "https://livrariaalexandria.com.br";

// O PostgREST devolve no máximo 1.000 linhas por request. Sem paginar, o
// sitemap anunciava 1.000 dos 4.691 livros publicados — medido em 2026-08-06
// contando o sitemap.xml de produção contra `Prefer: count=exact` no banco.
// Mesmo padrão já usado em app/(public)/autores/page.tsx e
// app/(public)/listas/page.tsx.
const PAGE = 1000;

type QueryResult<T> = { data: T[] | null; error: { message: string } | null };

/**
 * Varre uma tabela de 1.000 em 1.000 até esgotar.
 *
 * Erro é logado, não engolido: o bug que motivou esta função ficou meses
 * invisível porque `?? []` transformava um filtro por coluna inexistente
 * (`autores.status_publish`, erro 400) numa seção silenciosamente vazia do
 * sitemap, sem quebrar o build.
 */
async function fetchAll<T>(
  label: string,
  page: (from: number, to: number) => PromiseLike<QueryResult<T>>,
): Promise<T[]> {
  const all: T[] = [];

  for (let from = 0; ; from += PAGE) {
    const { data, error } = await page(from, from + PAGE - 1);

    if (error) {
      console.error(`[sitemap] falha ao carregar ${label}: ${error.message}`);
      break;
    }

    if (!data?.length) break;

    all.push(...data);

    if (data.length < PAGE) break;
  }

  return all;
}

type SlugComData = { slug: string; updated_at: string | null };
type Slug = { slug: string };
type ListaComMembros = { slug: string; lista_livros: unknown[] | null };
type AutorComLivros = {
  slug: string;
  descricao: string | null;
  livros_autores: unknown[] | null;
};

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const [livros, listas, categorias, autores, jogos, infantis] = await Promise.all([
    // `is_publishable` — mesmo critério que app/(public)/livros/[slug]/page.tsx
    // usa para decidir o notFound(). Filtrar por `status = "publish"` incluía 5
    // livros que respondiam 404 (4.691 vs 4.686 em 2026-08-06).
    fetchAll<SlugComData>("livros", (from, to) =>
      supabase
        .from("livros")
        .select("slug, updated_at")
        .eq("is_publishable", true)
        .order("slug")
        .range(from, to),
    ),

    // As tabelas `listas` e `autores` NÃO têm coluna `status_publish` — o filtro
    // antigo `.eq("status_publish", true)` devolvia erro 400 e zerava a seção.
    // O inner join já garante "só o que tem ao menos 1 livro".
    // O embed traz os membros, então dá para contar aqui e aplicar o mesmo
    // corte que o `generateMetadata` da página usa — ver lib/indexavel.ts.
    // Anunciar no sitemap uma URL que a página marca com `noindex` foi
    // exatamente o alerta que o Search Console levantou em agosto.
    fetchAll<ListaComMembros>("listas", (from, to) =>
      supabase
        .from("listas")
        .select("slug, lista_livros!inner(livro_id)")
        .order("slug")
        .range(from, to),
    ),

    // `categorias` de fato tem `status_publish`; o inner join substitui o
    // filtro manual de categorias sem livros.
    fetchAll<Slug>("categorias", (from, to) =>
      supabase
        .from("categorias")
        .select("slug, livros_categorias!inner(livro_id)")
        .eq("status_publish", true)
        .order("slug")
        .range(from, to),
    ),

    // `descricao` entra no select porque o corte de autor depende dela: sem
    // bio E com menos de 2 livros, a página é nome + um item.
    fetchAll<AutorComLivros>("autores", (from, to) =>
      supabase
        .from("autores")
        .select("slug, descricao, livros_autores!inner(livro_id)")
        .order("slug")
        .range(from, to),
    ),

    // Seções do pipeline paralelo — a tabela pode não existir ainda.
    fetchAll<SlugComData>("jogos", (from, to) =>
      supabase
        .from("jogos")
        .select("slug, updated_at")
        .eq("is_publishable", true)
        .order("slug")
        .range(from, to),
    ),

    fetchAll<SlugComData>("livros_infantis", (from, to) =>
      supabase
        .from("livros_infantis")
        .select("slug, updated_at")
        .eq("is_publishable", true)
        .order("slug")
        .range(from, to),
    ),
  ]);

  const livroPages: MetadataRoute.Sitemap = livros.map((l) => ({
    url: `${base}/livros/${l.slug}`,
    lastModified: l.updated_at ?? undefined,
    changeFrequency: "monthly",
    priority: 0.9,
  }));

  const listaPages: MetadataRoute.Sitemap = listas
    .filter((l) => listaIndexavel(l.lista_livros?.length ?? 0))
    .map((l) => ({
      url: `${base}/listas/${l.slug}`,
      changeFrequency: "weekly" as const,
      priority: 0.7,
    }));

  const categoriaPages: MetadataRoute.Sitemap = categorias.map((c) => ({
    url: `${base}/categorias/${c.slug}`,
    changeFrequency: "weekly",
    priority: 0.6,
  }));

  const autorPages: MetadataRoute.Sitemap = autores
    .filter((a) => autorIndexavel(a.descricao, a.livros_autores?.length ?? 0))
    .map((a) => ({
      url: `${base}/autores/${a.slug}`,
      changeFrequency: "monthly" as const,
      priority: 0.6,
    }));

  const jogoPages: MetadataRoute.Sitemap = jogos.map((j) => ({
    url: `${base}/jogos/${j.slug}`,
    lastModified: j.updated_at ?? undefined,
    changeFrequency: "monthly",
    priority: 0.7,
  }));

  const infantilPages: MetadataRoute.Sitemap = infantis.map((l) => ({
    url: `${base}/infantis/${l.slug}`,
    lastModified: l.updated_at ?? undefined,
    changeFrequency: "monthly",
    priority: 0.7,
  }));

  // `/jogos` e `/infantis` emitem `robots: noindex` quando a seção está vazia
  // (jogos/page.tsx, infantis/page.tsx). Anunciar no sitemap uma URL noindex é
  // contradição — foi o alerta "Excluída pela tag noindex" que o Search Console
  // mandou em 2026-07-28, quando `livros_infantis` estava com 0 linhas.
  const hubs = [
    ...(jogoPages.length ? ["/jogos"] : []),
    ...(infantilPages.length ? ["/infantis"] : []),
  ];

  const staticPages: MetadataRoute.Sitemap = [
    "/",
    "/livros",
    ...hubs,
    "/listas",
    "/categorias",
    "/autores",
    "/ofertas",
  ].map((url) => ({
    url: `${base}${url}`,
    changeFrequency: "weekly",
    priority: 0.8,
  }));

  return [
    ...staticPages,
    ...livroPages,
    ...listaPages,
    ...categoriaPages,
    ...autorPages,
    ...jogoPages,
    ...infantilPages,
  ];
}
