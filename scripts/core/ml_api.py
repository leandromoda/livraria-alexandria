# ============================================================
# CORE — API de catálogo do Mercado Livre
# Livraria Alexandria
#
# Substitui o scraping como fonte de preço e deep link. Ver TASK-OFERTAS-005.
#
# POR QUE EXISTE (medido em 2026-08-24 e 2026-08-29):
#   O scraping entregou 4 de 50 livros num passe real do G — a Amazon respondeu
#   503 nas 3 tentativas e o ML devolveu a página "Para continuar, acesse sua
#   conta". O gargalo deixou de ser o código e passou a ser o bot wall.
#
#   A Amazon não tem saída oficial hoje: a PA-API foi desligada em 15/05/2026 e
#   a Creators API que a substitui exige >=10 vendas qualificadas em 30 dias.
#   O ML tem, e é esta.
#
# O QUE ABRE E O QUE NÃO ABRE (sondado em 2026-08-29, ver tools/probe_ml_*.py):
#   /oauth/token client_credentials ....... OK, token de 21600 s
#   /sites/MLB/search ..................... 403 mesmo com token — fechado
#   /items/{id} ........................... fechado
#   /products/search ...................... ABERTO — é a porta
#   /products/{id}/items .................. ABERTO — traz o `price`
#
# ⚠ A ARMADILHA CENTRAL: `/products/search` NUNCA responde "não achei" — ela
#   devolve o produto mais parecido. Medido (n=70): 97% "encontrou" produto, e
#   19 desses eram livro ERRADO. "Sob a Roda" (Hermann Hesse) devolveu "Sob a
#   Selva"; "Mistério no Castelo de Chimneys" (Agatha Christie) devolveu "O
#   Mistério do Castelo Abandonado".
#
#   Por isso `_autor_confere` é PORTÃO, não refinamento. Sem ele, trocaríamos
#   "preço do livro errado por scraping" por "preço do livro errado por API" —
#   pior, porque agora com deep link para o produto errado.
#
#   Utilizável de verdade (autor confere E tem preço): 41 de 70 = 58%.
#   Contra os 8% do scraping sob bot wall.
# ============================================================

import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

from core.logger import log

API = "https://api.mercadolibre.com"
SITE = "MLB"
DOMINIO_LIVRO = "MLB-BOOKS"
TIMEOUT = 20

# A capa/detalhe do produto de catálogo mora nesta URL. A API não devolve
# `permalink` (medido: vem vazio), mas esta forma é a canônica — confirmada em
# navegador logado: título correto, sem muro, e elegível a afiliado.
URL_PRODUTO = "https://www.mercadolivre.com.br/p/{produto_id}"

_token = {"valor": None, "expira_em": 0.0}


def _credenciais():
    return (os.getenv("ML_CLIENT_ID", "").strip(),
            os.getenv("ML_CLIENT_SECRET", "").strip())


def configurado() -> bool:
    """Só diz se as chaves existem — não valida contra o servidor."""
    cid, csec = _credenciais()
    return bool(cid and csec)


# =========================
# HTTP
# =========================

def _post_form(url, dados):
    body = urllib.parse.urlencode(dados).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode())


def _get(url, token):
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode())


def token(forcar=False):
    """Token de aplicação, com cache em memória.

    O token vale 6 h e o G roda por horas num processo só, então cache em
    memória cobre o caso real sem gravar segredo em disco. Renova 5 min antes
    de expirar, para não perder uma chamada na virada.
    """
    agora = time.time()
    if not forcar and _token["valor"] and agora < _token["expira_em"] - 300:
        return _token["valor"]

    cid, csec = _credenciais()
    if not (cid and csec):
        return None

    d = _post_form(f"{API}/oauth/token", {
        "grant_type": "client_credentials",
        "client_id": cid, "client_secret": csec})
    _token["valor"] = d.get("access_token")
    _token["expira_em"] = agora + float(d.get("expires_in", 21600))
    return _token["valor"]


# =========================
# PRÉ-VOO — mesmo contrato de claude_runner.session_status()
# =========================

def status():
    """(estado, detalhe) — `ok | sem_credencial | auth | erro`.

    Mesma ideia do pré-voo da sessão do claude CLI: uma chamada trivial ANTES
    de o autopilot gastar um passe inteiro. Sem isso, o monitor de preços
    tentaria a API livro a livro e cairia no fallback de scraping em todos,
    gastando os ~25 s de backoff por livro do bot wall para nada.
    """
    if not configurado():
        return "sem_credencial", ("ML_CLIENT_ID / ML_CLIENT_SECRET ausentes em "
                                  "scripts/.env")
    try:
        tk = token(forcar=True)
    except urllib.error.HTTPError as e:
        corpo = ""
        try:
            corpo = (e.read().decode() or "")[:160]
        except Exception:
            pass
        if e.code in (400, 401, 403):
            return "auth", f"HTTP {e.code} ao pedir token: {corpo}"
        return "erro", f"HTTP {e.code} ao pedir token: {corpo}"
    except Exception as e:
        return "erro", f"{type(e).__name__}: {e}"

    if not tk:
        return "auth", "servidor não devolveu access_token"

    # Token válido não basta: a porta que usamos precisa estar aberta. O
    # /sites/MLB/search, por exemplo, responde 403 com token perfeitamente bom.
    try:
        d = _get(f"{API}/products/search?status=active&site_id={SITE}"
                 f"&q={urllib.parse.quote('dom casmurro')}", tk)
    except urllib.error.HTTPError as e:
        return "erro", f"/products/search respondeu HTTP {e.code}"
    except Exception as e:
        return "erro", f"/products/search: {type(e).__name__}"

    n = len(d.get("results", []))
    if n == 0:
        return "erro", "/products/search respondeu 200 mas sem resultados"
    return "ok", f"token válido e /products/search respondendo ({n} resultados)"


