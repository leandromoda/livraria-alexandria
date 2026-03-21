# ============================================================
# STEP 22 — REPAIR
# Livraria Alexandria
#
# Detecta livros publicados com dados ruins (sinopse genérica,
# capa errada, preço zero) e reseta os flags de status para
# permitir re-processamento pelo pipeline.
#
# Uso: rodar em dry-run primeiro, depois confirmar execução.
# Após executar: re-rodar steps 11 (sinopses), 12 (capas),
#                13 (quality gate), 14 (publicar), 17 (ofertas)
# ============================================================

from core.db import get_conn
from core.logger import log


# =========================
# DETECÇÃO DE SINOPSE GENÉRICA
# =========================

GENERIC_MARKERS = [
    "contexto não especificado",
    "escopo narrativo",
    "jornada que convida o leitor",
    "aspectos fundamentais da vida",
    "complexidades de uma situação central",
    "série de eventos que moldam",
    "narrativa que se desenrola em um contexto",
    "condição humana, às relações interpessoais",
    "trama se desenvolve através de uma série",
]

COVER_TRUSTED_DOMAINS = [
    "amazon",
    "googleapis",
    "openlibrary",
    "books.google",
    "m.media-amazon",
    "images-na.ssl-images-amazon",
    "covers.openlibrary",
]


def is_generic_synopsis(texto):
    if not texto:
        return False
    lower = texto.lower()
    return any(marker in lower for marker in GENERIC_MARKERS)


def is_suspicious_cover(imagem_url):
    """Retorna True se a URL de capa não pertence a um domínio confiável de livros."""
    if not imagem_url:
        return True  # sem capa = suspeito
    lower = imagem_url.lower()
    return not any(domain in lower for domain in COVER_TRUSTED_DOMAINS)


# =========================
# FETCH
# =========================

def fetch_published(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT id, titulo, slug, sinopse, imagem_url
        FROM livros
        WHERE status_publish = 1
    """)
    return cur.fetchall()


def fetch_zero_price_offers(conn):
    """Retorna livros publicados que possuem apenas ofertas com preço 0 ou NULL."""
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT l.id, l.titulo, l.slug
        FROM livros l
        WHERE l.status_publish = 1
          AND EXISTS (
              SELECT 1 FROM livros AS o_ref
              WHERE o_ref.id = l.id
                AND (l.preco IS NULL OR l.preco = 0)
                AND l.offer_url IS NOT NULL
          )
    """)
    return cur.fetchall()


# =========================
# DIAGNÓSTICO
# =========================

def diagnosticar(conn):
    rows = fetch_published(conn)

    bad_synopsis  = []
    bad_cover     = []

    for livro_id, titulo, slug, sinopse, imagem_url in rows:
        if is_generic_synopsis(sinopse):
            bad_synopsis.append((livro_id, titulo, slug))
        if is_suspicious_cover(imagem_url):
            bad_cover.append((livro_id, titulo, slug, imagem_url))

    # Preço zero: livros publicados com preco=0 ou NULL e offer_url preenchida
    cur = conn.cursor()
    cur.execute("""
        SELECT id, titulo, slug, preco
        FROM livros
        WHERE status_publish = 1
          AND offer_url IS NOT NULL
          AND (preco IS NULL OR preco = 0)
    """)
    bad_price = [(r[0], r[1], r[2], r[3]) for r in cur.fetchall()]

    return bad_synopsis, bad_cover, bad_price


# =========================
# RESET
# =========================

def reset_synopsis(conn, ids):
    """Reseta sinopse genérica: status_synopsis=0, status_publish=0, sinopse=NULL."""
    cur = conn.cursor()
    for livro_id in ids:
        cur.execute("""
            UPDATE livros
            SET sinopse          = NULL,
                status_synopsis  = 0,
                status_publish   = 0,
                is_publishable   = 0,
                updated_at       = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (livro_id,))
    conn.commit()


def reset_cover(conn, ids):
    """Reseta capa suspeita: status_cover=0, imagem_url=NULL, status_publish=0."""
    cur = conn.cursor()
    for livro_id in ids:
        cur.execute("""
            UPDATE livros
            SET imagem_url       = NULL,
                status_cover     = 0,
                status_publish   = 0,
                is_publishable   = 0,
                updated_at       = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (livro_id,))
    conn.commit()


