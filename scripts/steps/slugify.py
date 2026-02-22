# ============================================
# LIVRARIA ALEXANDRIA — SLUGIFY
# Path Safe + Collision Safe
# ============================================

import re
import unicodedata

from datetime import datetime

from core.db import get_conn
from core.logger import log


# =========================
# SLUG BASE
# =========================

def base_slug(text):

    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()

    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text)

    return text.strip("-")


# =========================
# CHECK COLISÃO
# =========================

def slug_exists(slug):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        "SELECT 1 FROM livros WHERE slug = ? LIMIT 1",
        (slug,)
    )

    exists = cur.fetchone() is not None

    conn.close()

    return exists


def generate_unique_slug(titulo):

    base = base_slug(titulo)

    slug = base
    counter = 2

    while slug_exists(slug):
        slug = f"{base}-{counter}"
        counter += 1

    return slug


# =========================
# FETCH PENDENTES
# =========================

def fetch_pending(idioma, limit):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, titulo
        FROM livros
        WHERE status_slug = 0
        AND idioma = ?
        LIMIT ?
    """, (idioma, limit))

    rows = cur.fetchall()
    conn.close()

    return rows


# =========================
# UPDATE
# =========================

def update_slug(book_id, slug):

    conn = get_conn()
    cur = conn.cursor()

    now = datetime.utcnow().isoformat()

    cur.execute("""
        UPDATE livros
        SET slug = ?,
            status_slug = 1,
            updated_at = ?
        WHERE id = ?
    """, (slug, now, book_id))

    conn.commit()
    conn.close()


# =========================
# RUN
# =========================

def run(idioma, pacote=10):

    rows = fetch_pending(idioma, pacote)

    if not rows:
        log(
            f"Nada pendente para slug "
            f"no idioma [{idioma}]."
        )
        return

    processed = 0

    for book_id, titulo in rows:

        slug = generate_unique_slug(titulo)

        update_slug(book_id, slug)

        processed += 1

        log(f"SLUG → {titulo} → {slug}")

    log(
        f"SLUG CONCLUÍDO [{idioma}] → "
        f"{processed}"
    )
