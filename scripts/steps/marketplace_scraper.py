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
import unicodedata
import requests

from datetime import datetime

from core.db import get_conn
from core.isbn import normalize_isbn13
from core.logger import log
from core import interrupt as _interrupt


# =========================
# STATS (reseta a cada run)
# =========================

_run_stats = {"http_503": 0, "mp_ok": 0, "mp_skip": 0}

# ---------------------------------------------------------------------------
# Telemetria do `_resolve_produto` — por QUE um livro não resolveu
#
# ⚠ Motivo de existir, medido em 2026-08-29. Em duas passadas do mesmo dia o
# monitor de preços rendeu 41% (62/150, log 07-54-02) e depois 20% (30/150, log
# 10-28-52) — e o log não permitia dizer o porquê, porque a única saída era
# `Ativos: N | Erros: N`. Foi preciso cruzar o relatório `NNNN_audit_prices.json`
# com o `books.db` para descobrir o fato que importava: os **120 erros eram
# 120 URLs do Mercado Livre**, nenhuma da Amazon.
#
# Sem isto, "a API do ML rendeu menos" e "o scraping do ML apanhou do bot wall"
# são indistinguíveis no log — e são correções opostas. Os contadores são
# AGREGADOS de propósito: log por item foi justamente o que inchou os logs de
# julho (ver "A espera produtiva suspende o dreno" no topo deste arquivo).
# ---------------------------------------------------------------------------

_resolve_stats = {
    "ml_api_ok":     0,   # API do ML confirmou o produto (portão de 2 folhas)
    "ml_api_miss":   0,   # API consultada, não confirmou — cai no scraping
    "ml_api_off":    0,   # sem credencial / módulo ausente — nem tentou
    "ml_api_erro":   0,   # exceção na chamada da API
    "scrape_sem_pagina": 0,  # fetch_page devolveu None (bot wall, timeout)
    "scrape_sem_card":   0,  # página veio, nenhum card casou título+autor
    "scrape_ok":     0,   # scraping resolveu o produto
}


def reset_resolve_stats():
    for k in _resolve_stats:
        _resolve_stats[k] = 0


def resolve_stats_line():
    """Uma linha agregada, só com o que aconteceu (zeros são ruído)."""
    partes = [f"{k}={v}" for k, v in _resolve_stats.items() if v]
    return " | ".join(partes) if partes else "sem tentativas"

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


# Onde a disponibilidade REALMENTE é declarada, por marketplace. Buscar fora
# dessas regiões é o que causou o bug de 2026-08-29 (ver `is_unavailable`).
AVAIL_SELECTORS = {
    "amazon": ["#availability", "#outOfStock", "#availability_feature_div"],
    "mercadolivre": [".ui-pdp-stock-information", ".ui-pdp-buybox__quantity"],
}


def is_unavailable(soup, signals, preco=None, marketplace=None):
    """True só quando a página DECLARA indisponibilidade. Na dúvida: False.

    ⚠ BUG CORRIGIDO EM 2026-08-29 — esta função varria o texto INTEIRO da
    página atrás das palavras de `signals`, e despublicou 6 livros que estavam
    à venda. Medido nas próprias páginas, no mesmo dia:

        A Quinta Estação    R$  69,10
        Cidade dos Ossos    R$ 300,90
        Encontro com Rama   R$  54,85

    O que casava era boilerplate presente em TODA página de produto da Amazon:
    `${cardName} indisponível para o vendedor escolhido` (template de
    JavaScript), `Imagem não disponível` (alt de placeholder) e `Listar
    indisponível` (string de erro de UI). Nenhum deles fala do produto.

    O bug era latente e o PR #296 o tornou alcançável: até ali o monitor lia a
    página de BUSCA, que não traz esses textos; ao passar a ler a página de
    PRODUTO — que era a correção certa — a varredura começou a casar sempre.

    Duas travas agora:

    1. **Preço manda.** Página com preço de compra é página de produto à venda.
       Isso sozinho derruba os três falsos positivos acima.
    2. **Só a região de disponibilidade conta.** Sem essa região no HTML, o
       retorno é False — "não consegui confirmar" não pode virar "indisponível"
       quando a consequência é despublicar.
    """
    if preco is not None and preco > 0:
        return False

    regioes = AVAIL_SELECTORS.get(marketplace or "", [])
    trechos = []
    for sel in regioes:
        for el in soup.select(sel):
            trechos.append(el.get_text(separator=" ", strip=True))
    if not trechos:
        return False

    texto = " ".join(trechos).lower()
    return any(s.lower() in texto for s in signals)


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

    preco = parse_price(extract_text_from_selectors(soup, sels.get("price", [])))
    result = {
        "cover_url":  extract_image_url(soup, sels.get("cover", [])),
        "descricao":  clean_text(extract_text_from_selectors(soup, sels.get("desc", []))),
        "preco":      preco,
        # `preco` e `marketplace` entram para a checagem não depender de varrer
        # o texto inteiro — ver a nota de bug em `is_unavailable`.
        "disponivel": not is_unavailable(soup, sels.get("unavail", []),
                                         preco=preco, marketplace=marketplace),
        "marketplace": marketplace,
    }

    return result


