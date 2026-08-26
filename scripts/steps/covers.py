# ============================================================
# STEP 8 — COVERS
# Livraria Alexandria
#
# Cadeia de fallback:
#   1. Amazon (URL direta por ISBN)
#   2. Google Books API
#   3. OpenLibrary
#
# status_cover:
#   0 = pendente
#   1 = capa encontrada
#   2 = sem capa (não bloqueia o pipeline)
# ============================================================

import os
import re
import sqlite3
import time
from datetime import datetime

import requests
from dotenv import load_dotenv

from core import interrupt as _interrupt


# =========================
# CONFIG
# =========================

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH  = os.path.join(DATA_DIR, "books.db")

load_dotenv(os.path.join(BASE_DIR, ".env"))
GOOGLE_BOOKS_API_KEY = os.getenv("GOOGLE_BOOKS_API_KEY", "")

AMAZON_COVER      = "https://images-na.ssl-images-amazon.com/images/P/{isbn}.jpg"
GOOGLE_BOOKS_URL  = "https://www.googleapis.com/books/v1/volumes"
OPENLIBRARY_COVER = "https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg"

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; LibraryBot/1.0)"}
TIMEOUT = 15
MIN_IMAGE_BYTES = 5000   # abaixo disso = placeholder


# =========================
# LOGGER
# =========================

def log(msg):
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {msg}", flush=True)


# =========================
# DB
# =========================

def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


# =========================
# FETCHERS
# =========================

def fetch_amazon_cover(isbn):
    """URL direta da Amazon por ISBN — sem API key."""
    if not isbn:
        return None
    url = AMAZON_COVER.format(isbn=isbn)
    try:
        res = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if res.status_code == 200 and len(res.content) > MIN_IMAGE_BYTES:
            return url
    except Exception:
        pass
    return None


# Zoom da capa do Google Books. A capa é exibida a 176x256 px
# (`app/_components/BookCover.tsx`), com `priority` — ou seja, é o elemento de
# LCP da página de livro.
#
# ⚠ Até 2026-08-26 esta função fazia `thumb.replace("&zoom=1", "&zoom=0")`, com
# o comentário "remove zoom baixo". `zoom=0` é a resolução CHEIA, e o resultado
# medido em 2026-08-26 no books.db foi: **1.294 das 2.137 capas do Google Books
# (60%) ficaram em `zoom=0`**, servindo centenas de KB para exibir 176 px.
#
# Medido na mesma data, na capa de `o-jardim-das-rosas`:
#
#   | variante      | peso   | tempo  |
#   |---------------|--------|--------|
#   | zoom=0 (antes)| 593 KB | 1,56 s |
#   | zoom=2 (hoje) |  40 KB | 0,96 s |
#   | zoom=1        |  24 KB | 0,39 s |
#
# `zoom=2` e não `zoom=1`: o 1 entrega ~128 px de largura, que borra numa tela
# 2x sobre um slot de 176 px. O 2 é o menor que ainda cobre retina.
ZOOM_GOOGLE_BOOKS = "2"

_ZOOM_RE = re.compile(r"([?&])zoom=\d+")


def normalizar_capa_google(url):
    """Forma canônica da URL de capa do Google Books: HTTPS + zoom alvo.

    As duas correções vivem juntas porque são o mesmo campo e o mesmo passe.
    Além do zoom, medido em 2026-08-26: **837 capas PUBLICADAS estavam em
    `http://`** (1.875 no banco todo). O site é HTTPS, então isso é conteúdo
    misto — o navegador bloqueia ou faz upgrade por conta própria, e em nenhum
    dos dois casos é o que queremos servir. `fetch_google_cover` já forçava
    HTTPS nas capas NOVAS desde sempre; o passivo antigo nunca foi reescrito
    porque `publish.fetch_pendentes` filtra `status_publish = 0` e cada livro é
    enviado ao Supabase uma única vez.

    Só age em books.google.com — as capas do OpenLibrary usam sufixo `-L`/`-M`
    no path e não têm este parâmetro.
    """
    if not url or "books.google.com" not in url:
        return url
    url = url.replace("http://", "https://")
    if _ZOOM_RE.search(url):
        return _ZOOM_RE.sub(r"\1zoom=" + ZOOM_GOOGLE_BOOKS, url)
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}zoom={ZOOM_GOOGLE_BOOKS}"


