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

import os
import random
import re
import time
import requests

from datetime import datetime

from core.db import get_conn
from core.logger import log
from core import interrupt as _interrupt


# =========================
# STATS (reseta a cada run)
# =========================

_run_stats = {"http_503": 0, "mp_ok": 0, "mp_skip": 0}

# Circuit breaker para Open Library: após OL_CIRCUIT_THRESHOLD falhas
# consecutivas, skip Open Library pelo resto do batch para não bloquear
# o scraper inteiro em ConnectTimeout/ReadTimeout repetidos.
_ol_consecutive_failures = 0
OL_CIRCUIT_THRESHOLD = 3   # falhas consecutivas para abrir o circuit

# Circuit breaker para o marketplace — mesma ideia, motivo diferente.
#
# O marketplace é tentado PRIMEIRO (é a única fonte com preço), mas é o mais
# caro quando está sob bot wall: fetch_page faz até RETRY_MAX=3 tentativas com
# backoff de RETRY_DELAY_503 = [5, 20] segundos, ou seja ~25s de sleep mais os
# timeouts de leitura — por livro. Em 17 mil livros isso seria inviável. Após
# MP_CIRCUIT_THRESHOLD falhas consecutivas o marketplace é pulado pelo resto do
# lote e o step degrada exatamente para o comportamento anterior (só APIs).
# Qualquer sucesso fecha o circuit.
_mp_consecutive_failures = 0
MP_CIRCUIT_THRESHOLD = int(os.getenv("MP_CIRCUIT_THRESHOLD", "3"))


# =========================
# CONFIG
# =========================

TIMEOUT_CONNECT   = 5
TIMEOUT_SCRAPING  = 10   # scraping direto HTML (Amazon/ML) — mais propenso a ReadTimeout
TIMEOUT_API       = 20   # chamadas de API (Open Library, Google Books) — mais estáveis
TIMEOUT_READ      = TIMEOUT_SCRAPING  # compatibilidade: fetch_page usa este valor
RETRY_DELAY       = 3
RETRY_MAX         = 3
RETRY_DELAY_503   = [5, 20]   # backoff em segundos após o 1º e 2º 503 consecutivo
MIN_IMG_BYTES = 5000
MAX_DESC_CHARS = 2000

# Pool de User-Agents — rotacionado a cada tentativa para reduzir bloqueios 503
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
]