# =========================
# BUSCA -> PRODUTO (2 SALTOS)
# =========================

# Estes helpers nasceram em `steps/jogos_pipeline.py` (2026-07-14) e foram
# promovidos para cá em 2026-08-23 porque o problema é o mesmo nos dois
# pipelines: o `offer_url` que o resolver produz é uma URL de BUSCA, e os
# SELECTORS acima são de PÁGINA DE PRODUTO. Raspar a busca com eles devolve o
# preço do primeiro card — de qualquer item que esteja lá.
#
# Medido em 2026-08-23 no books.db: 4.849 dos 4.856 livros publicados (99,9%)
# têm offer_url de busca. Numa amostra de 3 buscas reais na Amazon, a de "O Guia
# do Mochileiro das Galáxias" devolveu 4 preços — R$ 45,83 / 76,97 / 33,45 /
# 19,00 — sendo dois de OUTROS livros da série. Ver TASK-OFERTAS-004.
#
# A direção da dependência não inverte: `jogos_pipeline` já importava deste
# módulo, e o que migrou é lógica genérica de marketplace, não domínio de jogos.

_AMAZON_ASIN_RE = re.compile(r"/dp/([A-Z0-9]{10})")
_ML_LINK_RE     = re.compile(
    r"https?://(?:produto\.mercadolivre\.com\.br/MLB-?\d+[^\s\"'#?]*"
    r"|www\.mercadolivre\.com\.br/[^\s\"'#?]*?/p/MLB\d+)"
)

# Tokens que não identificam o produto (edição/formato/tipo). Cobre os dois
# domínios: "rpg/caixa/box" vêm de jogos, "livro/livros" de livros — as buscas
# de livro literalmente terminam em "livro" (ver offer_resolver).
_TITULO_STOPWORDS = {
    "rpg", "livro", "livros", "basico", "básico", "caixa", "box",
    "edicao", "edição", "jogo", "jogos", "de", "do", "da", "dos", "das",
    "e", "o", "a", "em", "para", "ed", "vol", "volume", "2a", "1a", "3a",
    "ii", "iii",
}


def _tokens_titulo(texto):
    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode("ascii")
    t = re.sub(r"[^a-z0-9\s]", " ", t.lower())
    return [w for w in t.split() if w and w not in _TITULO_STOPWORDS]


def _autor_compativel(autor, texto):
    """True se o SOBRENOME do autor aparece em `texto`.

    Sobrenome, não o nome inteiro: a Amazon abrevia ("Douglas Adams" vira
    "Adams, Douglas" ou só "Adams") e o ML costuma omitir o autor. Sem `autor`
    ou sem `texto` a checagem não se aplica e devolve True — quem decide se
    isso basta é `_titulo_score`, via `estrito`.
    """
    if not autor or not texto:
        return True
    tokens_autor = [t for t in _tokens_titulo(autor) if len(t) > 2]
    if not tokens_autor:
        return True
    return tokens_autor[-1] in set(_tokens_titulo(texto))


def _titulo_score(titulo, titulo_resultado, autor=None, texto_card=None, estrito=False):
    """Pontua o quanto o card da busca corresponde ao item procurado.
    Devolve `(cobertura, similaridade)` — comparável entre cards — ou None
    quando o card é REJEITADO.

    A pontuação de desempate é medida sobre os dois lados ORDENADOS, e o portão
    de aceitação não: o portão precisa continuar idêntico ao de jogos desde
    2026-07-14, e ordenar os dois lados o afrouxaria. São usos diferentes do
    mesmo par de títulos — aceitar é uma decisão, ranquear é outra.

    Dois regimes, porque os dois domínios erram de formas diferentes:

    - `estrito=False` (jogos, comportamento desde 2026-07-14): aceita com >=60%
      dos tokens significativos presentes, ou similaridade global >=0.6. Falso
      negativo é aceitável — o item cai no agente finder.

    - `estrito=True` (livros): exige TODOS os tokens significativos do título
      buscado presentes no card (ou similaridade >=0.85) e, quando o autor é
      conhecido, o sobrenome dele no texto do card. Motivo medido em 2026-08-23:
      com o limiar de 0,6 só sobre o título, "Praticamente Inofensiva - Volume
      5. Série O Mochileiro das Galáxias" casa com "O Guia do Mochileiro das
      Galáxias" (2 de 3 tokens = 0,67). Livro tem série; jogo não tem, e por
      isso o regime frouxo nunca doeu em jogos.
    """
    from difflib import SequenceMatcher

    tj = _tokens_titulo(titulo)
    if not tj:
        return None
    tr = set(_tokens_titulo(titulo_resultado))
    cobertura = (sum(1 for w in tj if w in tr) / len(tj)) if tr else 0.0
    ratio = SequenceMatcher(None, " ".join(tj), " ".join(sorted(tr))).ratio()

    if estrito:
        if cobertura < 1.0 and ratio < 0.85:
            return None
        if not _autor_compativel(autor, f"{titulo_resultado} {texto_card or ''}"):
            return None
    else:
        if cobertura < 0.6 and ratio < 0.6:
            return None

    ranking = SequenceMatcher(None, " ".join(sorted(set(tj))),
                              " ".join(sorted(tr))).ratio()
    return (cobertura, ranking)


