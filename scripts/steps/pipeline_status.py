# ============================================================
# STEP 0 — PIPELINE STATUS
# Livraria Alexandria
#
# Painel de situação do pipeline: funil de livros,
# contadores por step, gargalos evidenciados.
# Não modifica dados — só leitura.
# ============================================================

from pathlib import Path

from core.db import get_conn
from core.logger import log


# =========================
# HELPERS
# =========================

def pct(part, total):
    if not total:
        return 0.0
    return part / total * 100


def bar(part, total, width=20):
    filled = int(pct(part, total) / 100 * width)
    return "█" * filled + "░" * (width - filled)


def q(conn, sql, *params):
    """Executa uma query e retorna o primeiro valor, ou 0 se falhar."""
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        row = cur.fetchone()
        return row[0] if row else 0
    except Exception:
        return 0


# =========================
# SEEDS PENDENTES
# =========================

def count_seeds_pendentes(conn):
    """Conta arquivos NNN_offer_seed(s).json ainda não ingeridos."""

    seeds_dir = Path(__file__).resolve().parents[1] / "data" / "seeds"

    if not seeds_dir.exists():
        return 0

    arquivos = list(seeds_dir.glob("*_offer_seed*.json"))

    if not arquivos:
        return 0

    # Desconta os que já estão registrados em seed_imports
    try:
        cur = conn.cursor()
        cur.execute("SELECT filename FROM seed_imports")
        ingeridos = {r[0] for r in cur.fetchall()}
    except Exception:
        ingeridos = set()

    pendentes = [f for f in arquivos if f.name not in ingeridos]

    return len(pendentes)


# =========================
# RUN
# =========================

