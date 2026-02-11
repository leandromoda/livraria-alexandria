import requests
import time

from core.db import get_conn
from core.logger import log

# =========================
# CONFIG
# =========================

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "phi3:mini"

MAX_RETRIES = 3


# =========================
# PROMPT
# =========================

def build_prompt(titulo, autor):

    return f"""
Escreva uma sinopse editorial curta (até 80 palavras)
para página de recomendação de livros.

Tom: informativo + persuasivo
Foco: valor do livro para o leitor
Sem spoilers
Sem citações

Livro: {titulo}
Autor: {autor}
"""


# =========================
# LLM CALL
# =========================

def generate_synopsis(titulo, autor):

    prompt = build_prompt(titulo, autor)

    for attempt in range(MAX_RETRIES):

        try:

            res = requests.post(
                OLLAMA_URL,
                json={
                    "model": MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.4,
                        "num_predict": 180
                    }
                },
                timeout=120
            )

            text = res.json()["response"].strip()

            if len(text) > 30:
                return text

        except Exception as e:
            log(f"Retry LLM ({attempt+1}) → {titulo}")
            time.sleep(2)

    return None


# =========================
# FETCH PENDENTES
# =========================

def fetch_pending(limit):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, titulo, autor
        FROM books
        WHERE sinopse = 0
        LIMIT ?
    """, (limit,))

    rows = cur.fetchall()
    conn.close()

    return rows


# =========================
# UPDATE
# =========================

def update_synopsis(book_id, text):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        UPDATE books
        SET
            descricao = ?,
            sinopse = 1
        WHERE id = ?
    """, (text, book_id))

    conn.commit()
    conn.close()


# =========================
# RUN
# =========================

def run(pacote=10):

    rows = fetch_pending(pacote)

    if not rows:
        log("Nada pendente para sinopse.")
        return

    processed = 0
    failed = 0

    for book_id, titulo, autor in rows:

        log(f"LLM → {titulo}")

        synopsis = generate_synopsis(titulo, autor)

        if not synopsis:
            failed += 1
            log(f"FALHA → {titulo}")
            continue

        update_synopsis(book_id, synopsis)

        processed += 1
        log(f"SINOPSE OK → {titulo}")

    log(
        f"SINOPSE CONCLUÍDO → {processed} | falhas {failed}"
    )
