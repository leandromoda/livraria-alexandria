import requests
import uuid
import re
import unicodedata
import time
import threading
from datetime import datetime

# =========================
# CONFIG
# =========================

SUPABASE_URL = "https://ncnexkuiiuzwujqurtsa.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5jbmV4a3VpaXV6d3VqcXVydHNhIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2OTU0MTY2MCwiZXhwIjoyMDg1MTE3NjYwfQ.CacLDlVd0noDzcuVJnxjx3eMr7SjI_19rAsDZeQh6S8"

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}

OPENLIBRARY_URL = "https://openlibrary.org/search.json"
OLLAMA_URL = "http://localhost:11434/api/generate"

MODEL = "phi3:mini"

QUERY = "finance"
LIMIT = 20

last_activity = time.time()


# =========================
# LOGGER
# =========================

def log(msg):

    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {msg}")


# =========================
# HEARTBEAT
# =========================

def heartbeat():

    while True:

        elapsed = int(time.time() - last_activity)

        log(
            f"Script ativo… último evento há {elapsed}s"
        )

        time.sleep(30)


threading.Thread(
    target=heartbeat,
    daemon=True
).start()


# =========================
# SLUG
# =========================

def slugify(text):

    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text)
    text = text.strip("-")

    return text


# =========================
# FETCH
# =========================

def fetch_books():

    global last_activity

    log("Buscando livros OpenLibrary…")

    params = {
        "q": QUERY,
        "limit": LIMIT
    }

    res = requests.get(
        OPENLIBRARY_URL,
        params=params
    )

    data = res.json()

    docs = data.get("docs", [])

    log(f"Resultados encontrados: {len(docs)}")

    last_activity = time.time()

    return docs


# =========================
# LLM
# =========================

def generate_synopsis(title, author):

    global last_activity

    log(f"LLM → Gerando sinopse: {title}")

    prompt = f"""
Sinopse curta (até 60 palavras):

{title} — {author}
"""

    res = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_predict": 120,
                "temperature": 0.4
            }
        }
    )

    last_activity = time.time()

    return res.json()["response"].strip()


# =========================
# INSERT
# =========================

def insert_book(payload):

    global last_activity

    url = f"{SUPABASE_URL}/rest/v1/livros"

    requests.post(
        url,
        headers=HEADERS,
        json=payload
    )

    log(f"DB → Inserido: {payload['titulo']}")

    last_activity = time.time()


# =========================
# PIPELINE
# =========================

def run():

    books = fetch_books()

    total = len(books)

    log(f"Iniciando ingest de {total} livros")

    for i, b in enumerate(books, start=1):

        titulo = b.get("title")
        autores = ", ".join(
            b.get("author_name", [])
        )

        if not titulo:
            continue

        log(f"PROGRESS {i}/{total} → {titulo}")

        descricao = generate_synopsis(
            titulo,
            autores
        )

        payload = {
            "id": str(uuid.uuid4()),
            "titulo": titulo,
            "slug": slugify(titulo),
            "autor": autores,
            "descricao": descricao
        }

        insert_book(payload)

    log("Ingest concluído.")


# =========================
# RUN
# =========================

if __name__ == "__main__":
    run()