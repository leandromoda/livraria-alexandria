import requests
import re
import unicodedata

from core.db import get_conn
from core.logger import log

# =========================
# CONFIG
# =========================

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "phi3:mini"

# =========================
# PROMPT REVISÃO
# =========================

def build_prompt(texto):

    return f"""
Revise a sinopse abaixo.

Objetivos:

- Corrigir gramática
- Corrigir concordância
- Melhorar fluidez
- Remover repetições
- Manter até 80 palavras
- Não adicionar conteúdo novo

Sinopse:

{texto}
"""


# =========================
# LLM REVIEW
# =========================

def review_text(texto):

    res = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL,
            "prompt": build_prompt(texto),
            "stream": False,
            "options": {
                "temperature": 0.2,
                "num_predict": 180
            }
        },
        timeout=120
    )

    return res.json()["response"].strip()


# =========================
# SLUG NORMALIZAÇÃO
# =========================

def base_slug(text):

    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()

    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text)

    return text.strip("-")


def slug_exists(slug, book_id):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT 1 FROM books
        WHERE slug = ?
        AND id != ?
        LIMIT 1
    """, (slug, book_id))

    exists = cur.fetchone() is not None
    conn.close()

    return exists


def revise_slug(titulo, book_id):

    base = base_slug(titulo)
    slug = base
    counter = 2

    while slug_exists(slug, book_id):
        slug = f"{base}-{counter}"
        counter += 1

    return slug


# =========================
# FETCH PENDENTES
# =========================

def fetch_pending(limit):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, titulo, descricao
        FROM books
        WHERE sinopse = 1
        AND revisado = 0
        LIMIT ?
    """, (limit,))

    rows = cur.fetchall()
    conn.close()

    return rows


# =========================
# UPDATE
# =========================

def update_review(book_id, texto, slug):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        UPDATE books
        SET
            descricao_revisada = ?,
            slug = ?,
            revisado = 1
        WHERE id = ?
    """, (texto, slug, book_id))

    conn.commit()
    conn.close()


# =========================
# RUN
# =========================

def run(pacote=10):

    rows = fetch_pending(pacote)

    if not rows:
        log("Nada pendente para revisão.")
        return

    processed = 0

    for book_id, titulo, descricao in rows:

        log(f"REVISANDO → {titulo}")

        texto_revisto = review_text(descricao)

        slug_revisto = revise_slug(titulo, book_id)

        update_review(
            book_id,
            texto_revisto,
            slug_revisto
        )

        processed += 1

        log(f"REVISADO → {titulo}")

    log(f"REVISÃO CONCLUÍDA → {processed}")
