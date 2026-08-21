# ============================================================
# STEP — ISBN BACKFILL (Google Books)
# Livraria Alexandria
#
# Preenche `livros.isbn` a partir de `volumeInfo.industryIdentifiers` do
# Google Books, que e METADADO da edicao — nao heuristica.
#
# POR QUE ESTE STEP EXISTE
# ------------------------
# Medido em 2026-08-21 no books.db (n=17.861): so 41 livros tinham ISBN
# (0,23%), e 4.852 dos 4.859 PUBLICADOS estavam sem (99,86%). A causa nao era
# falta de dado na origem — era descarte: `marketplace_scraper` chamava Open
# Library e Google Books, lia capa e descricao, e jogava fora o ISBN que vinha
# na mesma resposta. Prova disso: os 4.852 publicados sem ISBN TEM descricao,
# ou seja, alguma dessas APIs achou o livro.
#
# O #291 fechou a entrada (a ingestao valida o ISBN do seed) e o #289 fechou a
# saida (o site so emite ISBN valido). Este step preenche o passivo.
#
# RENDIMENTO MEDIDO (2026-08-21, n=25 livros publicados sorteados)
# ---------------------------------------------------------------
#   sem_item=0 | com ISBN valido=22 | titulo casando=21 | mismatch=1 | erro=1
#   -> ~84% de rendimento bruto com limiar UNIdirecional de 0,6.
#
# POR QUE O LIMIAR AQUI E BIDIRECIONAL E MAIS ALTO
# ------------------------------------------------
# Aquela medicao expos um falso-aceito que o limiar unidirecional nao pega: o
# titulo local pode caber INTEIRO dentro do titulo de uma coletanea ou box.
# Casos reais da amostra:
#   "Cinco Elegias"      -> "Novos poemas, 1938, e Cinco elegias"  (coletanea)
#   "Beautiful Stranger" -> "The Beautiful Series, 5 Books Colle…" (box)
# Nos dois, |A inter B| / |A| = 1,00 e o ISBN devolvido e o da COLETANEA, nao
# o do livro. Publicar isso repetiria, com outra roupa, o defeito que o #289
# corrigiu — identificador que aponta para o produto errado. Por isso o
# criterio e min(|A inter B|/|A|, |A inter B|/|B|) >= LIMIAR_TITULO: exige que
# os dois titulos se cubram, o que reprova coletanea e box.
#
# Troca consciente: perde recall para ganhar precisao. Depois do caso do
# `9788576849943`, ISBN errado custa mais caro que ISBN ausente.
#
# POR QUE NAO OPEN LIBRARY
# ------------------------
# O `search.json` devolve os ISBNs de TODAS as edicoes da obra: medido em
# 2026-08-21, "A Divina Comedia Dante" retorna 1.042 ISBNs. Sem saber qual
# edicao e a nossa, escolher um e sortear. O Google Books devolve os
# identificadores do volume que casou — especificos daquela edicao.
#
# QUOTA
# -----
# Google Books free: ~1.000 consultas/dia. Sem a API key a quota anonima e
# compartilhada e vive estourada (medido 2026-08-21: HTTP 429 sem key, HTTP
# 200 com key no mesmo minuto). Ao receber 429 o step PARA o lote e devolve o
# controle — nao insiste. Com ~4.850 publicados pendentes, o passivo drena em
# ~5 dias de autopilot; e por isso que este step e cadenciado.
#
# RETOMAVEL
# ---------
# `isbn_checado_em` e gravado inclusive quando NAO acha, entao livro que o
# Google Books nao cobre nao volta a consumir quota em todo ciclo.
# `isbn_fonte` registra de onde veio.
# ============================================================

import os
import re
import time
import unicodedata
import urllib.parse
from datetime import datetime

import requests

from core.db import get_conn
from core.isbn import normalize_isbn13
from core.logger import log

# Reaproveita a config do publish em vez de repetir URL e credencial.
from steps.publish import TABLE_URL, HEADERS


GOOGLE_BOOKS_URL = "https://www.googleapis.com/books/v1/volumes"
TIMEOUT = (10, 25)

# Quantos volumes pedir por consulta. Custa a MESMA consulta de quota que
# maxResults=1 e aumenta a chance de achar a edicao certa, em vez de aceitar
# a primeira que vier.
MAX_RESULTS = 5