def fetch_google_cover(titulo, autor, isbn=None):
    """Google Books API — busca por ISBN primeiro, depois título+autor."""
    try:
        query = f"isbn:{isbn}" if isbn else f"{titulo} {autor}"
        params = {"q": query, "maxResults": 1}
        if GOOGLE_BOOKS_API_KEY:
            params["key"] = GOOGLE_BOOKS_API_KEY

        res = requests.get(GOOGLE_BOOKS_URL, params=params,
                           headers=HEADERS, timeout=TIMEOUT)
        items = res.json().get("items")
        if not items:
            return None

        links = items[0]["volumeInfo"].get("imageLinks", {})
        thumb = (links.get("large")
                 or links.get("medium")
                 or links.get("thumbnail")
                 or links.get("smallThumbnail"))

        if thumb:
            return normalizar_capa_google(thumb)

    except Exception:
        pass
    return None


def fetch_openlibrary_cover(isbn):
    """OpenLibrary — fallback final, checa tamanho para evitar placeholder."""
    if not isbn:
        return None
    url = OPENLIBRARY_COVER.format(isbn=isbn)
    try:
        res = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if res.status_code == 200 and len(res.content) > MIN_IMAGE_BYTES:
            return url
    except Exception:
        pass
    return None


# =========================
# FETCH PENDING
# =========================

def fetch_pending(conn, idioma, limit, book_ids=None):
    cur = conn.cursor()
    # Alvo explícito (remediação de QA): processa só os ids pedidos, sem filtrar
    # por idioma. Reaproveita o MESMO motor de capas — não há script paralelo.
    if book_ids:
        placeholders = ",".join("?" * len(book_ids))
        cur.execute(f"""
            SELECT id, titulo, autor, isbn
            FROM livros
            WHERE status_cover = 0
              AND id IN ({placeholders})
            ORDER BY priority_score DESC, created_at ASC
        """, tuple(book_ids))
        return cur.fetchall()
    # `idioma IS NULL` entra na fila: a busca de capa consulta Amazon/Google/
    # OpenLibrary por ISBN/título/autor — o idioma não influencia o resultado,
    # então filtrá-lo só exclui. Medido em 2026-08-20 (SQLite local): os 19
    # livros com status_cover=0 tinham TODOS idioma NULL, e como "NULL = 'PT'"
    # nunca é verdadeiro em SQL, o autopilot os contava como gargalo e o step
    # selecionava zero — 77 ciclos de fallback com "Progresso: 0" nos logs de
    # 17/08 e 18/08. Ver log_analysis_2026-08-17_05-35-45.json.
    cur.execute("""
        SELECT id, titulo, autor, isbn
        FROM livros
        WHERE status_cover = 0
          AND (idioma = ? OR idioma IS NULL)
        ORDER BY priority_score DESC, created_at ASC
        LIMIT ?
    """, (idioma, limit))
    return cur.fetchall()


# =========================
# UPDATE
# =========================

def update_cover(conn, book_id, url, status):
    cur = conn.cursor()
    cur.execute("""
        UPDATE livros
        SET imagem_url   = ?,
            status_cover = ?,
            updated_at   = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (url, status, book_id))
    conn.commit()


# =========================
# RUN
# =========================

def run(idioma, pacote=10, book_ids=None):

    conn = get_conn()
    rows = fetch_pending(conn, idioma, pacote, book_ids=book_ids)

    if not rows:
        alvo = f"{len(book_ids)} ids" if book_ids else f"[{idioma}]"
        log(f"Nada pendente para capas ({alvo}).")
        conn.close()
        return

    ok = 0
    amazon_used = 0
    google_used = 0
    openlibrary_used = 0
    failed = 0
    total  = len(rows)

    try:
        for i, (book_id, titulo, autor, isbn) in enumerate(rows, start=1):

            if _interrupt.requested():
                log("[CAPA] Interrupção solicitada — encerrando após o último livro salvo.")
                break

            log(f"[CAPA][{i:03d}/{total:03d}] → {titulo}")

            cover  = None
            source = None

            # 1. Amazon
            cover = fetch_amazon_cover(isbn)
            if cover:
                source = "amazon"
                amazon_used += 1

            # 2. Google Books
            if not cover:
                cover = fetch_google_cover(titulo, autor, isbn)
                if cover:
                    source = "google"
                    google_used += 1

            # 3. OpenLibrary
            if not cover:
                cover = fetch_openlibrary_cover(isbn)
                if cover:
                    source = "openlibrary"
                    openlibrary_used += 1

            if cover:
                update_cover(conn, book_id, cover, status=1)
                ok += 1
                log(f"[CAPA] OK [{source}] → {titulo}")
            else:
                update_cover(conn, book_id, None, status=2)
                failed += 1
                log(f"[CAPA] SEM CAPA → {titulo}")

            time.sleep(0.3)

    except KeyboardInterrupt:
        log("[CAPA] Interrompido pelo usuário — progresso salvo até aqui.")

    conn.close()

    log(f"[CAPA] Finalizado | OK={ok} amazon={amazon_used} google={google_used} "
        f"openlibrary={openlibrary_used} | sem_capa={failed}")