HEADERS = {
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
    """Faz GET com retry. Retorna BeautifulSoup ou None.

    - Rotaciona User-Agent a cada tentativa (reduz detecção de bot)
    - 503: backoff exponencial + nova tentativa (max RETRY_MAX)
    - 403: falha imediata (Forbidden — sem sentido retentar)
    - Timeout / exceção: retry com RETRY_DELAY + jitter
    """

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        log("[SCRAPER] beautifulsoup4 não instalado. Rode: pip install beautifulsoup4")
        return None

    for attempt in range(RETRY_MAX):
        headers = {**HEADERS, "User-Agent": random.choice(USER_AGENTS)}
        try:
            resp = requests.get(
                url,
                headers=headers,
                timeout=(TIMEOUT_CONNECT, TIMEOUT_READ),
                allow_redirects=True,
            )
            if resp.status_code == 200:
                return BeautifulSoup(resp.text, "html.parser")
            if resp.status_code == 403:
                log(f"[SCRAPER] HTTP 403 → {url[:80]}")
                return None
            if resp.status_code == 503:
                _run_stats["http_503"] += 1
                log(f"[SCRAPER] HTTP 503 (tentativa {attempt + 1}/{RETRY_MAX}) → {url[:80]}")
                if attempt < RETRY_MAX - 1:
                    delay = RETRY_DELAY_503[min(attempt, len(RETRY_DELAY_503) - 1)]
                    log(f"[SCRAPER] Backoff {delay}s antes de nova tentativa")
                    time.sleep(delay)
                continue
        except KeyboardInterrupt:
            raise
        except requests.exceptions.ReadTimeout:
            log(f"[SCRAPER] TIMEOUT (tentativa {attempt + 1}) → {url[:80]}")
        except Exception as e:
            log(f"[SCRAPER] Erro HTTP (tentativa {attempt + 1}): {type(e).__name__}")
        if attempt < RETRY_MAX - 1:
            time.sleep(RETRY_DELAY + random.uniform(0, 2))

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
# OPEN LIBRARY (PRIMARY)
# =========================

OL_SEARCH = "https://openlibrary.org/search.json?q={q}&limit=1&fields=title,cover_i,key,author_name"
OL_WORK   = "https://openlibrary.org{key}.json"
OL_COVER  = "https://covers.openlibrary.org/b/id/{cover_id}-L.jpg"


def try_open_library(titulo, isbn=None, autor=None):
    """
    Busca capa e descrição via Open Library (Internet Archive).
    Grátis, sem autenticação, cobre milhões de livros.

    Usa ISBN quando disponível (mais preciso), senão "título autor".
    NÃO usar lookup_query — contém sufixo 'livro' que confunde a busca.

    Circuit breaker: se _ol_consecutive_failures >= OL_CIRCUIT_THRESHOLD,
    retorna None imediatamente sem fazer requests (Open Library instável).

    Retorna dict com cover_url, descricao ou None se falha.
    """
    global _ol_consecutive_failures

    if not titulo and not isbn:
        return None

    if _ol_consecutive_failures >= OL_CIRCUIT_THRESHOLD:
        return None   # circuit aberto — skip silencioso

    try:
        # Prefere ISBN se disponível (mais preciso), senão título + autor
        if isbn:
            q = isbn
        elif autor:
            q = f"{titulo} {autor}"
        else:
            q = titulo
        resp = requests.get(
            OL_SEARCH.format(q=requests.utils.quote(q)),
            timeout=(TIMEOUT_CONNECT, TIMEOUT_API),
        )
        if resp.status_code != 200:
            _ol_consecutive_failures += 1
            return None

        docs = resp.json().get("docs", [])
        if not docs:
            _ol_consecutive_failures = 0   # resposta válida — reset
            return None

        doc      = docs[0]
        cover_id = doc.get("cover_i")
        work_key = doc.get("key")  # ex: /works/OL123W

        cover_url = OL_COVER.format(cover_id=cover_id) if cover_id else None

        # Descrição via endpoint da obra
        descricao = None
        if work_key:
            try:
                w = requests.get(
                    OL_WORK.format(key=work_key),
                    timeout=(TIMEOUT_CONNECT, TIMEOUT_API),
                )
                if w.status_code == 200:
                    raw = w.json().get("description", "")
                    # description pode ser string ou {"value": "..."}
                    if isinstance(raw, dict):
                        raw = raw.get("value", "")
                    descricao = clean_text(raw) if raw else None
            except Exception:
                pass

        if not cover_url and not descricao:
            return None

        _ol_consecutive_failures = 0   # sucesso — reset circuit
        return {
            "cover_url":  cover_url,
            "descricao":  descricao,
            "preco":      None,   # Open Library não tem preço
            "disponivel": True,
            "source":     "open_library",
        }

    except KeyboardInterrupt:
        raise
    except Exception as e:
        _ol_consecutive_failures += 1  # ConnectTimeout/ReadTimeout abre o circuit breaker
        log(f"[SCRAPER] Open Library falhou: {type(e).__name__}")
        return None


# =========================
# NOTA: PREÇO VIA ML API
# =========================
# A API do MercadoLivre exige OAuth2 desde 2023.
# Para habilitar coleta de preços reais, configure:
#   ML_CLIENT_ID  e  ML_CLIENT_SECRET  no .env
# e implemente o fluxo client_credentials em try_mercadolivre_api().
# Por enquanto, preço fica NULL até o marketplace_scraper
# receber auth ou o monitor de preços (passo 19) ser ativado.


# =========================
# GOOGLE BOOKS FALLBACK
# =========================

def try_google_books(isbn, titulo, autor):
    """Fallback leve — retorna descricao e cover_url via Google Books API."""

    try:
        query = isbn if isbn else f"{titulo} {autor}"
        url   = f"https://www.googleapis.com/books/v1/volumes?q={requests.utils.quote(query)}&maxResults=1"
        resp  = requests.get(url, timeout=(TIMEOUT_CONNECT, TIMEOUT_API))

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
    # Livros sem imagem_url têm prioridade — evita re-scrape desnecessário
    # de livros que já têm capa mas ainda não têm status_enrich=1.
    # Título vazio causa URL de busca inválida — filtrado aqui.
    cur.execute("""
        SELECT id, titulo, autor, isbn, offer_url, imagem_url,
               marketplace, lookup_query
        FROM livros
        WHERE status_enrich = 0
          AND offer_url IS NOT NULL
          AND offer_url != ''
          AND titulo IS NOT NULL
          AND titulo != ''
        ORDER BY
          CASE WHEN imagem_url IS NULL OR imagem_url = '' THEN 0 ELSE 1 END,
          created_at ASC
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

    global _mp_consecutive_failures, _ol_consecutive_failures

    log("Marketplace Scraper iniciado…")

    # Os dois circuits são POR LOTE, como diz o comentário deles ("pelo resto
    # do batch"). Resetar aqui importa porque o autopilot chama run() várias
    # vezes no MESMO processo: sem isto o circuit da Open Library, uma vez
    # aberto, nunca mais fechava — o guard retorna antes de qualquer request,
    # então o contador jamais era zerado e a fonte ficava desligada para o
    # resto da sessão.
    _mp_consecutive_failures = 0
    _ol_consecutive_failures = 0

    conn  = get_conn()
    rows  = fetch_pending(conn, pacote)
    total = len(rows)

    if not rows:
        log("Nenhum livro pendente de enriquecimento (offer_url resolvida + status_enrich=0).")
        conn.close()
        return

    ok = falhas = pulados = 0
    _run_stats["http_503"] = 0
    _run_stats["mp_ok"]    = 0
    _run_stats["mp_skip"]  = 0

    try:
        for i, row in enumerate(rows, start=1):

            if _interrupt.requested():
                log("[SCRAPER] Interrupção solicitada — encerrando após o último livro salvo.")
                break

            livro_id      = row["id"]
            titulo        = row["titulo"]
            offer_url     = row["offer_url"]
            isbn          = row["isbn"]
            autor         = row["autor"]
            lookup_query  = row["lookup_query"] or titulo
            marketplace   = row["marketplace"] or ""

            print(f"[SCRAPER][{i:03d}/{total:03d}] → {titulo}")

            result = None
            source = "scraping"
            preco_raspado = None

            # Tentativa 1: marketplace. É a ÚNICA fonte com preço — Open Library
            # e Google Books retornam preco=None por construção — e também a de
            # melhor qualidade de descrição: medido em 2026-07-25, scraping teve
            # 0% de synopsis-title-mismatch em 111 livros contra 24,8% do Google
            # Books em 5.721. Até 2026-07-26 ela era a ÚLTIMA tentativa, atrás
            # das duas APIs, e como para livro real as APIs quase nunca falham
            # as duas juntas, o marketplace praticamente não era alcançado:
            # 140 de 17.861 livros (0,8%) com status_enrich=1. Resultado — preço
            # nunca coletado no enriquecimento.
            #
            # O circuit breaker é o que torna essa ordem viável sob bot wall:
            # sem ele, cada livro bloqueado custaria ~25s só de backoff de 503.
            if _mp_consecutive_failures < MP_CIRCUIT_THRESHOLD:
                scraped = scrape_marketplace(offer_url)
                if scraped:
                    _mp_consecutive_failures = 0     # sucesso — fecha o circuit
                    _run_stats["mp_ok"] += 1
                    preco_raspado = scraped.get("preco")
                    if scraped.get("cover_url") or scraped.get("descricao"):
                        result = scraped
                        source = "scraping"
                else:
                    _mp_consecutive_failures += 1
                    if _mp_consecutive_failures == MP_CIRCUIT_THRESHOLD:
                        log(f"[SCRAPER] Circuit do marketplace ABERTO após "
                            f"{MP_CIRCUIT_THRESHOLD} falhas seguidas — "
                            f"seguindo só com as APIs no resto do lote.")
            else:
                _run_stats["mp_skip"] += 1

            # Tentativa 2: Open Library (capa em alta-res + descrição, sem preço)
            # Usa titulo+autor, NÃO lookup_query (tem sufixo "livro" para Amazon)
            if not result:
                ol = try_open_library(titulo, isbn, autor)
                if ol and (ol.get("cover_url") or ol.get("descricao")):
                    result = ol
                    source = "open_library"

            # Tentativa 3: Google Books (descrição + capa, sem preço)
            if not result:
                gb = try_google_books(isbn, titulo, autor)
                if gb and (gb.get("cover_url") or gb.get("descricao")):
                    result = gb
                    source = "google_books"

            # O preço raspado sobrevive ao fallback. Sem isto, um produto que
            # devolve preço mas não devolve capa nem descrição (ou cuja capa
            # veio melhor da API) teria o preço descartado — que é exatamente
            # o dado que só o marketplace tem.
            if preco_raspado is not None:
                if result is None:
                    result = {"cover_url": None, "descricao": None}
                    source = "scraping"
                if result.get("preco") is None:
                    result["preco"] = preco_raspado

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

            # Rate limiting respeitoso — jitter evita padrão fixo detectável
            time.sleep(0.5 + random.uniform(0, 1.0))

    except KeyboardInterrupt:
        log(f"[SCRAPER] Interrompido pelo usuário — progresso salvo até aqui.")

    conn.close()

    log(
        f"[SCRAPER] OK: {ok} | "
        f"Falhas: {falhas} | "
        f"Pulados (sem dados): {pulados} | "
        f"HTTP 503 (bloqueio Amazon): {_run_stats['http_503']} | "
        f"Total: {total}"
    )
    # Sem esta linha não dá para saber se o marketplace está entregando preço
    # ou se o circuit abriu logo no começo e o lote inteiro veio só das APIs.
    log(
        f"[SCRAPER] Marketplace — respostas: {_run_stats['mp_ok']} | "
        f"pulados por circuit aberto: {_run_stats['mp_skip']} | "
        f"circuit ao fim: {'ABERTO' if _mp_consecutive_failures >= MP_CIRCUIT_THRESHOLD else 'fechado'}"
    )