def _titulo_compativel(titulo, titulo_resultado, autor=None, texto_card=None, estrito=False):
    """Wrapper booleano de `_titulo_score`, mantido para leitura nos testes."""
    return _titulo_score(titulo, titulo_resultado, autor, texto_card, estrito) is not None


def _find_product_url(soup, marketplace, titulo, autor=None, estrito=False):
    """Extrai da página de BUSCA a URL do resultado que MELHOR casa com o item.
    Retorna URL canônica sem tag de afiliado, ou None.

    ⚠ Mudança de 2026-08-23: escolhe o card de MAIOR pontuação, não o primeiro
    compatível. O portão de aceitação é o mesmo de antes em jogos — só a escolha
    entre os aprovados melhorou. Medido na busca de "O Guia do Mochileiro das
    Galáxias": "O guia do mochileiro das galáxias" (1,00) e "O guia definitivo
    do mochileiro das galáxias" (~0,86) passam os dois no regime estrito, e o
    primeiro card da página nem sempre é o de maior pontuação.
    """
    if soup is None:
        return None

    melhor_url, melhor_score = None, None

    if marketplace == "amazon":
        # Cards de resultado (páginas reais têm; páginas de captcha, não)
        for card in soup.select('div[data-component-type="s-search-result"]'):
            h2 = card.select_one("h2")
            card_titulo = h2.get_text(" ", strip=True) if h2 else ""
            score = _titulo_score(titulo, card_titulo, autor,
                                  card.get_text(" ", strip=True), estrito)
            if score is None or (melhor_score is not None and score <= melhor_score):
                continue
            for a in card.select('a[href*="/dp/"]'):
                href = a.get("href") or ""
                if "/sspa/" in href or "sspa=" in href:   # patrocinado
                    continue
                m = _AMAZON_ASIN_RE.search(href)
                if m:
                    melhor_url, melhor_score = f"https://www.amazon.com.br/dp/{m.group(1)}", score
                    break
        return melhor_url

    if marketplace == "mercadolivre":
        # Layouts novo (poly-card) e antigo (ui-search)
        for card in soup.select("div.poly-card, li.ui-search-layout__item"):
            t = card.select_one(
                ".poly-component__title, .ui-search-item__title, h3, h2"
            )
            card_titulo = t.get_text(" ", strip=True) if t else ""
            score = _titulo_score(titulo, card_titulo, autor,
                                  card.get_text(" ", strip=True), estrito)
            if score is None or (melhor_score is not None and score <= melhor_score):
                continue
            for a in card.select("a[href]"):
                href = (a.get("href") or "").split("#", 1)[0]
                if "click1.mercadolivre" in href or "mclics" in href:  # anúncio
                    continue
                m = _ML_LINK_RE.match(href)
                if m:
                    melhor_url, melhor_score = m.group(0), score
                    break
        return melhor_url

    return None


def _resolve_produto_ml_api(titulo, autor=None, isbn=None):
    """Tenta a API de catálogo do ML. Retorna (result, url_afiliada) ou None.

    O formato de retorno imita o do `scrape_marketplace` para o chamador não
    precisar saber de onde veio o dado. `cover_url` e `descricao` ficam None de
    propósito: a API de catálogo não é fonte de descrição, e o pipeline já tem
    Open Library / Google Books para isso.
    """
    try:
        from core import ml_api
    except Exception:
        _resolve_stats["ml_api_off"] += 1
        return None
    if not ml_api.configurado():
        _resolve_stats["ml_api_off"] += 1
        return None
    try:
        achado = ml_api.buscar_livro(titulo, autor, isbn)
    except Exception as e:
        _resolve_stats["ml_api_erro"] += 1
        log(f"[SCRAPER] API do ML falhou ({type(e).__name__}) — caindo no scraping")
        return None
    if not achado:
        # A /products/search NUNCA responde "não achei" — ela devolve o mais
        # parecido, e o portão de duas folhas (autor E título) reprovou. Isto é
        # o comportamento CERTO; contar aqui é o que separa "a API rejeitou"
        # de "a API está fora".
        _resolve_stats["ml_api_miss"] += 1
        return None

    from steps.offer_resolver import inject_ml_affiliate
    _run_stats["ml_api_ok"] = _run_stats.get("ml_api_ok", 0) + 1
    _resolve_stats["ml_api_ok"] += 1
    result = {
        "cover_url": None,
        "descricao": None,
        "preco": achado["preco"],
        "disponivel": True,
        "marketplace": "mercadolivre",
        "fonte": "ml_api",
    }
    return result, inject_ml_affiliate(achado["url"])


