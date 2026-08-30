# ============================================================
# STEP 31 — MIGRAR OFERTAS DA AMAZON PARA O ML
# Livraria Alexandria
#
# Rerroteia livros PUBLICADOS cuja `offer_url` ainda aponta para a Amazon,
# mas SÓ quando a API de catálogo do ML confirma o produto.
# ============================================================
#
# Por que este step existe
# ------------------------
# O `offer_resolver` passou a rotear sempre para o ML em 2026-08-29 (#305), mas
# só para livro NOVO: `fetch_pending` filtra `offer_url IS NULL`. Quem já tinha
# sido resolvido antes ficou na Amazon, e só migraria se o monitor de preços o
# visitasse E a origem falhasse. Medido no `books.db` em 2026-08-30:
#
#   publicados                                  4.860
#   com offer_url da Amazon                     2.486
#     └ URL de BUSCA e sem preço                2.265  (91%)
#     └ com preco_atual                           203
#     └ com deep link /dp/                         27
#     └ com deep link E preço (oferta que funciona)  9
#
# Os 2.265 são link de busca sem preço — o perfil de *thin affiliate* que o
# diagnóstico do spam update de agosto apontou. Migrá-los ataca exatamente esse
# passivo **sem criar uma única página nova**, ao contrário de quase tudo mais
# que aumenta publicação.
#
# ⚠ POR QUE SÓ MIGRA COM CONFIRMAÇÃO DA API (degrau 1, nunca o degrau 2)
# ----------------------------------------------------------------------
# O `resolve_offer` tem três degraus e, para seed NOVO, cair no degrau 2 (URL de
# busca do ML) é correto: não há nada a perder. Aqui há. Ficou registrado na
# TASK-OFERTAS-007 que trocar busca da Amazon por busca do ML "é neutro" — e
# **não é**, por dois motivos que este step evita:
#
#  1. Se o livro não está no catálogo do ML, troca-se uma busca que acha por uma
#     busca vazia. Isso é pior que o estado atual, não neutro.
#  2. Pior: `offer_resolver.update_offer` faz `preco_atual = COALESCE(?,
#     preco_atual)`. Com a API não confirmando, `preco` vem `None` e o preço
#     antigo **da Amazon sobrevive colado numa URL do ML** — preço de um
#     marketplace exibido como se fosse do outro, nos 203 livros com preço.
#
# Por isso: confirmou → migra com deep link E preço juntos; não confirmou →
# **não toca em nada**, só carimba a data da tentativa.
#
# ⚠ A FILA NÃO PODE VIRAR LAÇO
# ----------------------------
# Livro que a API não confirma continua elegível — o catálogo do ML muda, e
# bloquear para sempre seria errado. Mas reconsultá-lo a cada ciclo repetiria o
# laço de categorização corrigido no #307 (547 rejeições para 32 livros, 40% de
# cada lote). A trava é `ml_migracao_em`: a fila serve **nunca-tentados
# primeiro** e, depois, os de tentativa mais antiga. Mesmo padrão do
# `preco_updated_at` no `offer_price_monitor.fetch_pending`.

import os

from core.db import get_conn
from core.logger import log

# Cota por passe do G. Cada livro custa ~1-2 s (uma chamada à API do ML), então
# 150 fica na mesma ordem de grandeza do PRECO_POR_CICLO e não estica o passe.
# `0` desliga.
MIGRAR_ML_POR_CICLO = int(os.getenv("MIGRAR_ML_POR_CICLO", "150"))

# Padrão de URL da Amazon que indica oferta JÁ BOA: deep link de produto.
# Combinado com preço, é oferta que funciona — não se mexe.
_DEEP_LINK_AMZ = "%/dp/%"


def fetch_pending(conn, limit):
    """Publicados na Amazon que valem a tentativa, nunca-tentados primeiro.

    Exclui deliberadamente quem já tem deep link `/dp/` **e** `preco_atual`:
    são 9 livros (medido 2026-08-30) com oferta que funciona, e trocar o
    marketplace deles seria regressão, não migração.
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, titulo, autor, isbn, offer_url, preco_atual, supabase_id
        FROM livros
        WHERE status_publish = 1
          AND LOWER(COALESCE(offer_url, '')) LIKE '%amazon%'
          AND NOT (offer_url LIKE ? AND preco_atual IS NOT NULL)
        ORDER BY (ml_migracao_em IS NOT NULL), ml_migracao_em ASC, titulo ASC
        LIMIT ?
        """,
        (_DEEP_LINK_AMZ, limit),
    )
    return cur.fetchall()


