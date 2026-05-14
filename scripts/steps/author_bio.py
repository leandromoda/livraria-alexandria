# ============================================================
# STEP 29 — AUTHOR BIO
# Livraria Alexandria
#
# Gera bio editorial (80–160 palavras) para autores sem descricao,
# usando o agente Cowork em agents/author_bio/ (Gemini via
# markdown_executor.execute_agent).
#
# Cobertura da bio: quem é o autor → escola/movimento → principais obras.
#
# Fallback determinístico se o agente falhar ou retornar bio inválida:
#   "Autor(a) de {N} livros disponíveis na Livraria Alexandria."
#
# Depende de: autores com descricao IS NULL
# Grava em:   autores.descricao
# ============================================================

import time

from core.db import get_conn
from core.logger import log
from core.markdown_executor import execute_agent


# =========================
# CONFIG
# =========================

AGENT_PATH    = "agents/author_bio"
MAX_BIO_CHARS = 900        # ~160 palavras — alinhado com R2 das rules
MAX_TITULOS   = 6          # máximo de títulos enviados ao agente
DELAY_ENTRE   = 0.5        # segundos entre requests (respeita tier Gemini)

# Marcadores que indicam bio genérica/falha do agente — rejeitada
_GENERIC_MARKERS = [
    "contexto não especificado",
    "informações insuficientes",
    "dados não fornecidos",
    "não foi possível",
    "não tenho informações",
    "autor desconhecido",
    "[input]",
    "[dados fornecidos]",
    "livraria alexandria",    # fallback interno do agente — usamos o nosso
]


# =========================
# QUALIDADE
# =========================

def _bio_valida(bio: str) -> bool:
    """Retorna False se a bio contiver marcadores de conteúdo genérico/falha."""
    bio_lower = bio.lower()
    return not any(marker in bio_lower for marker in _GENERIC_MARKERS)


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
# BIO VIA AGENTE
# =========================

def gerar_bio_agente(nome: str, nacionalidade: str | None, titulos: str | None) -> str | None:
    """Chama o agente author_bio para gerar bio editorial estruturada."""

    lista_titulos: list[str] = []
    if titulos:
        lista_titulos = [t.strip() for t in titulos.split("|") if t.strip()][:MAX_TITULOS]

    payload = {
        "nome":         nome,
        "nacionalidade": nacionalidade or "",
        "titulos":      lista_titulos,
        "idioma":       "PT",
    }

    try:
        result = execute_agent(AGENT_PATH, payload)
        bio = result.get("bio", "").strip() if result else ""

        if not bio:
            log(f"[AUTHOR_BIO] Agente retornou bio vazia → {nome}")
            return None

        # Trunca se exceder limite (não deve acontecer se o agente respeitar R2)
        if len(bio) > MAX_BIO_CHARS:
            bio = bio[:MAX_BIO_CHARS].rsplit(" ", 1)[0].rstrip(",;:") + "."

        if not _bio_valida(bio):
            log(f"[AUTHOR_BIO] Bio rejeitada (marcador genérico) → {nome}")
            return None

        return bio

    except Exception as e:
        log(f"[AUTHOR_BIO] Agente falhou: {type(e).__name__}: {e}")
        return None


# =========================
# FALLBACK DETERMINÍSTICO
# =========================

def gerar_bio_fallback(nome: str, n_livros: int) -> str:
    """Bio determinística para quando o agente falha — nunca retorna vazio."""
    qtd = f"{n_livros} {'livro' if n_livros == 1 else 'livros'}"
    return f"Autor(a) com {qtd} disponíveis no catálogo da Livraria Alexandria."


# =========================
# UPDATE
# =========================

def update_descricao(conn, autor_id: str, descricao: str) -> None:
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

def run(idioma: str = None, pacote: int = 20) -> None:
    log("[AUTHOR_BIO] Iniciando geração de bios de autores...")

    conn  = get_conn()
    rows  = fetch_pendentes(conn, pacote)

    if not rows:
        log("[AUTHOR_BIO] Nenhum autor pendente.")
        conn.close()
        return

    total     = len(rows)
    ok        = 0
    fallbacks = 0

    log(f"[AUTHOR_BIO] {total} autores encontrados")

    for i, (autor_id, nome, nacionalidade, titulos) in enumerate(rows, 1):
        log(f"[AUTHOR_BIO][{i:03d}/{total:03d}] → {nome}")

        n_livros = len(titulos.split("|")) if titulos else 0
        bio      = gerar_bio_agente(nome, nacionalidade, titulos)

        if bio:
            update_descricao(conn, autor_id, bio)
            log(f"[AUTHOR_BIO] OK → {nome} ({len(bio)} chars)")
            ok += 1
        else:
            bio_fb = gerar_bio_fallback(nome, n_livros)
            update_descricao(conn, autor_id, bio_fb)
            log(f"[AUTHOR_BIO] FALLBACK → {nome}")
            fallbacks += 1

        if i < total:
            time.sleep(DELAY_ENTRE)

    conn.close()

    log("[AUTHOR_BIO] Finalizado")
    log(f"OK (agente): {ok} | Fallback: {fallbacks} | Total: {total}")
