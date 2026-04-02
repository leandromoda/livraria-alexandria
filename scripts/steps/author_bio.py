# ============================================================
# STEP — AUTHOR BIO
# Livraria Alexandria
#
# Gera bio curta (2-3 frases, máx 300 chars) para autores
# sem descricao, usando LLM (Gemini via markdown_executor).
#
# Fallback determinístico se LLM falhar:
#   "Autor(a) de {N} livros disponíveis na Livraria Alexandria."
#
# Depende de: autores com descricao IS NULL
# Grava em:   autores.descricao
# ============================================================

import time

from core.db import get_conn
from core.logger import log
from core.markdown_executor import _call_llm


# =========================
# CONFIG
# =========================

MAX_BIO_CHARS = 300
DELAY_ENTRE_REQUESTS = 0.5   # segundos (respeita tier Gemini)


# =========================
# FETCH
# =========================

def fetch_pendentes(conn, pacote: int) -> list:
    """Retorna autores sem bio, com lista de títulos de seus livros."""
    cur = conn.cursor()
    cur.execute("""
        SELECT
            a.id,
            a.nome,
            a.nacionalidade,
            GROUP_CONCAT(l.titulo, ' | ') AS titulos
        FROM autores a
        LEFT JOIN livros_autores la ON la.autor_id = a.id
        LEFT JOIN livros l ON l.id = la.livro_id
        WHERE a.descricao IS NULL
        GROUP BY a.id
        LIMIT ?
    """, (pacote,))
    return cur.fetchall()


# =========================
# BIO GERADA
# =========================

def gerar_bio_llm(nome: str, nacionalidade: str | None, titulos: str | None) -> str | None:
    """Chama LLM para gerar bio de 2-3 frases sobre o autor."""
    lista_titulos = ""
    if titulos:
        lista = [t.strip() for t in titulos.split("|") if t.strip()][:5]
        lista_titulos = ", ".join(f'"{t}"' for t in lista)

    contexto_nac = f", {nacionalidade}" if nacionalidade else ""

    prompt = (
        f"Escreva uma bio concisa de 2 a 3 frases sobre o(a) autor(a) {nome}{contexto_nac}. "
        f"{'Obras conhecidas: ' + lista_titulos + '. ' if lista_titulos else ''}"
        "A bio deve ser factual, em português do Brasil, sem adjetivos excessivos. "
        "Responda APENAS com a bio, sem introdução, sem aspas, sem markdown."
    )

    try:
        resultado = _call_llm(prompt).strip()
        # Trunca se necessário
        if len(resultado) > MAX_BIO_CHARS:
            resultado = resultado[:MAX_BIO_CHARS].rsplit(" ", 1)[0] + "."
        return resultado if resultado else None
    except Exception as e:
        log(f"[AUTHOR_BIO] LLM falhou: {type(e).__name__}: {e}")
        return None


def gerar_bio_fallback(nome: str, n_livros: int) -> str:
    """Bio determinística para quando o LLM falha."""
    return (
        f"Autor(a) de {n_livros} {'livro' if n_livros == 1 else 'livros'} "
        f"disponíveis na Livraria Alexandria."
    )


# =========================
# UPDATE
# =========================

def update_descricao(conn, autor_id: str, descricao: str):
    cur = conn.cursor()
    cur.execute("""
        UPDATE autores
        SET descricao  = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (descricao, autor_id))
    conn.commit()


# =========================
# RUN
# =========================

def run(idioma: str = None, pacote: int = 20):
    log("[AUTHOR_BIO] Iniciando geração de bios de autores...")

    conn = get_conn()
    rows = fetch_pendentes(conn, pacote)

    if not rows:
        log("[AUTHOR_BIO] Nenhum autor pendente.")
        conn.close()
        return

    total = len(rows)
    ok = 0
    fallbacks = 0
    falhas = 0

    for i, (autor_id, nome, nacionalidade, titulos) in enumerate(rows, 1):
        log(f"[AUTHOR_BIO][{i}/{total}] → {nome}")

        n_livros = len(titulos.split("|")) if titulos else 0
        bio = gerar_bio_llm(nome, nacionalidade, titulos)

        if bio:
            update_descricao(conn, autor_id, bio)
            log(f"[AUTHOR_BIO] OK → {nome}")
            ok += 1
        else:
            bio_fb = gerar_bio_fallback(nome, n_livros)
            update_descricao(conn, autor_id, bio_fb)
            log(f"[AUTHOR_BIO] FALLBACK → {nome}")
            fallbacks += 1

        if i < total:
            time.sleep(DELAY_ENTRE_REQUESTS)

    conn.close()
    log(f"[AUTHOR_BIO] Finalizado")
    log(f"OK (LLM): {ok} | Fallback: {fallbacks} | Falhas: {falhas} | Total: {total}")