def _carimbar(conn, livro_id):
    """Registra a tentativa sem tocar na oferta — o anti-laço da fila."""
    conn.execute(
        "UPDATE livros SET ml_migracao_em = CURRENT_TIMESTAMP WHERE id = ?",
        (livro_id,),
    )
    conn.commit()


def _migrar(conn, livro_id, url_ml, preco):
    """Troca a oferta e reabre a republicação no Supabase.

    `status_publish_oferta = 0` é o que faz o `publish_ofertas.run_repair()` do
    MESMO passe do G reenviar: o `_payload_hash` já inclui `url_afiliada` e
    `preco`, então a mudança se propaga sozinha. Sem esse reset, o site ficaria
    com o link antigo até alguém forçar.
    """
    conn.execute(
        """
        UPDATE livros
        SET offer_url             = ?,
            marketplace           = 'mercado_livre',
            preco_atual           = ?,
            preco_updated_at      = CURRENT_TIMESTAMP,
            offer_status          = 1,
            status_publish_oferta = 0,
            ml_migracao_em        = CURRENT_TIMESTAMP,
            updated_at            = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (url_ml, preco, livro_id),
    )
    conn.commit()


def run(limit=None, dry_run=False):
    """Retorna (migrados, nao_confirmados, erros). Log agregado, nunca por item."""
    limit = MIGRAR_ML_POR_CICLO if limit is None else limit
    if limit <= 0:
        return 0, 0, 0

    try:
        from core import ml_api
    except Exception as e:
        log(f"[MIGRA_ML] Módulo ml_api indisponível ({e}) — nada a fazer.")
        return 0, 0, 0

    if not ml_api.configurado():
        log("[MIGRA_ML] Sem ML_CLIENT_ID/ML_CLIENT_SECRET — pulando.")
        return 0, 0, 0

    from steps.offer_resolver import inject_ml_affiliate

    conn = get_conn()
    rows = fetch_pending(conn, limit)

    if not rows:
        log("[MIGRA_ML] Nenhum livro publicado na Amazon elegível.")
        conn.close()
        return 0, 0, 0

    restantes = conn.execute(
        """
        SELECT COUNT(*) FROM livros
        WHERE status_publish = 1
          AND LOWER(COALESCE(offer_url, '')) LIKE '%amazon%'
          AND NOT (offer_url LIKE ? AND preco_atual IS NOT NULL)
        """,
        (_DEEP_LINK_AMZ,),
    ).fetchone()[0]

    log(f"[MIGRA_ML] {len(rows)} livro(s) neste passe | {restantes} no passivo "
        f"| dry_run={dry_run}")

    migrados = nao_conf = erros = 0

    for row in rows:
        livro_id = row["id"]
        try:
            achado = ml_api.buscar_livro(row["titulo"], row["autor"], row["isbn"])
        except Exception as e:
            # Falha de rede/API não pode carimbar: o livro não foi realmente
            # avaliado, e carimbar o mandaria para o fim da fila à toa.
            log(f"[MIGRA_ML] ERRO na API → {row['titulo']} | {e}")
            erros += 1
            continue

        if not achado:
            # O portão de duas folhas (autor E título) reprovou. Não é erro —
            # é a API funcionando. Só carimba e segue.
            nao_conf += 1
            if not dry_run:
                _carimbar(conn, livro_id)
            continue

        if not dry_run:
            _migrar(conn, livro_id, inject_ml_affiliate(achado["url"]),
                    float(achado["preco"]))
        migrados += 1

    conn.close()

    log(f"[MIGRA_ML] Migrados: {migrados} | Não confirmados: {nao_conf} | "
        f"Erros: {erros} | Total: {len(rows)}")
    if dry_run:
        log("[MIGRA_ML] dry-run ativo — nenhuma alteração foi salva.")

    return migrados, nao_conf, erros
