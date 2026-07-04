# ============================================================
# STEP 2 — DESCRIPTION ENRICHMENT
# Livraria Alexandria
#
# Busca descrição no Google Books para todos os livros
# que ainda não possuem descricao preenchida.
# Sem LLM. Apenas REST API.
# Usa GOOGLE_BOOKS_API_KEY se disponível em scripts/.env
# ============================================================

import os
import sqlite3
import time
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

import requests
from dotenv import load_dotenv


# =========================
# ENV
# =========================

_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=_ENV_PATH)

GOOGLE_BOOKS_API_KEY = os.getenv("GOOGLE_BOOKS_API_KEY", "")


# =========================
# CONFIG
# =========================

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

DB_PATH = os.path.join(DATA_DIR, "books.db")

GOOGLE_BOOKS_URL = "https://www.googleapis.com/books/v1/volumes"

REQUEST_DELAY = 0.3
MIN_DESC_LENGTH = 50
TITLE_SIMILARITY_THRESHOLD = 0.5  # mínimo de similaridade entre título buscado e retornado


# =========================
# TITLE VALIDATION
# =========================

def _normalize_title(s: str) -> str:
    """Normaliza título para comparação: NFKD → ASCII → minúsculas."""
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode("ascii").lower().strip()


def _title_matches(expected: str, returned: str) -> bool:
    """
    Retorna True se o título retornado pelo Google Books é compatível com o
    título que estava sendo buscado. Evita aceitar descrições de livros errados.

    Critérios (qualquer um satisfatório):
    1. O título buscado é substring do título retornado (ex: "Sapiens" em "Sapiens: A Brief History")
    2. O título retornado é substring do título buscado (ex: edição abreviada)
    3. Similaridade SequenceMatcher >= TITLE_SIMILARITY_THRESHOLD
    """
    n_expected = _normalize_title(expected)
    n_returned = _normalize_title(returned)

    if not n_returned:
        return False

    if n_expected in n_returned or n_returned in n_expected:
        return True

    ratio = SequenceMatcher(None, n_expected, n_returned).ratio()
    return ratio >= TITLE_SIMILARITY_THRESHOLD


def _author_matches(expected: str, returned_authors) -> bool:
    """
    Retorna True se algum autor retornado pelo Google Books casa com o autor
    buscado. Usado como fallback quando o título não bate: obra estrangeira
    catalogada com título PT ("O Advogado") cuja edição EN tem descrição, mas
    título divergente. O autor é o discriminador language-agnostic.

    Critérios (qualquer um): containment de nome normalizado ou sobrenome igual.
    """
    n_expected = _normalize_title(expected)
    if not n_expected:
        return False
    for a in (returned_authors or []):
        n_a = _normalize_title(a)
        if not n_a:
            continue
        if n_a in n_expected or n_expected in n_a:
            return True
        exp_parts, a_parts = n_expected.split(), n_a.split()
        if exp_parts and a_parts and exp_parts[-1] == a_parts[-1]:
            return True
    return False


# =========================
# LOGGER
# =========================

def log(msg):
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {msg}")


# =========================
# DB CONNECTION
# =========================

def get_conn():

    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=60000")

    return conn


# =========================
# FETCH PENDING
# =========================

def fetch_pending(conn, limit, retry_failed=False):

    cur = conn.cursor()

    # retry_failed=True reinclui os que falharam antes (status_descricao=2):
    # a rodada original pode ter desistido por rate limit / falta de API key,
    # e o matching por autor + fallback multi-idioma recupera boa parte deles.
    status_filter = "status_descricao IN (0, 2)" if retry_failed else "status_descricao = 0"

    cur.execute(f"""
        SELECT id, titulo, autor
        FROM livros
        WHERE {status_filter}
          AND (descricao IS NULL OR TRIM(descricao) = '')
        LIMIT ?
    """, (limit,))

    return cur.fetchall()


# =========================
# GOOGLE BOOKS LOOKUP
# =========================

