# ============================================================
# STEP 17 — MARKETPLACE SCRAPER
# Livraria Alexandria
#
# Extrai capa, descrição e preço direto do marketplace para
# livros com offer_url resolvida. Substitui enrich_descricao
# e covers como step primário de enriquecimento.
#
# Fallback chain: scraping → Google Books → OpenLibrary
#
# Progresso: [SCRAPER][NNN/TTT] → titulo
# ============================================================

import re
import time
import requests

from datetime import datetime

from core.db import get_conn
from core.logger import log


# =========================
# CONFIG
# =========================

TIMEOUT       = 15
RETRY_DELAY   = 3
RETRY_MAX     = 2
MIN_IMG_BYTES = 5000
MAX_DESC_CHARS = 2000

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Seletores por marketplace
SELECTORS = {
    "amazon": {
        "cover":   ["#imgTagWrapperId img", "#landingImage", "#ebooksImgBlkFront"],
        "desc":    ["#bookDescription_feature_div", "#productDescription", "#feature-bullets ul"],
        "price":   [".a-price .a-offscreen", "#price", ".a-color-price", ".kindle-price"],
        "unavail": ["Este item não está disponível", "Indisponível", "Currently unavailable",
                    "Não disponível", "temporariamente indisponível"],
    },
    "mercadolivre": {
        "cover":   [".ui-pdp-image", ".ui-pdp-gallery__figure img"],
        "desc":    [".ui-pdp-description__content", ".ui-pdp-description p"],
        "price":   [".andes-money-amount__fraction", ".price-tag-fraction"],
        "unavail": ["Sem estoque", "Produto indisponível", "sem estoque"],
    },
}


# =========================
# DETECT MARKETPLACE
# =========================

def detect_marketplace(url):
    if not url:
        return None
    if "amazon.com.br" in url or "amzn" in url:
        return "amazon"
    if "mercadolivre.com.br" in url or "mercadolibre" in url:
        return "mercadolivre"
    return None


# =========================
# HTTP FETCH
# =========================

