# ============================================================
# STEP — SLUGIFY AUTORES
# Livraria Alexandria
# ============================================================
# Extrai autores únicos da tabela livros, gera slugs,
# popula autores e livros_autores no SQLite local.
# ============================================================

import os
import re
import unicodedata
import uuid
from datetime import datetime


def _nfc(s: str) -> str:
    """Normaliza para NFC — garante forma canônica composta do Unicode."""
    return unicodedata.normalize("NFC", s)

from core.db import get_conn


# =========================
# LOGGER
# =========================

def log(msg):
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {msg}")


# =========================
# SLUG
# =========================

def base_slug(text):

    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text)

    return text.strip("-")


def slug_exists(conn, slug):

    cur = conn.cursor()
    cur.execute("SELECT 1 FROM autores WHERE slug = ? LIMIT 1", (slug,))
    return cur.fetchone() is not None


def generate_unique_slug(conn, nome):

    base = base_slug(nome)
    slug = base
    counter = 2

    while slug_exists(conn, slug):
        slug = f"{base}-{counter}"
        counter += 1

    return slug


# =========================
# FETCH
# =========================

def fetch_livros_com_autor(conn):
    """Retorna todos os livros com campo autor preenchido."""

    cur = conn.cursor()

    cur.execute("""
        SELECT id, autor
        FROM livros
        WHERE autor IS NOT NULL
          AND trim(autor) != ''
    """)

    return cur.fetchall()


def get_autor_by_nome(conn, nome):

    cur = conn.cursor()
    cur.execute("SELECT id FROM autores WHERE nome = ? LIMIT 1", (nome,))
    return cur.fetchone()


def relacao_exists(conn, livro_id, autor_id):

    cur = conn.cursor()
    cur.execute("""
        SELECT 1 FROM livros_autores
        WHERE livro_id = ? AND autor_id = ?
        LIMIT 1
    """, (livro_id, autor_id))
    return cur.fetchone() is not None


# =========================
# INSERT
# =========================

def insert_autor(conn, nome, slug):

    autor_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    conn.execute("""
        INSERT INTO autores (id, nome, slug, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
    """, (autor_id, nome, slug, now, now))

    return autor_id


def insert_relacao(conn, livro_id, autor_id):

    now = datetime.utcnow().isoformat()

    conn.execute("""
        INSERT OR IGNORE INTO livros_autores (livro_id, autor_id, created_at)
        VALUES (?, ?, ?)
    """, (livro_id, autor_id, now))


# =========================
# RUN
# =========================

def run():

    conn = get_conn()

    rows = fetch_livros_com_autor(conn)

    if not rows:
        log("Nenhum livro com autor encontrado.")
        conn.close()
        return

    autores_criados = 0
    relacoes_criadas = 0
    total = len(rows)

    for i, row in enumerate(rows, start=1):

        livro_id = row["id"]
        autor_raw = row["autor"].strip()
        log(f"[SLUG_AUTORES][{i:03d}/{total:03d}] → {autor_raw}")

        # Suporte a múltiplos autores separados por ";"
        nomes = [n.strip() for n in autor_raw.split(";") if n.strip()]

        for nome in nomes:

            nome = _nfc(nome)  # normaliza antes de inserir ou buscar
            existing = get_autor_by_nome(conn, nome)

            if existing:
                autor_id = existing["id"]
            else:
                slug = generate_unique_slug(conn, nome)
                autor_id = insert_autor(conn, nome, slug)
                autores_criados += 1
                log(f"AUTOR → {nome} → {slug}")

            if not relacao_exists(conn, livro_id, autor_id):
                insert_relacao(conn, livro_id, autor_id)
                relacoes_criadas += 1

    conn.close()

    log(f"[SLUG_AUTORES] Finalizado | Autores criados: {autores_criados} | Relações criadas: {relacoes_criadas}")


if __name__ == "__main__":
    run()
