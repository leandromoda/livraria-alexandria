# ============================================================
# STEP 18 — CATEGORIZE
# Livraria Alexandria
#
# Classifica cada livro em até 5 categorias temáticas da
# taxonomy.json usando LLM (Gemini ou Ollama).
#
# Insere resultados em livros_categorias_tematicas.
# Seta status_categorize=1 após classificação.
#
# Progresso: [CATEGORIZE][NNN/TTT] → titulo
# ============================================================

import json
import os

from datetime import datetime
from core.db import get_conn
from core.logger import log
from core.markdown_executor import _call_llm as call_llm


# =========================
# CONFIG
# =========================

BASE_DIR     = os.path.dirname(os.path.dirname(__file__))
TAXONOMY_PATH = os.path.join(BASE_DIR, "data", "taxonomy.json")

MAX_CATEGORIES = 5


# =========================
# LOAD TAXONOMY
# =========================

def load_taxonomy():
    with open(TAXONOMY_PATH, "r", encoding="utf-8") as f:
        items = json.load(f)
    return {item["slug"]: item for item in items}


def taxonomy_slugs_list(taxonomy):
    return list(taxonomy.keys())


# =========================
# FETCH PENDING
# =========================

def fetch_pending(conn, pacote):
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, titulo, autor, descricao, sinopse, cluster
            FROM livros
            WHERE status_categorize = 0
              AND status_review = 1
            ORDER BY created_at ASC
            LIMIT ?
        """, (pacote,))
    except Exception:
        cur.execute("""
            SELECT id, titulo, autor, descricao, NULL as sinopse, NULL as cluster
            FROM livros
            WHERE status_categorize = 0
              AND status_review = 1
            ORDER BY created_at ASC
            LIMIT ?
        """, (pacote,))
    return cur.fetchall()


# =========================
# BUILD PROMPT
# =========================

SYSTEM_PROMPT = """Você é um classificador bibliográfico especializado.
Dado um livro (título, autor, descrição), você retorna uma lista JSON de slugs de categorias temáticas em ordem de relevância (mais relevante primeiro).
Responda APENAS com o JSON, sem explicações ou texto adicional."""


def build_prompt(titulo, autor, descricao, sinopse, slugs_list):

    texto_base = descricao or sinopse or ""
    texto_base = texto_base[:800] if len(texto_base) > 800 else texto_base

    slugs_sample = slugs_list  # taxonomia completa (~190 slugs ≈ 1.400 tokens, seguro para Gemini)

    return f"""{SYSTEM_PROMPT}

Taxonomia disponível (slugs válidos):
{json.dumps(slugs_sample, ensure_ascii=False)}

Livro:
Título: {titulo}
Autor: {autor or 'desconhecido'}
Descrição: {texto_base}

Retorne um JSON com até {MAX_CATEGORIES} slugs da taxonomia acima, em ordem de relevância:
{{"categorias": ["slug-1", "slug-2", "slug-3"]}}"""


# =========================
# PARSE LLM RESPONSE
# =========================

def parse_response(response_text, taxonomy):
    """Extrai lista de slugs válidos da resposta do LLM."""

    if not response_text:
        return []

    # Tentar extrair JSON da resposta
    try:
        # Remover markdown code blocks se presentes
        text = response_text.strip()
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        text = text.strip()

        data = json.loads(text)
        slugs = data.get("categorias", [])

    except Exception:
        # Fallback: extrair slugs com regex
        import re
        slugs = re.findall(r'"([a-z][a-z0-9\-]+)"', response_text)

    # Validar slugs contra taxonomy
    valid = []
    for slug in slugs:
        if slug in taxonomy:
            valid.append(slug)
        if len(valid) >= MAX_CATEGORIES:
            break

    return valid


# =========================
# SAVE CATEGORIES
# =========================

def save_categories(conn, livro_id, slugs):
    """Insere em livros_categorias_tematicas."""

    for i, slug in enumerate(slugs):
        primary = 1 if i == 0 else 0
        confidence = round(1.0 - i * 0.1, 1)  # 1.0, 0.9, 0.8, 0.7, 0.6

        conn.execute("""
            INSERT OR IGNORE INTO livros_categorias_tematicas
                (livro_id, categoria_slug, confidence, primary_cat, created_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (livro_id, slug, confidence, primary))

    conn.execute("""
        UPDATE livros
        SET status_categorize = 1,
            updated_at        = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (livro_id,))

    conn.commit()


# =========================
# RESET FAILED
# =========================

def reset_failed(conn=None):
    """Reseta livros com status_categorize=2 para 0 para reprocessamento."""
    close_conn = conn is None
    if conn is None:
        conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE livros
        SET status_categorize = 0,
            updated_at        = CURRENT_TIMESTAMP
        WHERE status_categorize = 2
    """)
    conn.commit()
    affected = cur.rowcount
    if close_conn:
        conn.close()
    log(f"[CATEGORIZE] reset_failed: {affected} livro(s) revertidos para status_categorize=0")
    return affected


# =========================
# RUN
# =========================

def run(idioma=None, pacote=50):

    log("Categorize iniciado…")

    taxonomy = load_taxonomy()
    slugs_list = taxonomy_slugs_list(taxonomy)

    log(f"Taxonomia carregada: {len(taxonomy)} categorias")

    conn  = get_conn()
    rows  = fetch_pending(conn, pacote)
    total = len(rows)

    if not rows:
        log("Nenhum livro pendente de classificação temática (status_categorize=0 AND status_review=1).")
        conn.close()
        return

    ok = falhas = 0

    for i, row in enumerate(rows, start=1):

        livro_id = row["id"]
        titulo   = row["titulo"]
        autor    = row["autor"]
        descricao = row["descricao"]
        sinopse  = row["sinopse"]
        cluster  = row["cluster"]

        print(f"[CATEGORIZE][{i:03d}/{total:03d}] → {titulo}")

        prompt = build_prompt(titulo, autor, descricao, sinopse, slugs_list)

        try:
            response = call_llm(prompt)
            slugs    = parse_response(response, taxonomy)

            if slugs:
                save_categories(conn, livro_id, slugs)
                log(f"[CATEGORIZE] {titulo} → {slugs}")
                ok += 1
            else:
                log(f"[CATEGORIZE] Sem categorias válidas para: {titulo}")
                # Marca como tentado para não reprocessar infinitamente
                conn.execute("""
                    UPDATE livros SET status_categorize = 2, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (livro_id,))
                conn.commit()
                falhas += 1

        except Exception as e:
            log(f"[CATEGORIZE] Erro em '{titulo}': {e}")
            falhas += 1

    conn.close()

    log(
        f"[CATEGORIZE] OK: {ok} | "
        f"Falhas: {falhas} | "
        f"Total: {total}"
    )