def reset_offer(conn, ids):
    """Reseta ofertas com preço zero para re-publicação."""
    cur = conn.cursor()
    for livro_id in ids:
        cur.execute("""
            UPDATE livros
            SET status_publish_oferta = 0,
                updated_at            = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (livro_id,))
    conn.commit()


# =========================
# RUN
# =========================

def run():

    conn = get_conn()

    log("[REPAIR] Diagnóstico de publicações com dados ruins…")

    bad_synopsis, bad_cover, bad_price = diagnosticar(conn)

    total_issues = len(bad_synopsis) + len(bad_cover) + len(bad_price)

    if total_issues == 0:
        log("[REPAIR] Nenhuma publicação com dados ruins detectada.")
        conn.close()
        return

    # --- Relatório ---

    print()
    print("=" * 60)
    print("REPAIR — RELATÓRIO DE PROBLEMAS DETECTADOS")
    print("=" * 60)

    if bad_synopsis:
        print(f"\n[SINOPSE GENÉRICA] {len(bad_synopsis)} livros:")
        for _, titulo, slug in bad_synopsis:
            print(f"  • {titulo}  ({slug})")

    if bad_cover:
        print(f"\n[CAPA SUSPEITA/AUSENTE] {len(bad_cover)} livros:")
        for _, titulo, slug, url in bad_cover:
            url_display = url if url else "(sem URL)"
            print(f"  • {titulo}  ({slug})")
            print(f"    URL: {url_display[:80]}")

    if bad_price:
        print(f"\n[PREÇO ZERO/NULO] {len(bad_price)} livros:")
        for _, titulo, slug, preco in bad_price:
            print(f"  • {titulo}  ({slug})  preco={preco}")

    print()
    print(f"Total: {total_issues} problemas em {len(set([r[0] for r in bad_synopsis] + [r[0] for r in bad_cover] + [r[0] for r in bad_price]))} livros distintos")
    print("=" * 60)

    # --- Confirmação ---

    print("""
O que deseja reparar?

1 → Apenas sinopses genéricas
2 → Apenas capas suspeitas/ausentes
3 → Apenas preços zero
4 → Tudo acima
0 → Cancelar (dry-run — nenhuma alteração)
""")

    from core.logger import log as _log
    try:
        op = input("Opção: ").strip()
    except EOFError:
        op = "0"

    if op == "0":
        log("[REPAIR] Cancelado. Nenhuma alteração feita.")
        conn.close()
        return

    # --- Execução ---

    reparar_synopsis = op in ("1", "4") and bad_synopsis
    reparar_cover    = op in ("2", "4") and bad_cover
    reparar_price    = op in ("3", "4") and bad_price

    if reparar_synopsis:
        ids = [r[0] for r in bad_synopsis]
        reset_synopsis(conn, ids)
        log(f"[REPAIR] {len(ids)} sinopses resetadas → re-rodar step 11 (sinopses) + step 13 (quality gate) + step 14 (publicar)")

    if reparar_cover:
        ids = [r[0] for r in bad_cover]
        reset_cover(conn, ids)
        log(f"[REPAIR] {len(ids)} capas resetadas → re-rodar step 12 (capas) + step 13 (quality gate) + step 14 (publicar)")

    if reparar_price:
        ids = [r[0] for r in bad_price]
        reset_offer(conn, ids)
        log(f"[REPAIR] {len(ids)} ofertas resetadas → re-rodar step 17 (publicar ofertas) após corrigir preços")

    conn.close()
    log("[REPAIR] Concluído.")
