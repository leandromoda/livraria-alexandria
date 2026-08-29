# ============================================================
# STEP 3 — OFFER RESOLVER
# Livraria Alexandria
#
# Gera URLs de afiliado a partir de lookup_query + marketplace
# ============================================================

import os
import sqlite3
import time
from pathlib import Path
from urllib.parse import quote, quote_plus, urlparse, urlencode, parse_qs, urlunparse


# =========================
# CONFIG
# =========================

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "books.db")


# =========================
# LOG
# =========================

def log(msg):
    now = time.strftime("%H:%M:%S")
    print(f"[{now}] {msg}")


# =========================
# DB CONNECTION
# =========================

def get_conn():

    conn = sqlite3.connect(DB_PATH, timeout=30)

    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    return conn


# =========================
# AFILIADO ML
# =========================

ML_AFFILIATE = {
    "matt_word": "leandro_moda",
    "matt_tool": "45905535",
}


def inject_ml_affiliate(url: str) -> str:
    """Injeta parâmetros de afiliado ML na URL. Idempotente. Só atua em mercadolivre.com."""
    parsed = urlparse(url)
    if "mercadolivre.com" not in parsed.netloc:
        return url
    params = parse_qs(parsed.query, keep_blank_values=True)
    if "matt_tool" in params:
        return url  # já tem — não duplicar
    params.update({k: [v] for k, v in ML_AFFILIATE.items()})
    new_query = urlencode({k: v[0] for k, v in params.items()})
    return urlunparse(parsed._replace(query=new_query))


# =========================
# AFILIADO AMAZON
# =========================

AMAZON_TAG = os.environ.get("AMAZON_ASSOCIATE_TAG", "livrariaalexa-20")


def inject_amazon_tag(url: str) -> str:
    """Injeta tag de associado Amazon na URL. Idempotente. Só atua em amazon.com.br."""
    parsed = urlparse(url)
    if "amazon.com.br" not in parsed.netloc:
        return url
    params = parse_qs(parsed.query, keep_blank_values=True)
    if "tag" in params:
        return url  # já tem — não duplicar
    params["tag"] = [AMAZON_TAG]
    new_query = urlencode({k: v[0] for k, v in params.items()})
    return urlunparse(parsed._replace(query=new_query))


# =========================
# URL BUILDERS
# =========================

def build_amazon_url(query: str) -> str:
    q = quote_plus(query)
    url = f"https://www.amazon.com.br/s?k={q}"
    return inject_amazon_tag(url)


def build_mercadolivre_url(query: str) -> str:
    # Usar hífens em vez de "+" no path para evitar redirect 301 do ML
    # que descarta os query params de afiliado (matt_tool/matt_word).
    # ML normaliza espaços→hífens canonicamente; usar o formato final
    # diretamente faz a página retornar 200 com os params intactos.
    slug = quote(query.lower().replace(" ", "-"), safe="-")
    url = f"https://lista.mercadolivre.com.br/{slug}"
    return inject_ml_affiliate(url)


# O marketplace do seed é palpite de quem escreveu o JSON, e a distribuição
# mostra isso: 8.798 'amazon' contra 8.778 'mercado_livre' — quase moeda ao ar.
# Só que os dois lados NÃO são equivalentes (medido em 2026-08-29):
#
#   ML ....... API oficial de catálogo. Preço, disponibilidade e deep link de
#              produto. ~1-2 s por livro, 37% de casamento confirmado.
#   Amazon ... sem API acessível (PA-API desligada em 15/05/2026; a Creators
#              API exige 10 vendas/30 dias). Só scraping, sob bot wall:
#              ~13,7 s por livro e ~0% de preço.
#
# Um livro roteado para a Amazon hoje é beco sem saída: fica com URL de busca,
# sem preço, que é exatamente o perfil de "thin affiliate" que o spam update
# penaliza. Por isso o roteamento deixou de obedecer o seed.
#
# `FORCAR_ML=0` volta a obedecer o campo `marketplace` do seed.
FORCAR_ML = os.getenv("FORCAR_ML", "1").strip() not in ("0", "false", "no")