# min(cobertura_local, cobertura_api). Ver o cabecalho para o porque de ser
# bidirecional.
#
# CALIBRADO em 2026-08-21 contra os 9 casos reais da amostra, nao chutado. O
# primeiro valor tentado (0,7) reprovava casamento legitimo — por isso a
# tabela existe:
#
#   ACEITAR   0,667  "Don Segundo Sombra"      | "Dom Segundo Sombra"
#   ACEITAR   0,667  "O Sentido da Existencia" | "O sentido da existencia humana"
#   ACEITAR   1,000  "Cartas de Papai Noel"    | "Cartas do Papai Noel"
#   ACEITAR   1,000  "O Invencivel"            | "Invencivel"
#   ACEITAR   1,000  "O cemiterio de Praga"    | "O Cemiterio de Praga"
#   REJEITAR  0,500  "Mikael Karvajalka"       | "Aventuras en Oriente de Mikael…"
#   REJEITAR  0,400  "Cinco Elegias"           | "Novos poemas, 1938, e Cinco elegias"
#   REJEITAR  0,333  "Kafka: Os Anos Decisivos"| "Kafka"
#   REJEITAR  0,286  "Beautiful Stranger"      | "The Beautiful Series, 5 Books…"
#
# Pior ACEITAR = 0,667; pior REJEITAR = 0,500. O limiar fica no meio da faixa
# vazia. Ao mexer nele, refazer esta tabela — ela e o teste de regressao em
# forma legivel, e `tests/test_isbn_backfill.py` a cobre caso a caso.
LIMIAR_TITULO = 0.6

# Pausa entre consultas. A API nao documenta rate limit por segundo, mas
# responde 503 sob rajada (visto em 2026-08-21).
PAUSA = 1.2


# =========================
# SCHEMA
# =========================

def ensure_columns(conn):
    """Cria as colunas de rastreio se faltarem. Idempotente."""
    existentes = {r[1] for r in conn.execute("PRAGMA table_info(livros)")}
    for coluna in ("isbn_checado_em", "isbn_fonte"):
        if coluna not in existentes:
            conn.execute(f"ALTER TABLE livros ADD COLUMN {coluna} TEXT")
            log(f"[ISBN] coluna {coluna} criada")
    conn.commit()


# =========================
# COMPARACAO DE TITULO
# =========================

def _tokens(texto):
    """Tokens comparaveis: sem acento, sem pontuacao, sem palavra curta.

    O corte em len > 2 tira artigo e preposicao ("de", "do", "the", "la"),
    que aparecem em quase todo titulo e inflariam a similaridade.
    """
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return {p for p in re.sub(r"[^a-z0-9 ]", " ", t).split() if len(p) > 2}


def similaridade_titulo(local, remoto):
    """Cobertura BIDIRECIONAL entre dois titulos, de 0 a 1.

    Devolve min(|A inter B|/|A|, |A inter B|/|B|). O segundo termo e o que
    reprova coletanea e box, em que o titulo do livro cabe inteiro dentro do
    titulo do volume — ver o cabecalho do modulo.
    """
    a, b = _tokens(local), _tokens(remoto)
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return min(inter / len(a), inter / len(b))


# =========================
# GOOGLE BOOKS
# =========================

class QuotaEstourada(Exception):
    """HTTP 429 — a quota do dia acabou. Para o lote; nao e falha do livro."""


def buscar_isbn(titulo, autor, api_key):
    """Devolve (isbn13, titulo_casado) ou (None, motivo).

    Nao levanta excecao por livro — so `QuotaEstourada`, que e do lote.
    """
    consulta = f"{titulo} {autor}".strip() if autor else (titulo or "")
    if not consulta.strip():
        return None, "sem titulo"

    params = {"q": consulta, "maxResults": MAX_RESULTS}
    if api_key:
        params["key"] = api_key

    try:
        resp = requests.get(
            f"{GOOGLE_BOOKS_URL}?{urllib.parse.urlencode(params)}",
            timeout=TIMEOUT,
        )
    except Exception as e:
        return None, f"erro de rede: {type(e).__name__}"

    if resp.status_code == 429:
        raise QuotaEstourada()
    if resp.status_code != 200:
        return None, f"HTTP {resp.status_code}"

    try:
        itens = resp.json().get("items") or []
    except Exception:
        return None, "resposta ilegivel"

    if not itens:
        return None, "sem resultado"

    # Percorre os candidatos e fica com o de MAIOR similaridade que tenha um
    # ISBN valido — nao com o primeiro que aparecer.
    # Comeca em -1, nao em 0: com 0 o candidato de similaridade ZERO nunca era
    # registrado, e a funcao devolvia "nenhum candidato com ISBN valido"
    # quando o certo era "titulo divergente" — motivo errado no log, que e
    # justamente onde se diagnostica por que um livro nao recebeu ISBN.
    melhor_sim, melhor_isbn, melhor_titulo = -1.0, None, None
    for item in itens:
        vi = item.get("volumeInfo") or {}
        isbns = [
            normalize_isbn13(ident.get("identifier"))
            for ident in (vi.get("industryIdentifiers") or [])
        ]
        isbns = [i for i in isbns if i]
        if not isbns:
            continue
        sim = similaridade_titulo(titulo, vi.get("title"))
        if sim > melhor_sim:
            melhor_sim, melhor_isbn, melhor_titulo = sim, isbns[0], vi.get("title")

    if not melhor_isbn:
        return None, "nenhum candidato com ISBN valido"
    if melhor_sim < LIMIAR_TITULO:
        return None, f"titulo divergente ({melhor_sim:.2f}): {melhor_titulo!r}"
    return melhor_isbn, melhor_titulo