# =========================
# CASAMENTO DE AUTOR — o portão
# =========================

def _tokens(texto):
    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return [w for w in re.sub(r"[^a-z0-9\s]", " ", t.lower()).split() if len(w) > 2]


def _autor_confere(autor_nosso, autor_ml):
    """True/False/None (indeterminado quando falta um dos lados).

    Critério: algum token significativo do nosso autor aparece no autor do ML.
    O ML escreve tanto "Machado de Assis" quanto "Adams, Douglas", então
    comparar conjuntos de tokens cobre as duas formas.

    `None` NÃO é aprovação — quem decide é `buscar_livro`, que rejeita.
    """
    a = _tokens(autor_nosso)
    b = set(_tokens(autor_ml))
    if not a or not b:
        return None
    return any(x in b for x in a)


# =========================
# BUSCA
# =========================

def _produtos(consulta, tk):
    url = (f"{API}/products/search?status=active&site_id={SITE}"
           f"&q={urllib.parse.quote(str(consulta))}")
    try:
        d = _get(url, tk)
    except Exception:
        return []
    return [p for p in d.get("results", [])
            if p.get("domain_id") == DOMINIO_LIVRO]


def _preco(produto_id, tk):
    """Preço do anúncio vencedor. `/items/{id}` está fechado, mas o preço já
    vem em `/products/{id}/items` — não precisamos daquele."""
    try:
        d = _get(f"{API}/products/{produto_id}/items", tk)
    except Exception:
        return None, None
    itens = d.get("results") or []
    if not itens:
        return None, None
    return itens[0].get("price"), d.get("paging", {}).get("total")


def buscar_livro(titulo, autor=None, isbn=None):
    """Resolve um livro no catálogo do ML.

    Retorna dict com produto_id, preco, url e autor_ml — ou None.

    REJEITA quando o autor não confere. Medido em 2026-08-29: sem esse portão,
    19 de 68 resultados eram livro errado. Falso negativo aqui é barato (o item
    fica sem preço, como já está hoje); falso positivo publica preço e deep
    link do produto errado.
    """
    tk = token()
    if not tk:
        return None

    candidatos = []
    via = None
    if isbn and str(isbn).strip():
        candidatos = _produtos(str(isbn).strip(), tk)
        via = "isbn"
    if not candidatos:
        consulta = f"{titulo} {autor or ''}".strip()
        candidatos = _produtos(consulta, tk)
        via = "titulo"
    if not candidatos:
        return None

    # ⚠ O portão tem DUAS folhas, e a segunda custou uma medição para aparecer.
    # Com só a validação de autor, "Mistério no Castelo de Chimneys" (Agatha
    # Christie) foi ACEITO apontando para "Um mistério no Caribe" — outro livro
    # DA MESMA AUTORA. É a mesma classe do falso positivo de série que o
    # `_titulo_score(estrito=True)` já resolvia no scraping ("Praticamente
    # Inofensiva" casando com "O Guia do Mochileiro"). Reusar aquele critério
    # aqui, em vez de reescrever, mantém uma regra só para os dois caminhos.
    from steps.marketplace_scraper import _titulo_score   # import tardio: o
    # caminho inverso (marketplace_scraper -> ml_api) também é tardio, então
    # não há ciclo em tempo de import.

    # Escolhe o MELHOR candidato aprovado, não o primeiro — mesma correção que
    # o `_find_product_url` recebeu no scraping. Medido: com "primeiro que
    # passa", "Comunicação Não Violenta" resolvia para o "Kit Comunicação Não
    # Violenta + Vive" a R$ 151,43 (um combo) em vez do livro. O portão aceita
    # os dois, porque o kit contém todos os tokens do título; a pontuação os
    # separa, porque o kit carrega tokens a mais.
    aprovados = []
    for p in candidatos[:5]:
        attrs = {a["id"]: a.get("value_name") for a in p.get("attributes", [])}
        if _autor_confere(autor, attrs.get("AUTHOR")) is not True:
            continue                     # inclui o indeterminado: não aprova
        titulo_ml = attrs.get("BOOK_TITLE") or p.get("name") or ""
        score = _titulo_score(titulo, titulo_ml, estrito=True)
        if score is not None:
            aprovados.append((score, p, attrs, titulo_ml))

    # Melhor primeiro, mas SEM desistir no primeiro sem preço: nem todo produto
    # de catálogo tem anúncio ativo, e desistir ali custaria cobertura à toa.
    aprovados.sort(key=lambda x: x[0], reverse=True)
    for _score, p, attrs, titulo_ml in aprovados:
        preco, n_anuncios = _preco(p["id"], tk)
        if preco is None:
            continue
        return {
            "produto_id": p["id"],
            "preco": float(preco),
            "url": URL_PRODUTO.format(produto_id=p["id"]),
            "titulo_ml": titulo_ml,
            "autor_ml": attrs.get("AUTHOR"),
            "gtin": attrs.get("GTIN"),
            "n_anuncios": n_anuncios,
            "via": via,
        }
    return None
