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
SUPABASE_KEY = "SUA_SERVICE_ROLE_KEY"

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}

OPENLIBRARY_SEARCH_URL = "https://openlibrary.org/search.json"
OPENLIBRARY_BASE_URL = "https://openlibrary.org"
GOOGLE_BOOKS_URL = "https://www.googleapis.com/books/v1/volumes"

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "phi3:mini"

LIMIT_PER_QUERY = 10

QUERIES = [
    "finance","investing","personal finance","wealth",
    "entrepreneurship","business strategy",
    "psychology","behavioral economics",
    "decision making","habits","productivity",
    "stoicism","philosophy","ethics",
    "political philosophy","strategy",
    "biography business","entrepreneur biography",
    "leadership","management",
]

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
        log(f"Script ativo… último evento há {elapsed}s")
        time.sleep(30)

threading.Thread(target=heartbeat, daemon=True).start()

# =========================
# SLUG
# =========================

def slugify(text):
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text)
    return text.strip("-")

# =========================
# FILTRO
# =========================

EXCLUDED_TERMS = [
    "laws","law","bill","act","court",
    "audit","administration","report",
    "government","committee"
]

def is_valid_book(doc):

    title = (doc.get("title") or "").lower()
    authors = doc.get("author_name")
    edition_count = doc.get("edition_count", 0)

    if len(title) < 5:
        return False

    if not authors:
        return False

    if edition_count < 2:
        return False

    for term in EXCLUDED_TERMS:
        if term in title:
            return False

    return True

# =========================
# DEDUP CORRIGIDO
# =========================

def book_exists(slug, isbn):

    url = f"{SUPABASE_URL}/rest/v1/livros"

    # ---- slug check
    res_slug = requests.get(
        url,
        headers=HEADERS,
        params={
            "select": "id",
            "slug": f"eq.{slug}"
        }
    )

    data_slug = res_slug.json()

    if data_slug:
        log(f"SKIP slug → {slug}")
        return True

    # ---- isbn check
    if isbn:

        res_isbn = requests.get(
            url,
            headers=HEADERS,
            params={
                "select": "id",
                "isbn": f"eq.{isbn}"
            }
        )

        data_isbn = res_isbn.json()

        if data_isbn:
            log(f"SKIP isbn → {isbn}")
            return True

    return False

# =========================
# FETCH
# =========================

def fetch_by_query(query):

    log(f"QUERY → {query}")

    res = requests.get(
        OPENLIBRARY_SEARCH_URL,
        params={"q": query, "limit": LIMIT_PER_QUERY * 3}
    )

    docs = res.json().get("docs", [])

    filtered = [
        d for d in docs if is_valid_book(d)
    ][:LIMIT_PER_QUERY]

    log(f"{query} → {len(filtered)} válidos")

    return filtered

# =========================
# METADATA OL
# =========================

def enrich_openlibrary(work_key):

    if not work_key:
        return {}

    url = f"{OPENLIBRARY_BASE_URL}{work_key}/editions.json?limit=5"
    res = requests.get(url)

    if res.status_code != 200:
        return {}

    data = res.json()

    isbn = None
    year = None
    cover = None

    for ed in data.get("entries", []):

        isbn_list = ed.get("isbn_13") or ed.get("isbn_10")
        if isbn_list:
            isbn = isbn_list[0]

        if ed.get("publish_date"):
            m = re.search(r"\d{4}", ed["publish_date"])
            if m:
                year = m.group(0)

        cover_id = ed.get("covers", [None])[0]
        if cover_id:
            cover = f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg"

        if isbn and year and cover:
            break

    return {
        "isbn": isbn,
        "ano_publicacao": year,
        "imagem_url": cover,
    }

# =========================
# GOOGLE FALLBACK
# =========================

def enrich_google(title, author):

    query = f"{title} {author}"

    res = requests.get(
        GOOGLE_BOOKS_URL,
        params={"q": query, "maxResults": 1}
    )

    items = res.json().get("items")

    if not items:
        return {}

    volume = items[0]["volumeInfo"]

    isbn = None
    for ident in volume.get("industryIdentifiers", []):
        if ident["type"] in ["ISBN_13","ISBN_10"]:
            isbn = ident["identifier"]

    year = None
    if volume.get("publishedDate"):
        m = re.search(r"\d{4}", volume["publishedDate"])
        if m:
            year = m.group(0)

    cover = volume.get("imageLinks", {}).get("thumbnail")

    return {
        "isbn": isbn,
        "ano_publicacao": year,
        "imagem_url": cover,
    }

# =========================
# LLM
# =========================

def generate_synopsis(title, author):

    log(f"LLM → {title}")

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
        }
    )

    return res.json()["response"].strip()

# =========================
# INSERT
# =========================

def insert_book(payload):

    url = f"{SUPABASE_URL}/rest/v1/livros"

    requests.post(
        url,
        headers=HEADERS,
        json=payload
    )

    log(f"INSERT → {payload['titulo']}")

# =========================
# PIPELINE
# =========================

def run():

    total_inserted = 0
    total_skipped = 0

    for query in QUERIES:

        cluster_inserted = 0
        cluster_skipped = 0

        books = fetch_by_query(query)

        for b in books:

            titulo = b.get("title")
            autores = ", ".join(
                b.get("author_name", [])
            )

            metadata = enrich_openlibrary(b.get("key"))

            if not metadata.get("isbn") or not metadata.get("imagem_url"):
                g_meta = enrich_google(titulo, autores)
                metadata = {**g_meta, **metadata}

            slug = slugify(titulo)
            isbn = metadata.get("isbn")

            if book_exists(slug, isbn):
                cluster_skipped += 1
                total_skipped += 1
                continue

            descricao = generate_synopsis(titulo, autores)

            payload = {
                "id": str(uuid.uuid4()),
                "titulo": titulo,
                "slug": slug,
                "autor": autores,
                "descricao": descricao,
                "isbn": isbn,
                "ano_publicacao": metadata.get("ano_publicacao"),
                "imagem_url": metadata.get("imagem_url"),
            }

            insert_book(payload)

            cluster_inserted += 1
            total_inserted += 1

        log(
            f"CLUSTER {query} → +{cluster_inserted} | skip {cluster_skipped}"
        )

    log("===== RESUMO FINAL =====")
    log(f"INSERTS → {total_inserted}")
    log(f"SKIPS → {total_skipped}")

# =========================
# RUN
# =========================

if __name__ == "__main__":
    run()
