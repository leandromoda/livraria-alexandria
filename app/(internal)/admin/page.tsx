export const dynamic = "force-dynamic";

import { supabaseAdmin } from "@/lib/supabase-admin";

// ─── Types ────────────────────────────────────────────────────────────────────

type CatalogStats = {
  total: number;
  published: number;
  blacklisted: number;
  withCover: number;
  withOffer: number;
};

type SourceRow = { label: string; clicks: number; pct: number };

type TopLivro = { titulo: string; slug: string; clicks: number };
type RecentClick = { id: string; titulo: string; slug: string; marketplace: string; created_at: string };

// ─── Data fetching ────────────────────────────────────────────────────────────

async function getCatalogStats(): Promise<CatalogStats> {
  const [
    { count: total },
    { count: published },
    { count: blacklisted },
    { count: withCover },
    { data: offerRows },
  ] = await Promise.all([
    supabaseAdmin.from("livros").select("*", { count: "exact", head: true }),
    supabaseAdmin
      .from("livros")
      .select("*", { count: "exact", head: true })
      .eq("is_publishable", true),
    supabaseAdmin
      .from("livros")
      .select("*", { count: "exact", head: true })
      .eq("is_publishable", false),
    supabaseAdmin
      .from("livros")
      .select("*", { count: "exact", head: true })
      .eq("is_publishable", true)
      .not("imagem_url", "is", null),
    supabaseAdmin.from("ofertas").select("livro_id").eq("ativa", true),
  ]);

  const withOffer = new Set(
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (offerRows ?? []).map((r: any) => r.livro_id)
  ).size;

  return {
    total: total ?? 0,
    published: published ?? 0,
    blacklisted: blacklisted ?? 0,
    withCover: withCover ?? 0,
    withOffer,
  };
}

async function getMarketplaceClicks(): Promise<SourceRow[]> {
  const { data } = await supabaseAdmin
    .from("oferta_clicks")
    .select("ofertas(marketplace)");

  const counts: Record<string, number> = {};
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  for (const r of (data ?? []) as any[]) {
    const mkt = r.ofertas?.marketplace ?? "(sem marketplace)";
    counts[mkt] = (counts[mkt] ?? 0) + 1;
  }
  return toSourceRows(counts);
}

function toSourceRows(counts: Record<string, number>): SourceRow[] {
  const entries = Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10);
  const total = entries.reduce((s, [, v]) => s + v, 0) || 1;
  return entries.map(([label, clicks]) => ({
    label,
    clicks,
    pct: Math.round((clicks / total) * 100),
  }));
}

async function getTopLivros(): Promise<TopLivro[]> {
  const { data } = await supabaseAdmin
    .from("oferta_clicks")
    .select("livro_id, oferta_id, ip_hash, created_at, ofertas(livros(titulo, slug))")
    .order("created_at", { ascending: false })
    .limit(5000);

  const seen = new Set<string>();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const deduped: any[] = [];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  for (const r of (data ?? []) as any[]) {
    const bucket = Math.floor(new Date(r.created_at).getTime() / (30 * 60 * 1000));
    const key = `${r.ip_hash}:${r.oferta_id}:${bucket}`;
    if (!seen.has(key)) {
      seen.add(key);
      deduped.push(r);
    }
  }

  const counts: Record<string, TopLivro> = {};
  for (const r of deduped) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const livro = (r.ofertas as any)?.livros;
    if (!livro || !r.livro_id) continue;
    if (!counts[r.livro_id]) {
      counts[r.livro_id] = { titulo: livro.titulo, slug: livro.slug, clicks: 0 };
    }
    counts[r.livro_id].clicks++;
  }

  return Object.values(counts)
    .sort((a, b) => b.clicks - a.clicks)
    .slice(0, 10);
}

