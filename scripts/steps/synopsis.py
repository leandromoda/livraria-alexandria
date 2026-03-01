import time

from core.db import get_conn
from core.logger import log
from core.markdown_executor import execute_agent


# =====================================================
# CONFIG
# =====================================================

AGENT_PATH = "agents/synopsis"


# =====================================================
# HELPERS
# =====================================================

def fetch_pending(conn, idioma, limit):

    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, titulo, autor, idioma
        FROM livros
        WHERE status_synopsis = 0
          AND idioma = ?
          AND is_book = 1
        LIMIT ?
        """,
        (idioma, limit),
    )

    return cur.fetchall()


def update_synopsis(conn, livro_id, synopsis):

    cur = conn.cursor()

    cur.execute(
        """
        UPDATE livros
        SET descricao = ?,
            status_synopsis = 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (synopsis, livro_id),
    )

    conn.commit()


# =====================================================
# MAIN STEP
# =====================================================

def run(idioma, pacote):
    """
    Step: geração de sinopses via Markdown Agent
    Compatível com main.py → synopsis.run(idioma, pacote)
    """

    log("[SYNOPSIS] Iniciando geração de sinopses")

    conn = get_conn()

    rows = fetch_pending(conn, idioma, pacote)

    if not rows:
        log("[SYNOPSIS] Nada pendente.")
        return

    total = len(rows)

    log(f"[SYNOPSIS] {total} livros encontrados")

    start_time = time.time()

    for i, (livro_id, titulo, autor, idioma_livro) in enumerate(rows, start=1):

        heartbeat = int(time.time() - start_time)

        log(
            f"[SYNOPSIS][{i}/{total}] "
            f"{titulo} — heartbeat {heartbeat}s"
        )

        payload = {
            "titulo": titulo,
            "autor": autor,
            "idioma": idioma_livro,
        }

        result = execute_agent(AGENT_PATH, payload)

        synopsis_text = result.get("synopsis", "")

        # =====================================================
        # NOVO LOG — TRANSCRIÇÃO DA SINOPSE GERADA
        # =====================================================
        if synopsis_text:
            log("[SYNOPSIS][TEXT_BEGIN]")
            log(synopsis_text)
            log("[SYNOPSIS][TEXT_END]")

        # =====================================================

        if synopsis_text:
            update_synopsis(conn, livro_id, synopsis_text)
            log(f"[SYNOPSIS] OK → {titulo}")
        else:
            log(f"[SYNOPSIS] Falha → {titulo}")

    conn.close()

    log("[SYNOPSIS] Finalizado")