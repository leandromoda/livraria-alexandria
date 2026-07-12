// Navegação de páginas (server component). Renderiza links reais (<a>) para
// preservar SEO/crawlabilidade e funcionar sem JS. `makeHref` monta a URL de
// cada página preservando os filtros ativos (letra/q/grupo).

type PaginationProps = {
  currentPage: number;
  totalPages: number;
  makeHref: (page: number) => string;
};

// Janela compacta de páginas ao redor da atual: 1 … (p-1) p (p+1) … last
function pageWindow(current: number, total: number): (number | "…")[] {
  const pages = new Set<number>([1, total, current - 1, current, current + 1]);
  const ordered = [...pages]
    .filter((p) => p >= 1 && p <= total)
    .sort((a, b) => a - b);

  const out: (number | "…")[] = [];
  let prev = 0;
  for (const p of ordered) {
    if (prev && p - prev > 1) out.push("…");
    out.push(p);
    prev = p;
  }
  return out;
}

export default function Pagination({
  currentPage,
  totalPages,
  makeHref,
}: PaginationProps) {
  if (totalPages <= 1) return null;

  const base =
    "min-w-9 h-9 px-2 inline-flex items-center justify-center text-sm font-semibold rounded-lg border transition-colors";
  const inactive =
    "text-[#4A4A4A] border-[#E6DED3] bg-white hover:border-[#C9A84C] hover:text-[#4A1628]";
  const active = "bg-[#4A1628] text-[#C9A84C] border-[#4A1628]";
  const disabled = "text-[#C4B9AE] border-[#E6DED3] bg-white pointer-events-none";

  return (
    <nav
      className="flex flex-wrap items-center justify-center gap-1.5 pt-8"
      aria-label="Paginação"
    >
      {currentPage > 1 ? (
        <a href={makeHref(currentPage - 1)} className={`${base} ${inactive}`} rel="prev">
          ← Anterior
        </a>
      ) : (
        <span className={`${base} ${disabled}`}>← Anterior</span>
      )}

      {pageWindow(currentPage, totalPages).map((p, i) =>
        p === "…" ? (
          <span key={`gap-${i}`} className="px-1 text-[#7B5E3A] select-none">
            …
          </span>
        ) : (
          <a
            key={p}
            href={makeHref(p)}
            aria-current={p === currentPage ? "page" : undefined}
            className={`${base} ${p === currentPage ? active : inactive}`}
          >
            {p}
          </a>
        )
      )}

      {currentPage < totalPages ? (
        <a href={makeHref(currentPage + 1)} className={`${base} ${inactive}`} rel="next">
          Próxima →
        </a>
      ) : (
        <span className={`${base} ${disabled}`}>Próxima →</span>
      )}
    </nav>
  );
}