def run():

    conn = get_conn()

    # ── Livros ──────────────────────────────────────────────────

    total = q(conn, "SELECT COUNT(*) FROM livros")

    if not total:
        log("[STATUS] Banco vazio — nenhum livro importado.")
        conn.close()
        return

    # Por idioma
    cur = conn.cursor()
    cur.execute("""
        SELECT COALESCE(idioma, 'UNKNOWN'), COUNT(*)
        FROM livros
        GROUP BY 1
        ORDER BY 2 DESC
    """)
    por_idioma = cur.fetchall()

    # Funil principal
    com_descricao      = q(conn, "SELECT COUNT(*) FROM livros WHERE descricao IS NOT NULL AND trim(descricao) != ''")
    com_offer_url      = q(conn, "SELECT COUNT(*) FROM livros WHERE offer_url IS NOT NULL AND trim(offer_url) != ''")
    com_scraper        = q(conn, "SELECT COUNT(*) FROM livros WHERE status_enrich IN (1, 2)")
    com_slug           = q(conn, "SELECT COUNT(*) FROM livros WHERE status_slug = 1")
    deduplicados       = q(conn, "SELECT COUNT(*) FROM livros WHERE status_dedup = 1")
    revisados          = q(conn, "SELECT COUNT(*) FROM livros WHERE status_review = 1")
    categorizados      = q(conn, "SELECT COUNT(*) FROM livros WHERE status_categorize = 1")
    com_sinopse        = q(conn, "SELECT COUNT(*) FROM livros WHERE status_synopsis = 1")
    com_capa           = q(conn, "SELECT COUNT(*) FROM livros WHERE status_cover IN (1, 2)")
    publicaveis        = q(conn, "SELECT COUNT(*) FROM livros WHERE is_publishable = 1")
    publicados         = q(conn, "SELECT COUNT(*) FROM livros WHERE status_publish = 1")
    oferta_publicada   = q(conn, "SELECT COUNT(*) FROM livros WHERE status_publish_oferta = 1")

    # categorias temáticas publicadas (livros com ao menos 1 categoria publicada)
    pub_categorias     = q(conn, """
        SELECT COUNT(DISTINCT livro_id) FROM livros_categorias_tematicas
    """)

    # Pendentes (gargalos)
    revisados_sem_sinopse  = q(conn, "SELECT COUNT(*) FROM livros WHERE status_review = 1 AND status_synopsis = 0")
    com_sinopse_sem_gate   = q(conn, "SELECT COUNT(*) FROM livros WHERE status_synopsis = 1 AND (is_publishable IS NULL OR is_publishable = 0)")
    publicaveis_nao_pub    = q(conn, "SELECT COUNT(*) FROM livros WHERE is_publishable = 1 AND status_publish = 0")
    pub_sem_oferta         = q(conn, "SELECT COUNT(*) FROM livros WHERE status_publish = 1 AND status_publish_oferta = 0 AND offer_url IS NOT NULL")

    # ── Autores ─────────────────────────────────────────────────

    total_autores     = q(conn, "SELECT COUNT(*) FROM autores")
    autores_publicados = q(conn, "SELECT COUNT(*) FROM autores WHERE status_publish = 1")
    autores_pendentes  = total_autores - autores_publicados

    # ── Seeds ───────────────────────────────────────────────────

    seeds_pendentes = count_seeds_pendentes(conn)

    # ── Ofertas (tabela livros) ──────────────────────────────────

    total_com_oferta   = q(conn, "SELECT COUNT(*) FROM livros WHERE offer_url IS NOT NULL")
    oferta_ativa       = q(conn, "SELECT COUNT(*) FROM livros WHERE COALESCE(offer_status, 'active') = 'active' AND offer_url IS NOT NULL")
    oferta_indisponivel = q(conn, "SELECT COUNT(*) FROM livros WHERE offer_status = 'unavailable'")

    conn.close()

    # ── Exibição ─────────────────────────────────────────────────

    sep = "─" * 62

    print()
    print("=" * 62)
    print("  LIVRARIA ALEXANDRIA — STATUS DO PIPELINE")
    print("=" * 62)

    # Seeds
    print()
    print(f"  SEEDS AGUARDANDO INGESTÃO: {seeds_pendentes} arquivo(s)")

    # Livros por idioma
    print()
    print(f"  LIVROS — TOTAL: {total:,}")
    print(f"  {sep}")
    for lang, cnt in por_idioma:
        print(f"    {lang:<10} {cnt:>5,}  {bar(cnt, total, 16)}  {pct(cnt, total):5.1f}%")

    # Funil
    steps = [
        ("1  Importados",          total,            total),
        ("2  Com descrição",        com_descricao,    total),
        ("3  Com offer_url",        com_offer_url,    total),
        ("4  Marketplace scraper",  com_scraper,      total),
        ("5  Com slug",             com_slug,         total),
        ("8  Deduplicados",         deduplicados,     total),
        ("9  Com review",           revisados,        total),
        ("10 Categorizados",        categorizados,    total),
        ("11 Com sinopse",          com_sinopse,      total),
        ("12 Com capa",             com_capa,         total),
        ("13 Publicáveis (gate)",   publicaveis,      total),
        ("14 Publicados",           publicados,       total),
        ("16 Cat. pub. (livros)",   pub_categorias,   total),
        ("17 Oferta publicada",     oferta_publicada, total),
    ]

    print()
    print("  FUNIL DO PIPELINE")
    print(f"  {sep}")

    prev = total
    for label, cnt, base in steps:
        drop = prev - cnt if label != "1  Importados" else 0
        drop_str = f"  (↓{drop:,})" if drop > 0 else ""
        print(f"  Step {label:<24} {cnt:>5,}  {bar(cnt, base, 16)}  {pct(cnt, base):5.1f}%{drop_str}")
        prev = cnt

    # Gargalos
    gargalos = []

    if revisados_sem_sinopse > 0:
        gargalos.append(f"Step 11 (Sinopses):         {revisados_sem_sinopse:>5,} com review mas sem sinopse")
    if com_sinopse_sem_gate > 0:
        gargalos.append(f"Step 13 (Quality Gate):     {com_sinopse_sem_gate:>5,} com sinopse mas não publicáveis")
    if publicaveis_nao_pub > 0:
        gargalos.append(f"Step 14 (Publicar):         {publicaveis_nao_pub:>5,} publicáveis ainda não publicados")
    if pub_sem_oferta > 0:
        gargalos.append(f"Step 17 (Pub. Ofertas):     {pub_sem_oferta:>5,} publicados sem oferta publicada")
    if seeds_pendentes > 0:
        gargalos.append(f"Step 1  (Seeds):            {seeds_pendentes:>5,} arquivo(s) aguardando ingestão")

    if gargalos:
        print()
        print("  GARGALOS")
        print(f"  {sep}")
        for g in gargalos:
            print(f"  ⚠  {g}")

    # Autores
    print()
    print(f"  AUTORES — TOTAL: {total_autores:,}")
    print(f"  {sep}")
    print(f"    Publicados  {autores_publicados:>5,}  {bar(autores_publicados, total_autores, 16)}  {pct(autores_publicados, total_autores):5.1f}%")
    print(f"    Pendentes   {autores_pendentes:>5,}  {bar(autores_pendentes,   total_autores, 16)}  {pct(autores_pendentes, total_autores):5.1f}%")

    # Ofertas
    print()
    print(f"  OFERTAS (livros com offer_url): {total_com_oferta:,}")
    print(f"  {sep}")
    print(f"    Ativas         {oferta_ativa:>5,}  {bar(oferta_ativa, total_com_oferta, 16)}  {pct(oferta_ativa, total_com_oferta):5.1f}%")
    print(f"    Indisponíveis  {oferta_indisponivel:>5,}  {bar(oferta_indisponivel, total_com_oferta, 16)}  {pct(oferta_indisponivel, total_com_oferta):5.1f}%")

    print()
    print("=" * 62)
    print()