def resolve_offer(marketplace: str, lookup_query: str,
                  titulo: str = None, autor: str = None, isbn: str = None):
    """(offer_url, preco, marketplace_final) — ou (None, None, None).

    Três degraus, do melhor para o pior:

    1. **API do ML confirma o livro** → deep link da PÁGINA DO PRODUTO, com
       preço já na mão. O livro nasce com oferta de verdade, sem precisar
       esperar o monitor de preços passar por ele.
    2. **API não confirma** → URL de BUSCA do ML. O monitor tenta de novo
       depois; "não casou agora" não é o mesmo que "não existe no ML".
    3. **`FORCAR_ML=0`** → obedece o seed, comportamento antigo.
    """
    if not lookup_query:
        return None, None, None

    if FORCAR_ML:
        if titulo:
            try:
                from core import ml_api
                if ml_api.configurado():
                    achado = ml_api.buscar_livro(titulo, autor, isbn)
                    if achado:
                        return (inject_ml_affiliate(achado["url"]),
                                achado["preco"], "mercado_livre")
            except Exception as e:
                log(f"[RESOLVER] API do ML indisponível ({type(e).__name__}) "
                    f"— caindo na URL de busca")
        return build_mercadolivre_url(lookup_query), None, "mercado_livre"

    if marketplace and marketplace.strip().lower() == "amazon":
        return build_amazon_url(lookup_query), None, "amazon"

    if marketplace and marketplace.strip().lower() in ("mercado_livre", "mercadolivre"):
        return build_mercadolivre_url(lookup_query), None, "mercado_livre"

    return None, None, None


# =========================
# FETCH PENDING
# =========================

def fetch_pending(conn, idioma, limit):

    cur = conn.cursor()

    if idioma is None:
        cur.execute("""
            SELECT id, titulo, autor, marketplace, lookup_query
            FROM livros
            WHERE lookup_query IS NOT NULL
              AND offer_url IS NULL
              AND (offer_status IS NULL OR offer_status = 0 OR offer_status = 'active')
            LIMIT ?
        """, (limit,))
    else:
        cur.execute("""
            SELECT id, titulo, autor, marketplace, lookup_query
            FROM livros
            WHERE idioma = ?
              AND lookup_query IS NOT NULL
              AND offer_url IS NULL
              AND (offer_status IS NULL OR offer_status = 0 OR offer_status = 'active')
            LIMIT ?
        """, (idioma, limit))

    return cur.fetchall()


# =========================
# UPDATE
# =========================

def update_offer(conn, book_id, offer_url, success, preco=None, marketplace=None):
    """Grava a oferta resolvida.

    `marketplace` é gravado junto porque o roteamento deixou de obedecer o seed
    (ver `resolve_offer`): sem isso o banco diria 'amazon' com uma URL do ML, e
    o `publish_ofertas` publicaria essa contradição no Supabase.

    `preco` só aparece quando a API do ML confirmou o produto — nesse caso o
    livro já nasce com preço, sem esperar o monitor passar por ele.
    """
    cur = conn.cursor()

    cur.execute("""
        UPDATE livros
        SET offer_url    = ?,
            offer_status = ?,
            marketplace  = COALESCE(?, marketplace),
            preco_atual  = COALESCE(?, preco_atual),
            preco_updated_at = CASE WHEN ? IS NOT NULL
                                    THEN CURRENT_TIMESTAMP ELSE preco_updated_at END,
            updated_at   = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (offer_url, 1 if success else -1, marketplace, preco, preco, book_id))

    conn.commit()


# =========================
# BACKFILL — livros publicados sem oferta
# =========================

def backfill_missing_offers(conn):
    """Gera lookup_query e marketplace para livros publicados que não têm nenhum dado de oferta."""
    cur = conn.cursor()
    cur.execute("""
        SELECT id, titulo, autor
        FROM livros
        WHERE status_publish = 1
          AND offer_url IS NULL
          AND (marketplace IS NULL OR lookup_query IS NULL)
    """)
    rows = cur.fetchall()

    if not rows:
        return 0

    count = 0
    for book_id, titulo, autor in rows:
        query = f"{titulo} {autor} livro" if autor else f"{titulo} livro"
        cur.execute("""
            UPDATE livros
            SET lookup_query = ?,
                marketplace  = 'amazon',
                offer_status = 0,
                updated_at   = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (query, book_id))
        count += 1

    conn.commit()
    log(f"[BACKFILL] {count} livros publicados receberam lookup_query + marketplace")
    return count


# =========================
# RUN
# =========================

def run(idioma, pacote):

    log("Iniciando Offer Resolver...")

    conn = get_conn()

    backfill_missing_offers(conn)

    rows = fetch_pending(conn, idioma, pacote)

    total      = len(rows)
    resolved   = 0
    failed     = 0
    com_preco  = 0

    log(f"{total} seeds pendentes")

    for row in rows:

        book_id, titulo, autor, marketplace, lookup_query = row

        try:
            offer_url, preco, mkt = resolve_offer(
                marketplace, lookup_query, titulo=titulo, autor=autor)

            if offer_url:
                update_offer(conn, book_id, offer_url, True,
                             preco=preco, marketplace=mkt)
                resolved += 1
                if preco:
                    com_preco += 1
            else:
                update_offer(conn, book_id, None, False)
                failed += 1

        except Exception as e:
            log(f"Erro → '{titulo}': {e}")
            update_offer(conn, book_id, None, False)
            failed += 1

    conn.close()

    log(f"Resolvidas: {resolved} | Falhas: {failed} | ja com preco pela API do ML: {com_preco}")
    log("Offer Resolver finalizado.")
