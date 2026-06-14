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
  const deduped: any[] = [];
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
  const deduped: any[] = [];
  for (const r of (data ?? []) as any[]) {
    const bucket = Math.floor(new Date(r.created_at).getTime() / (30 * 60 * 1000));
    const key = `${r.ip_hash}:${r.oferta_id}:${bucket}`;
    if (!seen.has(key)) {
      seen.add(key);
      deduped.push(r);
    }
  }

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

// ─── Page ─────────────────────────────────────────────────────────────────────

export default async function AdminPage() {
  const [catalog, marketplaceClicks, topLivros, recentClicks] = await Promise.all([
    getCatalogStats(),
    getMarketplaceClicks(),
    getTopLivros(),
    getRecentClicks(),
  ]);

  return (
    <main className="admin-root">
      {/* ── Header ── */}
      <header className="admin-header">
        <span className="admin-badge">INTERNAL</span>
        <h1 className="admin-title">Painel de Controle</h1>
        <p className="admin-subtitle">Livraria Alexandria — acesso restrito</p>
      </header>

      {/* ── Status do Catálogo ── */}
      <section className="section">
        <h2 className="section-title">Status do Catálogo</h2>
        <div className="stats-grid">
          <StatCard label="Total de livros" value={catalog.total} />
          <StatCard
            label="Publicados (ativos)"
            value={catalog.published}
            accent="green"
            sub={`${pct(catalog.published, catalog.total)}% do total`}
          />
          <StatCard
            label="Despublicados"
            value={catalog.blacklisted}
            accent="red"
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
            accent="red"
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
      <section className="section">
        <h2 className="section-title">Cliques por Marketplace</h2>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th style={{ width: "2rem" }}>#</th>
                <th>Marketplace</th>
                <th className="align-right">Cliques</th>
                <th className="align-right">Proporção</th>
              </tr>
            </thead>
            <tbody>
              {marketplaceClicks.length === 0 ? (
                <tr>
                  <td colSpan={4} className="empty">Nenhum clique registrado ainda.</td>
                </tr>
              ) : (
                marketplaceClicks.map((row, i) => (
                  <tr key={row.label}>
                    <td className="rank">{i + 1}</td>
                    <td>{row.label}</td>
                    <td className="align-right">
                      <span className="pill">{row.clicks}</span>
                    </td>
                    <td className="align-right">
                      <div className="pct-bar-cell">
                        <span className="muted" style={{ fontSize: "0.7rem", minWidth: "2.5rem", textAlign: "right" }}>
                          {row.pct}%
                        </span>
                        <div className="pct-bar-track">
                          <div className="pct-bar-fill" style={{ width: `${row.pct}%` }} />
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

      <style>{`
        .admin-root {
          min-height: 100vh;
          background: #0a0c10;
          color: #e2e8f0;
          font-family: 'IBM Plex Mono', 'Courier New', monospace;
          padding: 2.5rem 2rem 4rem;
          max-width: 1200px;
          margin: 0 auto;
        }

        .admin-header {
          border-left: 3px solid #f59e0b;
          padding-left: 1.25rem;
          margin-bottom: 3rem;
        }

        .admin-badge {
          font-size: 0.65rem;
          letter-spacing: 0.2em;
          color: #f59e0b;
          font-weight: 700;
        }

        .admin-title {
          font-size: 1.75rem;
          font-weight: 700;
          color: #f8fafc;
          margin: 0.25rem 0 0.25rem;
          letter-spacing: -0.02em;
        }

        .admin-subtitle {
          font-size: 0.8rem;
          color: #64748b;
          margin: 0;
        }

        .section {
          margin-bottom: 3rem;
        }

        .section-title {
          font-size: 0.7rem;
          letter-spacing: 0.15em;
          text-transform: uppercase;
          color: #94a3b8;
          margin-bottom: 1rem;
          padding-bottom: 0.5rem;
          border-bottom: 1px solid #1e2430;
        }

        .stats-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
          gap: 1rem;
        }

        .stat-card {
          background: #111520;
          border: 1px solid #1e2430;
          border-radius: 6px;
          padding: 1.25rem 1.5rem;
        }

        .stat-label {
          font-size: 0.7rem;
          color: #64748b;
          letter-spacing: 0.08em;
          text-transform: uppercase;
          margin-bottom: 0.5rem;
        }

        .stat-value {
          font-size: 2rem;
          font-weight: 700;
          line-height: 1;
          color: #f8fafc;
        }

        .stat-value.green { color: #4ade80; }
        .stat-value.red   { color: #f87171; }

        .stat-sub {
          font-size: 0.7rem;
          color: #475569;
          margin-top: 0.35rem;
        }

        .table-wrap {
          overflow-x: auto;
          border: 1px solid #1e2430;
          border-radius: 6px;
        }

        .data-table {
          width: 100%;
          border-collapse: collapse;
          font-size: 0.8rem;
        }

        .data-table th {
          background: #111520;
          color: #64748b;
          font-size: 0.65rem;
          letter-spacing: 0.1em;
          text-transform: uppercase;
          padding: 0.75rem 1rem;
          text-align: left;
          border-bottom: 1px solid #1e2430;
          white-space: nowrap;
        }

        .data-table td {
          padding: 0.65rem 1rem;
          border-bottom: 1px solid #141820;
          color: #cbd5e1;
          vertical-align: middle;
        }

        .data-table tr:last-child td { border-bottom: none; }
        .data-table tr:hover td { background: #111520; }

        .align-right { text-align: right; }

        .rank {
          color: #475569;
          font-size: 0.7rem;
          width: 2rem;
        }

        .pill {
          background: #1e2d40;
          color: #60a5fa;
          padding: 0.15rem 0.5rem;
          border-radius: 999px;
          font-size: 0.75rem;
          font-weight: 700;
        }

        .pct-bar-cell {
          display: flex;
          align-items: center;
          gap: 0.5rem;
          justify-content: flex-end;
        }

        .pct-bar-track {
          width: 80px;
          height: 4px;
          background: #1e2430;
          border-radius: 2px;
          overflow: hidden;
          flex-shrink: 0;
        }

        .pct-bar-fill {
          height: 100%;
          background: #3b82f6;
          border-radius: 2px;
        }

        .muted { color: #475569; }

        .empty {
          text-align: center;
          color: #334155;
          padding: 2rem !important;
          font-style: italic;
        }
      `}</style>
    </main>
  );
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function StatCard({
  label,
  value,
  accent,
  sub,
}: {
  label: string;
  value: number;
  accent?: "green" | "red";
  sub?: string;
}) {
  return (
    <div className="stat-card">
      <div className="stat-label">{label}</div>
      <div className={`stat-value${accent ? ` ${accent}` : ""}`}>{value}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  );
}