# =========================
# SUPABASE
# =========================

def patch_isbn_supabase(supabase_id, isbn):
    """PATCH so da coluna isbn.

    Deliberadamente NAO usa `publish.upsert_book`: aquele reenvia o payload
    inteiro e sobrescreveria sinopse, imagem e afins no Supabase com o estado
    local. Aqui o objetivo e uma coluna — o PATCH mantem o resto intacto.
    """
    try:
        res = requests.patch(
            f"{TABLE_URL}?id=eq.{supabase_id}",
            headers=HEADERS,
            json={"isbn": isbn},
            timeout=30,
        )
        if res.status_code in (200, 204):
            return True
        log(f"[ISBN] Supabase {res.status_code} -> {res.text[:120]}")
    except Exception as e:
        log(f"[ISBN] Supabase falhou: {type(e).__name__}")
    return False


# =========================
# SELECAO
# =========================

_PENDENTES_WHERE = """
    WHERE (isbn IS NULL OR TRIM(isbn) = '')
      AND isbn_checado_em IS NULL
      AND titulo IS NOT NULL AND TRIM(titulo) != ''
      AND is_publishable = 1
"""


def fetch_pending(conn, limite):
    """Livros sem ISBN e ainda nao consultados.

    Ordem: publicados primeiro (sao os que o site emite no JSON-LD), depois os
    que ja tem descricao — sinal de que alguma API achou o livro, entao a
    chance de existir ISBN e maior.
    """
    cur = conn.cursor()
    cur.execute(f"""
        SELECT id, titulo, autor, supabase_id
        FROM livros
        {_PENDENTES_WHERE}
        ORDER BY
            status_publish DESC,
            CASE WHEN descricao IS NOT NULL AND TRIM(descricao) != ''
                 THEN 0 ELSE 1 END,
            priority_score DESC
        LIMIT ?
    """, (limite,))
    return cur.fetchall()


def contar_pendentes(conn):
    return conn.execute(
        f"SELECT COUNT(*) FROM livros {_PENDENTES_WHERE}"
    ).fetchone()[0]


# =========================
# RUN
# =========================

def run(pacote=40, sincronizar_supabase=True):
    """Preenche o ISBN de ate `pacote` livros. Devolve quantos foram preenchidos."""

    log("ISBN Backfill iniciado…")

    api_key = os.getenv("GOOGLE_BOOKS_API_KEY", "")
    if not api_key:
        # Sem key, a quota anonima e compartilhada e vive estourada — rodar
        # assim so gasta tempo para colher 429. Ver o cabecalho.
        log("[ISBN] GOOGLE_BOOKS_API_KEY ausente — a quota anonima vive "
            "estourada; step pulado.")
        return 0

    conn = get_conn()
    ensure_columns(conn)

    pendentes = contar_pendentes(conn)
    rows = fetch_pending(conn, pacote)
    if not rows:
        log("[ISBN] Nenhum livro pendente de ISBN.")
        conn.close()
        return 0

    log(f"[ISBN] {len(rows)} livros neste lote ({pendentes} pendentes no total).")

    agora = datetime.utcnow().isoformat()
    preenchidos = sem_achar = sincronizados = 0

    for i, row in enumerate(rows, start=1):
        livro_id = row["id"]
        titulo = row["titulo"]
        autor = row["autor"]
        supabase_id = row["supabase_id"]

        try:
            isbn, detalhe = buscar_isbn(titulo, autor, api_key)
        except QuotaEstourada:
            log(f"[ISBN] Quota do Google Books estourada — lote parado em "
                f"{i - 1}/{len(rows)}. Retoma no proximo ciclo.")
            break

        if isbn:
            conn.execute("""
                UPDATE livros
                SET isbn = ?, isbn_fonte = 'google_books',
                    isbn_checado_em = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (isbn, agora, livro_id))
            preenchidos += 1
            print(f"[ISBN][{i:03d}/{len(rows):03d}] {isbn} <- {titulo}")

            # Livro ja publicado nao volta pelo step de publish (ele so pega
            # status_publish = 0), entao o ISBN novo so chega ao site por aqui.
            if sincronizar_supabase and supabase_id:
                if patch_isbn_supabase(supabase_id, isbn):
                    sincronizados += 1
        else:
            conn.execute("""
                UPDATE livros
                SET isbn_checado_em = ?, isbn_fonte = 'nao_encontrado',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (agora, livro_id))
            sem_achar += 1
            print(f"[ISBN][{i:03d}/{len(rows):03d}] -- {titulo} ({detalhe})")

        conn.commit()
        time.sleep(PAUSA)

    conn.commit()
    restantes = contar_pendentes(conn)
    conn.close()

    log(f"[ISBN] Preenchidos: {preenchidos} | Sem ISBN: {sem_achar} | "
        f"Sincronizados no Supabase: {sincronizados} | Restam: {restantes}")

    return preenchidos


if __name__ == "__main__":
    run()