async function getRecentClicks(): Promise<RecentClick[]> {
  const { data } = await supabaseAdmin
    .from("oferta_clicks")
    .select("id, oferta_id, ip_hash, created_at, ofertas(marketplace, livros(titulo, slug))")
    .order("created_at", { ascending: false })
    .limit(500);

  const seen = new Set<string>();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const deduped: any[] = [];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  for (const r of (data ?? []) as any[]) {
    const bucket = Math.floor(new Date(r.created_at).getTime() / (30 * 60 * 1000));
    const key = `${r.ip_hash}:${r.oferta_id}:${bucket}`;
    if (!seen.has(key)) {
      seen.add(key);
      deduped.push(r);
    }
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return deduped.slice(0, 20).map((r: any) => ({
    id: r.id,
    titulo: r.ofertas?.livros?.titulo ?? "—",
    slug: r.ofertas?.livros?.slug ?? "",
    marketplace: r.ofertas?.marketplace ?? "—",
    created_at: r.created_at,
  }));
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function pct(a: number, b: number): number {
  return b > 0 ? Math.round((a / b) * 100) : 0;
}

const thClass =
  "text-xs uppercase tracking-[0.1em] text-[#7B5E3A] font-medium px-4 py-3 border-b border-[#E6DED3]";
const tdClass = "px-4 py-2.5 border-b border-[#E6DED3]";

// ─── Page ─────────────────────────────────────────────────────────────────────

export default async function AdminPage() {
  const [catalog, marketplaceClicks, topLivros, recentClicks] = await Promise.all([
    getCatalogStats(),
    getMarketplaceClicks(),
    getTopLivros(),
    getRecentClicks(),
  ]);

  return (
    <main className="max-w-[1200px] mx-auto px-6 sm:px-8 pt-10 pb-16 font-sans">
      {/* ── Header ── */}
      <header className="mb-8 border-l-4 border-[#C9A84C] pl-4">
        <span className="text-xs uppercase tracking-[0.2em] text-[#7B5E3A] font-semibold">
          Painel interno
        </span>
        <h1 className="text-2xl sm:text-3xl font-serif font-semibold text-[#0D1B2A] mt-1">
          Painel de Controle
        </h1>
        <p className="text-sm text-[#4A4A4A] mt-1">
          Livraria Alexandria — acesso restrito
        </p>
      </header>

      <div className="space-y-10">
        {/* ── Status do Catálogo ── */}
        <section>
          <h2 className="text-lg font-serif font-semibold text-[#0D1B2A] mb-4">
            Status do Catálogo
          </h2>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-4">
            <StatCard label="Total de livros" value={catalog.total} />
            <StatCard
              label="Publicados (ativos)"
              value={catalog.published}
              highlight
              sub={`${pct(catalog.published, catalog.total)}% do total`}
            />
            <StatCard
              label="Despublicados"
              value={catalog.blacklisted}
              sub={`${pct(catalog.blacklisted, catalog.total)}% do total`}
            />
            <StatCard
              label="Com capa (ativos)"
              value={catalog.withCover}
              sub={`${pct(catalog.withCover, catalog.published)}% dos publicados`}
            />
            <StatCard
              label="Com oferta ativa"
              value={catalog.withOffer}
              sub={`${pct(catalog.withOffer, catalog.published)}% dos publicados`}
            />
            <StatCard
              label="Sem capa (ativos)"
              value={catalog.published - catalog.withCover}
              sub="aguardando capa"
            />
          </div>
        </section>

        {/* ── Top Livros por Cliques ── */}
        {topLivros.length > 0 && (
          <section className="bg-white border border-[#E6DED3] rounded-2xl px-8 py-7">
            <h2 className="text-lg font-serif font-semibold text-[#0D1B2A] mb-4">
              Top Livros por Cliques
            </h2>
            <ol className="space-y-2">
              {topLivros.map((l, i) => (
                <li key={l.slug} className="flex items-center justify-between text-sm">
                  <span className="flex items-center gap-3">
                    <span className="w-5 text-right text-[#7B5E3A] font-medium">{i + 1}.</span>
                    <a
                      href={`/livros/${l.slug}`}
                      className="text-[#0D1B2A] hover:text-[#4A1628] transition-colors"
                    >
                      {l.titulo}
                    </a>
                  </span>
                  <span className="text-[#C9A84C] font-semibold">{l.clicks} cliques</span>
                </li>
              ))}
            </ol>
          </section>
        )}

        {/* ── Cliques Recentes ── */}
        {recentClicks.length > 0 && (
          <section className="bg-white border border-[#E6DED3] rounded-2xl px-8 py-7">
            <h2 className="text-lg font-serif font-semibold text-[#0D1B2A] mb-4">
              Cliques Recentes
            </h2>
            <div className="space-y-2">
              {recentClicks.map((c) => (
                <div key={c.id} className="flex items-center justify-between text-sm">
                  <span className="flex items-center gap-3">
                    <a
                      href={`/livros/${c.slug}`}
                      className="text-[#0D1B2A] hover:text-[#4A1628] transition-colors"
                    >
                      {c.titulo}
                    </a>
                    <span className="text-xs text-[#7B5E3A]">{c.marketplace}</span>
                  </span>
                  <span className="text-xs text-[#4A4A4A]">
                    {new Date(c.created_at).toLocaleString("pt-BR", {
                      day: "2-digit",
                      month: "2-digit",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </span>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* ── Cliques por Marketplace ── */}
        <section>
          <h2 className="text-lg font-serif font-semibold text-[#0D1B2A] mb-4">
            Cliques por Marketplace
          </h2>
          <div className="overflow-x-auto bg-white border border-[#E6DED3] rounded-2xl">
            <table className="w-full text-sm border-separate border-spacing-0">
              <thead>
                <tr>
                  <th className={`w-8 text-left ${thClass}`}>#</th>
                  <th className={`text-left ${thClass}`}>Marketplace</th>
                  <th className={`text-right ${thClass}`}>Cliques</th>
                  <th className={`text-right ${thClass}`}>Proporção</th>
                </tr>
              </thead>
              <tbody>
                {marketplaceClicks.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="text-center text-[#7B5E3A] italic px-4 py-8">
                      Nenhum clique registrado ainda.
                    </td>
                  </tr>
                ) : (
                  marketplaceClicks.map((row, i) => (
                    <tr
                      key={row.label}
                      className="hover:bg-[#F5F0E8] transition-colors last:[&>td]:border-b-0"
                    >
                      <td className={`text-xs text-[#7B5E3A] ${tdClass}`}>{i + 1}</td>
                      <td className={`text-[#0D1B2A] ${tdClass}`}>{row.label}</td>
                      <td className={`text-right ${tdClass}`}>
                        <span className="inline-block bg-[#4A1628] text-white px-2 py-0.5 rounded-full text-xs font-semibold">
                          {row.clicks}
                        </span>
                      </td>
                      <td className={`text-right ${tdClass}`}>
                        <div className="flex items-center gap-2 justify-end">
                          <span className="text-xs text-[#7B5E3A] min-w-[2.5rem] text-right">
                            {row.pct}%
                          </span>
                          <div className="w-20 h-1 bg-[#E6DED3] rounded-full overflow-hidden shrink-0">
                            <div
                              className="h-full bg-[#C9A84C] rounded-full"
                              style={{ width: `${row.pct}%` }}
                            />
                          </div>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </main>
  );
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function StatCard({
  label,
  value,
  highlight,
  sub,
}: {
  label: string;
  value: number;
  highlight?: boolean;
  sub?: string;
}) {
  return (
    <div className="bg-white border border-[#E6DED3] rounded-xl px-5 py-4">
      <div className="text-xs uppercase tracking-[0.08em] text-[#7B5E3A] mb-2">{label}</div>
      <div
        className={`text-3xl font-serif font-semibold leading-none ${
          highlight ? "text-[#4A1628]" : "text-[#0D1B2A]"
        }`}
      >
        {value.toLocaleString("pt-BR")}
      </div>
      {sub && <div className="text-xs text-[#4A4A4A] mt-1.5">{sub}</div>}
    </div>
  );
}
