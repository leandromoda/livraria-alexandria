# ============================================================
# FIX AFFILIATE URLs
# Livraria Alexandria
#
# Corrige offer_url no SQLite local para garantir que todas
# as URLs de marketplace contenham parâmetros de afiliado.
#
# - Mercado Livre: matt_word + matt_tool
# - Amazon: tag=livrariaalexa-20
# ============================================================

from core.db import get_conn
from core.logger import log
from steps.offer_resolver import inject_ml_affiliate, inject_amazon_tag


def run():

    log("Iniciando Fix Affiliate URLs...")

    conn = get_conn()
    cur = conn.cursor()

    # IDs cujas offer_url foram efetivamente alteradas — só estes precisam
    # ser marcados para republicação. Resetar ofertas inalteradas desativaria
    # as afiliadas no site sem motivo (e forçaria republicação total à toa).
    changed_ids = []

    # --- Mercado Livre ---
    cur.execute("""
        SELECT id, offer_url FROM livros
        WHERE offer_url LIKE '%mercadolivre.com%'
          AND offer_url NOT LIKE '%matt_tool%'
    """)
    ml_rows = cur.fetchall()

    ml_fixed = 0
    for book_id, url in ml_rows:
        new_url = inject_ml_affiliate(url)
        if new_url != url:
            cur.execute(
                "UPDATE livros SET offer_url = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (new_url, book_id),
            )
            changed_ids.append(book_id)
            ml_fixed += 1

    conn.commit()
    log(f"[ML] {ml_fixed} URLs corrigidas (de {len(ml_rows)} sem matt_tool)")

    # --- Amazon ---
    cur.execute("""
        SELECT id, offer_url FROM livros
        WHERE offer_url LIKE '%amazon.com.br%'
          AND offer_url NOT LIKE '%tag=%'
    """)
    amz_rows = cur.fetchall()

    amz_fixed = 0
    for book_id, url in amz_rows:
        new_url = inject_amazon_tag(url)
        if new_url != url:
            cur.execute(
                "UPDATE livros SET offer_url = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (new_url, book_id),
            )
            changed_ids.append(book_id)
            amz_fixed += 1

    conn.commit()
    log(f"[AMZ] {amz_fixed} URLs corrigidas (de {len(amz_rows)} sem tag)")

    # --- Reset publish flag SOMENTE para as ofertas cujas URLs mudaram ---
    # Se nada foi corrigido (changed_ids vazio), este passo é no-op: não
    # desativa nenhuma oferta já publicada no Supabase.
    resetados = 0
    CHUNK = 500  # respeita o limite de variáveis por query do SQLite
    for i in range(0, len(changed_ids), CHUNK):
        chunk = changed_ids[i:i + CHUNK]
        placeholders = ",".join("?" * len(chunk))
        cur.execute(
            f"""
            UPDATE livros
            SET status_publish_oferta = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE id IN ({placeholders})
              AND status_publish = 1
              AND offer_url IS NOT NULL
              AND supabase_id IS NOT NULL
              AND status_publish_oferta = 1
            """,
            chunk,
        )
        resetados += cur.rowcount
    conn.commit()

    conn.close()

    log(f"[RESET] {resetados} ofertas marcadas para republicação no Supabase")
    log(f"Fix Affiliate URLs finalizado. Total corrigido: ML={ml_fixed}, AMZ={amz_fixed}")
    log("Rode o step 15 (Publicar Ofertas) para atualizar o Supabase.")