def _pick_descricao(candidatos, titulo, autor):
    """
    Escolhe a melhor descrição entre os candidatos do Google Books em camadas,
    preferindo português e caindo para qualquer idioma (a sinopse final é sempre
    gerada em PT pelo agente, que aceita descrição-fonte em outro idioma).

    Ordem de prioridade:
      1. título casa + idioma PT      2. título casa (qualquer idioma)
      3. autor casa  + idioma PT      4. autor casa (qualquer idioma)
      5. PT (top-relevância)          6. qualquer (top-relevância — mais fraco)

    A camada 5/6 (sem casar título nem autor) é segura porque o agente de sinopse
    tem gate de coerência título×descrição: se pegar o livro errado, a sinopse é
    rejeitada (synopsis-title-mismatch), não publicada.

    Retorna (descricao, camada, idioma) ou (None, None, None).
    """
    tmatch = [c for c in candidatos if _title_matches(titulo, c["titulo"])]
    amatch = [c for c in candidatos if _author_matches(autor, c["autores"])]

    def pt(pool):
        return [c for c in pool if (c["idioma"] or "").lower().startswith("pt")]

    for pool, camada in (
        (pt(tmatch), "titulo/pt"),
        (tmatch,     "titulo"),
        (pt(amatch), "autor/pt"),
        (amatch,     "autor"),
        (pt(candidatos), "top-rel/pt"),
        (candidatos, "top-rel"),
    ):
        if pool:
            c = pool[0]
            return c["descricao"], camada, (c["idioma"] or "?")
    return None, None, None


def fetch_descricao(titulo, autor):

    query = f"{titulo} {autor}".strip()

    time.sleep(REQUEST_DELAY)

    params = {"q": query, "maxResults": 5}

    if GOOGLE_BOOKS_API_KEY:
        params["key"] = GOOGLE_BOOKS_API_KEY

    for tentativa in range(2):
        try:
            res = requests.get(
                GOOGLE_BOOKS_URL,
                params=params,
                timeout=15,
            )

            if res.status_code != 200:
                log(f"[ENRICH] HTTP {res.status_code} → {titulo}")
                return None

            items = res.json().get("items", [])

            # Reúne candidatos com descrição usável; a escolha (título/autor/
            # idioma) é feita em camadas por _pick_descricao.
            candidatos = []
            for item in items:
                info = item.get("volumeInfo", {})
                descricao = info.get("description")
                if descricao and len(descricao.strip()) >= MIN_DESC_LENGTH:
                    candidatos.append({
                        "titulo":    info.get("title", ""),
                        "autores":   info.get("authors", []),
                        "idioma":    info.get("language", ""),
                        "descricao": descricao.strip(),
                    })

            descricao, camada, idioma = _pick_descricao(candidatos, titulo, autor)
            if descricao:
                if camada.startswith("top-rel"):
                    log(f"[ENRICH] match fraco ({camada}/{idioma}) -> {titulo}")
                elif not camada.endswith("/pt") and idioma:
                    log(f"[ENRICH] descricao {idioma} ({camada}) -> {titulo}")
                return descricao

            return None  # sem resultado compatível — não adianta retry

        except requests.RequestException as e:
            log(f"[ENRICH] Falha de rede (tentativa {tentativa + 1}/2) → {e}")
            if tentativa == 0:
                time.sleep(3)

        except Exception as e:
            log(f"[ENRICH] Erro inesperado → {e}")
            return None

    return None


# =========================
# UPDATE
# =========================

def update_descricao(conn, livro_id, descricao, status_descricao):

    cur = conn.cursor()

    cur.execute("""
        UPDATE livros
        SET descricao         = COALESCE(?, descricao),
            status_descricao  = ?,
            updated_at        = ?
        WHERE id = ?
    """, (descricao, status_descricao, datetime.utcnow().isoformat(), livro_id))

    conn.commit()


# =========================
# RUN
# =========================

def run(pacote=500, retry_failed=False):

    log("Iniciando Description Enrichment...")

    if GOOGLE_BOOKS_API_KEY:
        log("[ENRICH] Usando Google Books API Key")
    else:
        log("[ENRICH] AVISO: sem API key — rate limit reduzido")
    if retry_failed:
        log("[ENRICH] retry_failed=True — reprocessando também os status_descricao=2")

    if not os.path.exists(DB_PATH):
        log("Banco não encontrado. Execute o step 1 primeiro.")
        return

    conn = get_conn()

    rows = fetch_pending(conn, pacote, retry_failed=retry_failed)

    if not rows:
        log("Nenhum livro pendente de enriquecimento.")
        conn.close()
        return

    total    = len(rows)
    enriched = 0
    failed   = 0

    log(f"{total} livros sem descrição encontrados")

    for i, row in enumerate(rows, start=1):

        livro_id = row["id"]
        titulo   = row["titulo"]
        autor    = row["autor"] or ""

        log(f"[{i}/{total}] {titulo}")

        descricao = fetch_descricao(titulo, autor)

        if descricao:
            update_descricao(conn, livro_id, descricao, status_descricao=1)
            enriched += 1
            log(f"[OK] → {titulo}")
        else:
            update_descricao(conn, livro_id, None, status_descricao=2)
            failed += 1
            log(f"[--] Sem descrição → {titulo}")

    conn.close()

    log(f"Finalizado — OK: {enriched} | Sem descrição: {failed}")