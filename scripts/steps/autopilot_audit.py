# ============================================================
# AUTOPILOT AUDIT — Auditoria de integridade (sem LLM)
# Livraria Alexandria
#
# Executa checks de consistência nos dados do pipeline.
# Não usa LLM. Pode ser invocado manualmente (menu 27) ou
# automaticamente pelo autopilot quando o pipeline exaure.
#
# Formato de saída projetado para leitura por LLM:
#   [AUDIT] ⚠️  <N> <descrição> — <ação recomendada>
#   [AUDIT] ✅  <check> — OK
# ============================================================

from core.db import get_conn
from core.logger import log


# =========================
# CHECKS
# =========================

def _check(conn, descricao, query, acao_recomendada):
    """Executa um check e loga resultado."""
    cur = conn.cursor()
    cur.execute(query)
    n = cur.fetchone()[0]
    if n > 0:
        log(f"[AUDIT] ⚠️  {n} {descricao} — {acao_recomendada}")
    else:
        log(f"[AUDIT] ✅  {descricao} — OK")
    return n


def run(idioma: str = None, pacote: int = None):
    """Executa todos os checks de integridade e loga o relatório."""
    log("[AUDIT] Iniciando auditoria de integridade (sem LLM)...")

    conn = get_conn()
    alertas = 0

    # ── 1. Publicados sem supabase_id ─────────────────────────────────────────
    alertas += _check(
        conn,
        "livros com status_publish=1 mas sem supabase_id",
        """SELECT COUNT(*) FROM livros
           WHERE status_publish = 1
             AND (supabase_id IS NULL OR supabase_id = '')""",
        "rodar step 14 (Publicar Livros) novamente ou verificar erro de publicação",
    )

    # ── 2. status_cover=1 mas imagem_url vazia ────────────────────────────────
    alertas += _check(
        conn,
        "livros com status_cover=1 mas imagem_url vazia",
        """SELECT COUNT(*) FROM livros
           WHERE status_cover = 1
             AND (imagem_url IS NULL OR imagem_url = '')""",
        "resetar status_cover=0 para reprocessar: UPDATE livros SET status_cover=0 WHERE status_cover=1 AND imagem_url IS NULL",
    )

    # ── 3. Publicados sem oferta publicada (com offer_url disponível) ─────────
    alertas += _check(
        conn,
        "livros publicados com offer_url mas sem oferta no Supabase",
        """SELECT COUNT(*) FROM livros
           WHERE status_publish        = 1
             AND status_publish_oferta = 0
             AND offer_url IS NOT NULL
             AND supabase_id IS NOT NULL""",
        "rodar opção 27 (Reparar Ofertas) para republicar",
    )

    # ── 4. Publicados sem categoria temática ──────────────────────────────────
    alertas += _check(
        conn,
        "livros publicados sem categoria temática",
        """SELECT COUNT(*) FROM livros l
           WHERE l.status_publish = 1
             AND NOT EXISTS (
                 SELECT 1 FROM livros_categorias_tematicas t
                 WHERE t.livro_id = l.id
             )""",
        "rodar step 9 (Categorizar) e depois step 16 (Publicar Categorias)",
    )

    # ── 5. Autores publicados sem livros vinculados ───────────────────────────
    alertas += _check(
        conn,
        "autores publicados sem livros vinculados",
        """SELECT COUNT(*) FROM autores a
           WHERE a.status_publish = 1
             AND NOT EXISTS (
                 SELECT 1 FROM livros_autores la WHERE la.autor_id = a.id
             )""",
        "verificar registros em livros_autores ou re-publicar autores",
    )

    # ── 6. is_publishable=1 mas não publicados ────────────────────────────────
    alertas += _check(
        conn,
        "livros is_publishable=1 aguardando publicação",
        """SELECT COUNT(*) FROM livros
           WHERE is_publishable = 1
             AND status_publish = 0""",
        "rodar step 14 (Publicar Livros) — existem livros aprovados pendentes",
    )

    # ── 7. Livros sem slug com review concluído ───────────────────────────────
    alertas += _check(
        conn,
        "livros com review concluído mas sem slug",
        """SELECT COUNT(*) FROM livros
           WHERE status_review = 1
             AND (slug IS NULL OR slug = '')""",
        "rodar step 5 (Gerar Slugs)",
    )

    # ── 8. Sinopses muito curtas (abaixo do mínimo do quality gate) ───────────
    alertas += _check(
        conn,
        "livros com sinopse abaixo de 400 chars (falharão no quality gate)",
        """SELECT COUNT(*) FROM livros
           WHERE status_synopsis = 1
             AND sinopse IS NOT NULL
             AND length(sinopse) < 400""",
        "rodar step 11 (Sinopses) novamente para regenerar ou usar length_enforcer",
    )

    conn.close()

    log("=" * 52)
    if alertas == 0:
        log("[AUDIT] ✅  Nenhuma inconsistência encontrada. Pipeline íntegro.")
    else:
        log(f"[AUDIT] ⚠️  {alertas} checks com problemas — revisar ações recomendadas acima.")
    log("=" * 52)
