import { supabaseAdmin } from "@/lib/supabase-admin";

// ─── Types ────────────────────────────────────────────────────────────────────

type Click = {
  id: string;
  created_at: string;
  referer: string | null;
  utm_source: string | null;
  utm_campaign: string | null;
  session_id: string | null;
  ofertas: {
    marketplace: string;
    livros: {
      titulo: string;
      slug: string;
    } | null;
  } | null;
};

type TopLivro = {
  livro_id: string;
  titulo: string;
  total: number;
};

type CatalogStats = {
  total: number;
  published: number;
  withCover: number;
  withOffer: number;
  withSynopsis: number;
  stageBreakdown: { stage: string; count: number }[];
};

type SourceRow = { label: string; clicks: number; pct: number };

type TrafficSources = {
  byReferer: SourceRow[];
  byMarketplace: SourceRow[];
  byUtm: SourceRow[];
};

type PageViewDay = {
  date: string;
  views: number;
  visitors: number;
};

type VercelAnalyticsSummary = {
  totalViews: number;
  totalVisitors: number;
  history: PageViewDay[];
  error?: string;
};

// ─── Data fetching ────────────────────────────────────────────────────────────

async function getRecentClicks(): Promise<Click[]> {
  const { data } = await supabaseAdmin
    .from("oferta_clicks")
    .select(
      `id, created_at, referer, utm_source, utm_campaign, session_id,
       ofertas ( marketplace, livros ( titulo, slug ) )`
    )
    .order("created_at", { ascending: false })
    .limit(20);

  return (data as unknown as Click[]) ?? [];
}

async function getTopLivros(): Promise<TopLivro[]> {
  const { data } = await supabaseAdmin
    .from("oferta_clicks")
    .select("livro_id, livros ( titulo )")
    .not("livro_id", "is", null);

  if (!data) return [];

  const counts: Record<string, { titulo: string; total: number }> = {};
  for (const row of data as any[]) {
    const id = row.livro_id;
    if (!counts[id]) {
      counts[id] = { titulo: row.livros?.titulo ?? "—", total: 0 };
    }
    counts[id].total++;
  }

  return Object.entries(counts)
    .map(([livro_id, v]) => ({ livro_id, ...v }))
    .sort((a, b) => b.total - a.total)
    .slice(0, 10);
}

async function getCatalogStats(): Promise<CatalogStats> {
  const STAGES = ["slug", "dedup", "synopsis", "review", "cover", "publish"];

  const [
    { count: total },
    { count: published },
    { count: withCover },
    { data: offerRows },
    { data: allRows },
  ] = await Promise.all([
    supabaseAdmin.from("livros").select("*", { count: "exact", head: true }),
    supabaseAdmin
      .from("livros")
      .select("*", { count: "exact", head: true })
      .eq("status", "publish"),
    supabaseAdmin
      .from("livros")
      .select("*", { count: "exact", head: true })
      .not("imagem_url", "is", null),
    // busca livro_id de todas as ofertas ativas para deduplicar em JS
    supabaseAdmin.from("ofertas").select("livro_id").eq("ativa", true),
    supabaseAdmin.from("livros").select("status"),
  ]);

  const withOffer = new Set(
    (offerRows ?? []).map((r: any) => r.livro_id)
  ).size;

  const rows = (allRows ?? []) as any[];

  const withSynopsis = rows.filter((r) =>
    ["synopsis", "review", "cover", "publish"].includes(r.status)
  ).length;

  const stageCounts: Record<string, number> = {};
  for (const r of rows) {
    stageCounts[r.status] = (stageCounts[r.status] ?? 0) + 1;
  }
  const stageBreakdown = STAGES.map((s) => ({
    stage: s,
    count: stageCounts[s] ?? 0,
  }));

  return {
    total: total ?? 0,
    published: published ?? 0,
    withCover: withCover ?? 0,
    withOffer,
    withSynopsis,
    stageBreakdown,
  };
}