def _resolve_produto(search_url, titulo, autor=None, estrito=False, isbn=None):
    """Busca -> página do produto compatível com o título.
    Retorna (result_dict|None, product_url_afiliada|None). SEM fallback de
    raspar a página de busca: dado de produto errado é pior que dado nenhum
    (o item sem descrição segue para o agente finder).

    Desde 2026-08-29, no Mercado Livre a API oficial de catálogo é tentada
    ANTES do scraping (TASK-OFERTAS-005). Motivo medido: num passe real do G o
    scraping entregou 4 de 50 livros, com o ML devolvendo "Para continuar,
    acesse sua conta". A API não tem bot wall, mas cobre bem menos que 100% — o
    scraping continua como fallback.

    ⚠ **O número de cobertura desta docstring estava errado e foi corrigido em
    2026-08-29.** Dizia "a API entrega 58% (n=70)". Os 58% vinham de uma bancada
    que validava só o atributo AUTHOR sobre `results[0]`, contando como acerto
    casamentos que a segunda folha do portão (título, `_titulo_score` estrito)
    reprova. O cliente real mede **37%** na mesma amostra, e em execução real de
    ponta a ponta o rendimento do monitor foi **24% → 41% → 20%** em três passes
    (12/50, 62/150, 30/150) — **~30% somando os três (104/350)**. Use os 30%
    como expectativa, não os 58%.
    """
    from steps.offer_resolver import inject_amazon_tag, inject_ml_affiliate

    marketplace = detect_marketplace(search_url)

    if marketplace == "mercadolivre":
        via_api = _resolve_produto_ml_api(titulo, autor, isbn)
        if via_api:
            return via_api

    soup = fetch_page(search_url)
    if soup is None:
        _resolve_stats["scrape_sem_pagina"] += 1
        return None, None

    product_url = _find_product_url(soup, marketplace, titulo, autor, estrito)
    if not product_url:
        _resolve_stats["scrape_sem_card"] += 1
        return None, None

    result = scrape_marketplace(product_url)
    if not result:
        _resolve_stats["scrape_sem_card"] += 1
        return None, None

    _resolve_stats["scrape_ok"] += 1

    afiliada = (inject_amazon_tag(product_url) if marketplace == "amazon"
                else inject_ml_affiliate(product_url))
    return result, afiliada


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

        # O ISBN vem de graca na MESMA resposta e ate 2026-08-21 era jogado
        # fora: por isso so 41 de 17.861 livros tinham ISBN no banco, e o
        # Search Console reclamava de identificador ausente. `industry
        # Identifiers` e metadado da edicao que casou, nao heuristica.
        #
        # Sem guarda de titulo aqui de proposito: esta funcao so e alcancada
        # quando o volume ja foi aceito como o livro (a descricao e a capa dele
        # tambem vem daqui). A guarda de titulo vive no `isbn_backfill`, que
        # busca as-cegas por titulo+autor e por isso precisa dela.
        isbn13 = None
        for ident in info.get("industryIdentifiers") or []:
            isbn13 = normalize_isbn13(ident.get("identifier"))
            if isbn13:
                break

        return {
            "cover_url": img.get("thumbnail") or img.get("smallThumbnail"),
            "descricao": clean_text(info.get("description")),
            "isbn":      isbn13,
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
    isbn       = result.get("isbn")
    status_cov = 1 if cover_url else 2

    # `isbn = COALESCE(isbn, ?)` e nao `COALESCE(?, isbn)`: aqui o valor que
    # JA esta no banco ganha. As outras colunas fazem o contrario de proposito
    # (dado novo da API sobrescreve), mas ISBN e identificador — se o livro ja
    # tem um, ele veio do seed validado (#291) e nao deve ser trocado pelo
    # palpite de uma busca.
    conn.execute("""
        UPDATE livros
        SET imagem_url    = COALESCE(?, imagem_url),
            descricao     = COALESCE(?, descricao),
            preco_atual   = COALESCE(?, preco_atual),
            isbn          = COALESCE(isbn, ?),
            status_enrich = ?,
            status_cover  = ?,
            updated_at    = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (
        cover_url,
        descricao,
        preco,
        isbn,
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
