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

type PipelineStats = {
  total: number;
  publishable: number;
  blocked: number;
  is_book: number;
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

async function getPipelineStats(): Promise<PipelineStats> {
  const { count: total } = await supabaseAdmin
    .from("livros")
    .select("*", { count: "exact", head: true });

  const { count: publishable } = await supabaseAdmin
    .from("livros")
    .select("*", { count: "exact", head: true })
    .eq("is_publishable", true);

  const { count: is_book } = await supabaseAdmin
    .from("livros")
    .select("*", { count: "exact", head: true })
    .eq("is_book", true);

  return {
    total: total ?? 0,
    publishable: publishable ?? 0,
    blocked: (total ?? 0) - (publishable ?? 0),
    is_book: is_book ?? 0,
  };
}

async function getVercelAnalytics(): Promise<VercelAnalyticsSummary> {
  const token = process.env.VERCEL_ACCESS_TOKEN;
  const teamSlug = "leandro-modas-projects";
  const projectName = "livraria-alexandria";

  if (!token) {
    return { totalViews: 0, totalVisitors: 0, history: [] };
  }

  try {
    // Busca team ID
    const teamRes = await fetch(
      `https://api.vercel.com/v2/teams?slug=${teamSlug}`,
      { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" }
    );
    const teamData = await teamRes.json();
    const teamId = teamData?.teams?.[0]?.id;

    if (!teamId) return { totalViews: 0, totalVisitors: 0, history: [] };

    // Últimos 30 dias
    const now = Date.now();
    const from = now - 30 * 24 * 60 * 60 * 1000;

    const analyticsRes = await fetch(
      `https://api.vercel.com/v1/web/insights/stats/pageviews` +
        `?projectId=${projectName}&teamId=${teamId}` +
        `&from=${from}&to=${now}&granularity=1d&environment=production`,
      { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" }
    );

    const analyticsData = await analyticsRes.json();
    const dataPoints: Array<{ date: string; count: number; sessions: number }> =
      analyticsData?.data ?? [];

    const history: PageViewDay[] = dataPoints.map((d) => ({
      date: d.date,
      views: d.count ?? 0,
      visitors: d.sessions ?? 0,
    }));

    const totalViews = history.reduce((acc, d) => acc + d.views, 0);
    const totalVisitors = history.reduce((acc, d) => acc + d.visitors, 0);

    return { totalViews, totalVisitors, history };
  } catch {
    return { totalViews: 0, totalVisitors: 0, history: [] };
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

// ─── Page ─────────────────────────────────────────────────────────────────────

export default async function AdminPage() {
  const [clicks, topLivros, pipeline, analytics] = await Promise.all([
    getRecentClicks(),
    getTopLivros(),
    getPipelineStats(),
    getVercelAnalytics(),
  ]);

  const publishRatio =
    pipeline.total > 0
      ? Math.round((pipeline.publishable / pipeline.total) * 100)
      : 0;

  const maxViews =
    analytics.history.length > 0
      ? Math.max(...analytics.history.map((d) => d.views), 1)
      : 1;

  return (
    <main className="admin-root">
      {/* ── Header ── */}
      <header className="admin-header">
        <span className="admin-badge">INTERNAL</span>
        <h1 className="admin-title">Painel de Controle</h1>
        <p className="admin-subtitle">Livraria Alexandria — acesso restrito</p>
      </header>

      {/* ── Pipeline stats ── */}
      <section className="section">
        <h2 className="section-title">Status do Pipeline</h2>
        <div className="stats-grid">
          <StatCard label="Total de livros" value={pipeline.total} />
          <StatCard
            label="Publicáveis"
            value={pipeline.publishable}
            accent="green"
            sub={`${publishRatio}% do total`}
          />
          <StatCard
            label="Bloqueados"
            value={pipeline.blocked}
            accent="red"
          />
          <StatCard label="Confirmados como livro" value={pipeline.is_book} />
        </div>
      </section>

      {/* ── Visitas ── */}
      <section className="section">
        <h2 className="section-title">Visitas ao Site — últimos 30 dias</h2>
        <div className="stats-grid" style={{ marginBottom: "1.5rem" }}>
          <StatCard label="Pageviews totais" value={analytics.totalViews} />
          <StatCard label="Visitantes únicos" value={analytics.totalVisitors} />
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

        .chart-col:hover .bar {
          background: #60a5fa;
        }

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

        .data-table tr:last-child td {
          border-bottom: none;
        }

        .data-table tr:hover td {
          background: #111520;
        }

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

// ─── Sub-component ────────────────────────────────────────────────────────────

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