// TODO: substituir por RPCs SQL com GROUP BY quando oferta_clicks > 50k rows
async function getTrafficSources(): Promise<TrafficSources> {
  const [clicksRef, clicksMkt, clicksUtm] = await Promise.all([
    supabaseAdmin.from("oferta_clicks").select("referer"),
    supabaseAdmin.from("oferta_clicks").select("ofertas(marketplace)"),
    supabaseAdmin
      .from("oferta_clicks")
      .select("utm_source")
      .not("utm_source", "is", null),
  ]);

  const refCounts: Record<string, number> = {};
  for (const r of (clicksRef.data ?? []) as any[]) {
    const domain = parseDomain(r.referer);
    refCounts[domain] = (refCounts[domain] ?? 0) + 1;
  }

  const mktCounts: Record<string, number> = {};
  for (const r of (clicksMkt.data ?? []) as any[]) {
    const mkt = r.ofertas?.marketplace ?? "(sem marketplace)";
    mktCounts[mkt] = (mktCounts[mkt] ?? 0) + 1;
  }

  const utmCounts: Record<string, number> = {};
  for (const r of (clicksUtm.data ?? []) as any[]) {
    const src = r.utm_source ?? "(sem utm)";
    utmCounts[src] = (utmCounts[src] ?? 0) + 1;
  }

  return {
    byReferer: toSourceRows(refCounts),
    byMarketplace: toSourceRows(mktCounts),
    byUtm: toSourceRows(utmCounts),
  };
}

function parseDomain(url: string | null): string {
  if (!url) return "(direto)";
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "(inválido)";
  }
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