def fetch_page(url):
    """Faz GET com retry. Retorna BeautifulSoup ou None."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        log("[SCRAPER] beautifulsoup4 não instalado. Rode: pip install beautifulsoup4")
        return None

    for attempt in range(RETRY_MAX):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            if resp.status_code == 200:
                return BeautifulSoup(resp.text, "html.parser")
            log(f"[SCRAPER] HTTP {resp.status_code} → {url[:80]}")
        except Exception as e:
            log(f"[SCRAPER] Erro HTTP (tentativa {attempt + 1}): {e}")
        if attempt < RETRY_MAX - 1:
            time.sleep(RETRY_DELAY)

    return None


# =========================
# EXTRACT FROM SOUP
# =========================

def extract_text_from_selectors(soup, selectors):
    """Tenta cada seletor em ordem, retorna o primeiro texto encontrado."""
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            text = el.get_text(separator=" ", strip=True)
            if text:
                return text
    return None


def extract_image_url(soup, selectors):
    """Tenta cada seletor, retorna URL da imagem."""
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            src = el.get("src") or el.get("data-src") or el.get("data-a-dynamic-image")
            if src and src.startswith("http"):
                return src
            # Amazon data-a-dynamic-image é um JSON de URLs
            if src and src.startswith("{"):
                import json
                try:
                    urls = json.loads(src)
                    if urls:
                        return list(urls.keys())[0]
                except Exception:
                    pass
    return None


def clean_text(text, max_chars=MAX_DESC_CHARS):
    """Remove HTML residual e normaliza espaços."""
    if not text:
        return None
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars] if len(text) > max_chars else text


def parse_price(text):
    """Extrai valor numérico de string de preço."""
    if not text:
        return None
    cleaned = re.sub(r"[^\d,\.]", "", text.strip())
    cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except Exception:
        return None


def is_unavailable(soup, signals):
    page_text = soup.get_text(separator=" ").lower()
    for signal in signals:
        if signal.lower() in page_text:
            return True
    return False


# =========================
# SCRAPE ONE BOOK
# =========================

def scrape_marketplace(offer_url):
    """
    Retorna dict com cover_url, descricao, preco, disponivel
    ou None se falha total.
    """
    marketplace = detect_marketplace(offer_url)
    if not marketplace:
        return None

    sels = SELECTORS.get(marketplace, {})

    soup = fetch_page(offer_url)
    if soup is None:
        return None

    result = {
        "cover_url":  extract_image_url(soup, sels.get("cover", [])),
        "descricao":  clean_text(extract_text_from_selectors(soup, sels.get("desc", []))),
        "preco":      parse_price(extract_text_from_selectors(soup, sels.get("price", []))),
        "disponivel": not is_unavailable(soup, sels.get("unavail", [])),
        "marketplace": marketplace,
    }

    return result


# =========================
# GOOGLE BOOKS FALLBACK
# =========================

def try_google_books(isbn, titulo, autor):
    """Fallback leve — retorna descricao e cover_url via Google Books API."""

    try:
        query = isbn if isbn else f"{titulo} {autor}"
        url   = f"https://www.googleapis.com/books/v1/volumes?q={requests.utils.quote(query)}&maxResults=1"
        resp  = requests.get(url, timeout=10)

        if resp.status_code != 200:
            return None

        data  = resp.json()
        items = data.get("items", [])
        if not items:
            return None

        info = items[0].get("volumeInfo", {})
        img  = info.get("imageLinks", {})

        return {
            "cover_url": img.get("thumbnail") or img.get("smallThumbnail"),
            "descricao": clean_text(info.get("description")),
            "preco":     None,
            "disponivel": True,
            "source":    "google_books",
        }
    except Exception as e:
        log(f"[SCRAPER] Google Books fallback falhou: {e}")
        return None


# =========================
# FETCH PENDING
# =========================

def fetch_pending(conn, pacote):
    cur = conn.cursor()
    cur.execute("""
        SELECT id, titulo, autor, isbn, offer_url, imagem_url
        FROM livros
        WHERE status_enrich = 0
          AND offer_url IS NOT NULL
          AND offer_url != ''
        ORDER BY created_at ASC
        LIMIT ?
    """, (pacote,))
    return cur.fetchall()


# =========================
# SAVE RESULT
# =========================

def save_result(conn, livro_id, result, source="scraping"):

    cover_url  = result.get("cover_url")
    descricao  = result.get("descricao")
    preco      = result.get("preco")
    status_cov = 1 if cover_url else 2

    conn.execute("""
        UPDATE livros
        SET imagem_url    = COALESCE(?, imagem_url),
            descricao     = COALESCE(?, descricao),
            preco_atual   = COALESCE(?, preco_atual),
            status_enrich = ?,
            status_cover  = ?,
            updated_at    = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (
        cover_url,
        descricao,
        preco,
        1 if source == "scraping" else 2,
        status_cov,
        livro_id,
    ))

    conn.commit()


# =========================
# RUN
# =========================

def run(idioma=None, pacote=50):

    log("Marketplace Scraper iniciado…")

    conn  = get_conn()
    rows  = fetch_pending(conn, pacote)
    total = len(rows)

    if not rows:
        log("Nenhum livro pendente de enriquecimento (offer_url resolvida + status_enrich=0).")
        conn.close()
        return

    ok = falhas = pulados = 0

    for i, row in enumerate(rows, start=1):

        livro_id  = row["id"]
        titulo    = row["titulo"]
        offer_url = row["offer_url"]
        isbn      = row["isbn"]
        autor     = row["autor"]

        print(f"[SCRAPER][{i:03d}/{total:03d}] → {titulo}")

        # Tentativa 1: scraping direto do marketplace
        result = scrape_marketplace(offer_url)

        source = "scraping"

        if not result or not (result.get("cover_url") or result.get("descricao")):
            # Tentativa 2: Google Books
            result = try_google_books(isbn, titulo, autor)
            source = "google_books"

        if not result:
            log(f"[SCRAPER] Sem dados para: {titulo}")
            pulados += 1

            # Marca como tentado (status_enrich=2) para não reprocessar indefinidamente
            conn.execute("""
                UPDATE livros SET status_enrich = 2, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (livro_id,))
            conn.commit()
            continue

        save_result(conn, livro_id, result, source)

        if result.get("cover_url") or result.get("descricao"):
            ok += 1
        else:
            falhas += 1

        # Rate limiting respeitoso
        time.sleep(1)

    conn.close()

    log(
        f"[SCRAPER] OK: {ok} | "
        f"Falhas: {falhas} | "
        f"Pulados: {pulados} | "
        f"Total: {total}"
    )