async function getVercelAnalytics(): Promise<VercelAnalyticsSummary> {
  const token = process.env.VERCEL_ACCESS_TOKEN;
  const projectName = "livraria-alexandria";

  if (!token) {
    return { totalViews: 0, totalVisitors: 0, history: [], error: "VERCEL_ACCESS_TOKEN não configurado" };
  }

  try {
    // Busca projeto pelo nome para obter projectId e teamId (se aplicável)
    const projectRes = await fetch(
      `https://api.vercel.com/v9/projects/${projectName}`,
      { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" }
    );
    const projectData = await projectRes.json();
    const projectId = projectData?.id;
    // Para contas pessoais, team é null — não passar teamId nesse caso
    const teamId: string | null = projectData?.team?.id ?? null;

    if (!projectId) {
      return {
        totalViews: 0,
        totalVisitors: 0,
        history: [],
        error: `Projeto "${projectName}" não encontrado na Vercel (status ${projectRes.status})`,
      };
    }

    const now = Date.now();
    const from = now - 30 * 24 * 60 * 60 * 1000;
    const baseParams =
      `projectId=${projectId}&from=${from}&to=${now}&granularity=1d&environment=production` +
      (teamId ? `&teamId=${teamId}` : "");

    // Busca pageviews e visitantes únicos em paralelo
    const [pvRes, visRes] = await Promise.all([
      fetch(
        `https://api.vercel.com/v1/web/insights/stats/pageviews?${baseParams}`,
        { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" }
      ),
      fetch(
        `https://api.vercel.com/v1/web/insights/stats/visitors?${baseParams}`,
        { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" }
      ),
    ]);

    const pvData = await pvRes.json();
    const visData = await visRes.json();

    // Monta mapa de visitantes por data para fazer o join
    const visitorsByDate: Record<string, number> = {};
    for (const d of (visData?.data ?? []) as any[]) {
      if (d.key) visitorsByDate[d.key] = d.total ?? 0;
    }

    // Campos reais da API Vercel: d.key (data) e d.total (pageviews)
    const history: PageViewDay[] = ((pvData?.data ?? []) as any[]).map((d) => ({
      date: d.key ?? "",
      views: d.total ?? 0,
      visitors: visitorsByDate[d.key] ?? 0,
    }));

    if (history.length === 0) {
      return {
        totalViews: 0,
        totalVisitors: 0,
        history: [],
        error: `API retornou dados vazios (status pv=${pvRes.status} vis=${visRes.status}) — verifique o token e o Web Analytics do projeto`,
      };
    }

    const totalViews = history.reduce((acc, d) => acc + d.views, 0);
    const totalVisitors = history.reduce((acc, d) => acc + d.visitors, 0);

    return { totalViews, totalVisitors, history };
  } catch (err) {
    return { totalViews: 0, totalVisitors: 0, history: [], error: String(err) };
  }
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatDate(iso: string) {
  return new Date(iso).toLocaleString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    year: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatDay(dateStr: string) {
  return new Date(dateStr).toLocaleDateString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
  });
}

function pct(a: number, b: number): number {
  return b > 0 ? Math.round((a / b) * 100) : 0;
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default async function AdminPage() {
  const [clicks, topLivros, catalog, analytics, traffic] = await Promise.all([
    getRecentClicks(),
    getTopLivros(),
    getCatalogStats(),
    getVercelAnalytics(),
    getTrafficSources(),
  ]);

  const maxViews =
    analytics.history.length > 0
      ? Math.max(...analytics.history.map((d) => d.views), 1)
      : 1;

  const last7 = analytics.history.slice(-7);
  const views7d = last7.reduce((s, d) => s + d.views, 0);
  const visitors7d = last7.reduce((s, d) => s + d.visitors, 0);

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
            label="Publicados"
            value={catalog.published}
            accent="green"
            sub={`${pct(catalog.published, catalog.total)}% do total`}
          />
          <StatCard
            label="Com capa"
            value={catalog.withCover}
            sub={`${pct(catalog.withCover, catalog.total)}% do total`}
          />
          <StatCard
            label="Com oferta ativa"
            value={catalog.withOffer}
            sub={`${pct(catalog.withOffer, catalog.total)}% do total`}
          />
          <StatCard
            label="Com sinopse"
            value={catalog.withSynopsis}
            sub={`${pct(catalog.withSynopsis, catalog.total)}% do total`}
          />
          <StatCard
            label="Sem capa"
            value={catalog.total - catalog.withCover}
            accent="red"
            sub="aguardando capa"
          />
        </div>
        <StageBar breakdown={catalog.stageBreakdown} total={catalog.total} />
      </section>

      {/* ── Origens de Tráfego ── */}
      <section className="section">
        <h2 className="section-title">Origens de Tráfego — Cliques Afiliados</h2>
        <SourceTable
          title="Por Referer (Domínio)"
          rows={traffic.byReferer}
          emptyMessage="Nenhum clique com referer registrado ainda."
          labelHeader="Domínio"
        />
        <SourceTable
          title="Por Marketplace"
          rows={traffic.byMarketplace}
          emptyMessage="Nenhum clique registrado ainda."
          labelHeader="Marketplace"
        />
        <SourceTable
          title="Por UTM Source"
          rows={traffic.byUtm}
          emptyMessage="Nenhum UTM registrado — adicione ?utm_source= nos links afiliados para rastrear origem."
          labelHeader="Fonte"
        />
      </section>

      {/* ── Visitas ── */}
      <section className="section">
        <h2 className="section-title">Visitas ao Site — últimos 30 dias</h2>

        {analytics.error && (
          <div className="table-wrap" style={{ marginBottom: "1rem" }}>
            <p className="empty" style={{ color: "#f87171" }}>
              ⚠ Erro ao buscar dados da Vercel: {analytics.error}
            </p>
          </div>
        )}

        <div className="stats-grid" style={{ marginBottom: "1.5rem" }}>
          <StatCard label="Pageviews (30 dias)" value={analytics.totalViews} />
          <StatCard label="Visitantes (30 dias)" value={analytics.totalVisitors} />
          <StatCard label="Pageviews (7 dias)" value={views7d} />
          <StatCard label="Visitantes (7 dias)" value={visitors7d} />
        </div>

        {analytics.history.length > 0 ? (
          <>
            <div className="chart-wrap">
              <div className="chart-bars">
                {analytics.history.map((d) => {
                  const heightPct = Math.max(
                    4,
                    Math.round((d.views / maxViews) * 100)
                  );
                  return (
                    <div
                      key={d.date}
                      className="chart-col"
                      title={`${formatDay(d.date)}: ${d.views} views, ${d.visitors} visitantes`}
                    >
                      <span className="bar-label">
                        {d.views > 0 ? d.views : ""}
                      </span>
                      <div className="bar" style={{ height: `${heightPct}%` }} />
                      <span className="bar-date">{formatDay(d.date)}</span>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="table-wrap" style={{ marginTop: "1.5rem" }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Data</th>
                    <th className="align-right">Pageviews</th>
                    <th className="align-right">Visitantes</th>
                  </tr>
                </thead>
                <tbody>
                  {[...analytics.history].reverse().map((d) => (
                    <tr key={d.date}>
                      <td className="mono">{formatDay(d.date)}</td>
                      <td className="align-right">
                        <span className="pill">{d.views}</span>
                      </td>
                      <td className="align-right muted">{d.visitors}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <div className="table-wrap">
            <p className="empty">
              Nenhum dado de visitas disponível. Verifique o token ou aguarde
              dados serem coletados.
            </p>
          </div>
        )}
      </section>

      {/* ── Top livros ── */}
      <section className="section">
        <h2 className="section-title">Top Livros por Cliques</h2>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Título</th>
                <th className="align-right">Cliques</th>
              </tr>
            </thead>
            <tbody>
              {topLivros.length === 0 && (
                <tr>
                  <td colSpan={3} className="empty">
                    Nenhum dado disponível
                  </td>
                </tr>
              )}
              {topLivros.map((l, i) => (
                <tr key={l.livro_id}>
                  <td className="rank">{i + 1}</td>
                  <td>{l.titulo}</td>
                  <td className="align-right">
                    <span className="pill">{l.total}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* ── Cliques recentes ── */}
      <section className="section">
        <h2 className="section-title">Cliques Recentes</h2>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Data</th>
                <th>Livro</th>
                <th>Marketplace</th>
                <th>UTM Source</th>
                <th>UTM Campaign</th>
                <th>Referer</th>
                <th>Session</th>
              </tr>
            </thead>
            <tbody>
              {clicks.length === 0 && (
                <tr>
                  <td colSpan={7} className="empty">
                    Nenhum clique registrado
                  </td>
                </tr>
              )}
              {clicks.map((c) => (
                <tr key={c.id}>
                  <td className="mono">{formatDate(c.created_at)}</td>
                  <td>{c.ofertas?.livros?.titulo ?? "—"}</td>
                  <td>
                    <span className="tag">{c.ofertas?.marketplace ?? "—"}</span>
                  </td>
                  <td className="muted">{c.utm_source ?? "—"}</td>
                  <td className="muted">{c.utm_campaign ?? "—"}</td>
                  <td className="muted truncate">{c.referer ?? "—"}</td>
                  <td className="mono muted">
                    {c.session_id ? c.session_id.slice(0, 8) + "…" : "—"}
                  </td>
                </tr>
              ))}
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

        /* ── Stage breakdown bar ── */
        .stage-bar-wrap {
          margin-top: 1.5rem;
          background: #111520;
          border: 1px solid #1e2430;
          border-radius: 6px;
          padding: 1.25rem 1.5rem;
        }

        .stage-bar {
          display: flex;
          height: 8px;
          border-radius: 4px;
          overflow: hidden;
          gap: 2px;
          margin-bottom: 1rem;
        }

        .stage-segment {
          height: 100%;
          border-radius: 2px;
          transition: opacity 0.15s;
          cursor: default;
          min-width: 3px;
        }

        .stage-segment:hover { opacity: 0.75; }

        .stage-legend {
          display: flex;
          flex-wrap: wrap;
          gap: 0.75rem 1.5rem;
          font-size: 0.65rem;
          color: #64748b;
        }

        .stage-legend-item {
          display: flex;
          align-items: center;
          gap: 0.4rem;
        }

        .stage-dot {
          width: 8px;
          height: 8px;
          border-radius: 2px;
          flex-shrink: 0;
        }

        /* ── Traffic sources subsections ── */
        .subsection-title {
          font-size: 0.65rem;
          letter-spacing: 0.12em;
          text-transform: uppercase;
          color: #64748b;
          margin: 1.5rem 0 0.75rem;
          padding-bottom: 0.35rem;
          border-bottom: 1px solid #141820;
        }

        .subsection-title:first-child { margin-top: 0; }

        /* ── Chart ── */
        .chart-wrap {
          background: #111520;
          border: 1px solid #1e2430;
          border-radius: 6px;
          padding: 1.5rem 1rem 0.75rem;
        }

        .chart-bars {
          display: flex;
          align-items: flex-end;
          gap: 3px;
          height: 120px;
          overflow-x: auto;
        }

        .chart-col {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: flex-end;
          flex: 1;
          min-width: 24px;
          height: 100%;
          gap: 3px;
        }

        .bar {
          width: 100%;
          background: #3b82f6;
          border-radius: 3px 3px 0 0;
          min-height: 4px;
          transition: background 0.15s;
        }

        .chart-col:hover .bar { background: #60a5fa; }

        .bar-label {
          font-size: 0.55rem;
          color: #475569;
          line-height: 1;
        }

        .bar-date {
          font-size: 0.55rem;
          color: #334155;
          margin-top: 4px;
          white-space: nowrap;
        }

        /* ── Tables ── */
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

        .tag {
          background: #1e2430;
          color: #94a3b8;
          padding: 0.1rem 0.45rem;
          border-radius: 4px;
          font-size: 0.7rem;
          text-transform: uppercase;
          letter-spacing: 0.05em;
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

        .mono  { font-family: 'IBM Plex Mono', monospace; }
        .muted { color: #475569; }

        .truncate {
          max-width: 200px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

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

const STAGE_COLORS: Record<string, string> = {
  slug:     "#475569",
  dedup:    "#64748b",
  synopsis: "#3b82f6",
  review:   "#f59e0b",
  cover:    "#a78bfa",
  publish:  "#4ade80",
};

const STAGE_LABELS: Record<string, string> = {
  slug:     "Slug",
  dedup:    "Dedup",
  synopsis: "Sinopse",
  review:   "Review",
  cover:    "Capa",
  publish:  "Publicado",
};

function StageBar({
  breakdown,
  total,
}: {
  breakdown: { stage: string; count: number }[];
  total: number;
}) {
  if (total === 0) return null;

  return (
    <div className="stage-bar-wrap">
      <div className="stage-bar">
        {breakdown.map(({ stage, count }) => {
          const widthPct = Math.max(0.5, (count / total) * 100);
          return (
            <div
              key={stage}
              className="stage-segment"
              style={{
                width: `${widthPct}%`,
                background: STAGE_COLORS[stage] ?? "#334155",
              }}
              title={`${STAGE_LABELS[stage] ?? stage}: ${count} livros`}
            />
          );
        })}
      </div>
      <div className="stage-legend">
        {breakdown.map(({ stage, count }) => (
          <span key={stage} className="stage-legend-item">
            <span
              className="stage-dot"
              style={{ background: STAGE_COLORS[stage] ?? "#334155" }}
            />
            {STAGE_LABELS[stage] ?? stage} ({count})
          </span>
        ))}
      </div>
    </div>
  );
}

function SourceTable({
  title,
  rows,
  emptyMessage,
  labelHeader,
}: {
  title: string;
  rows: SourceRow[];
  emptyMessage: string;
  labelHeader: string;
}) {
  return (
    <>
      <h3 className="subsection-title">{title}</h3>
      <div className="table-wrap" style={{ marginBottom: "0.25rem" }}>
        <table className="data-table">
          <thead>
            <tr>
              <th style={{ width: "2rem" }}>#</th>
              <th>{labelHeader}</th>
              <th className="align-right">Cliques</th>
              <th className="align-right">Proporção</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={4} className="empty">
                  {emptyMessage}
                </td>
              </tr>
            ) : (
              rows.map((row, i) => (
                <tr key={row.label}>
                  <td className="rank">{i + 1}</td>
                  <td>{row.label}</td>
                  <td className="align-right">
                    <span className="pill">{row.clicks}</span>
                  </td>
                  <td className="align-right">
                    <div className="pct-bar-cell">
                      <span
                        className="muted"
                        style={{ fontSize: "0.7rem", minWidth: "2.5rem", textAlign: "right" }}
                      >
                        {row.pct}%
                      </span>
                      <div className="pct-bar-track">
                        <div
                          className="pct-bar-fill"
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
    </>
  );
}
