# ============================================================
# QA — REMEDIAÇÃO (fecha o ciclo da auditoria do site)
# Livraria Alexandria
#
# Princípio (decisão de arquitetura): NÃO há scripts paralelos.
# A remediação reusa os STEPS PADRÃO via book_ids, dando PRIORIDADE
# aos títulos com defeito — eles já têm os demais requisitos de
# publicação, falta só corrigir o fator-causa.
#
# Fila: tabela qa_remediation (livro_id, factor, status, attempts...).
# Teto anti-thrash: após MAX_ATTEMPTS sem sucesso → quarentena
# (qa_quarantine=1) para não entrar em loop despublica↔regenera.
#
# Fatia inicial: CAPA (não-LLM, fix-in-place — NÃO despublica:
# o site lê o Supabase; marcar status_publish=0 só reenfileira o
# livro para o step de publicação padrão re-fazer o upsert da capa).
# ============================================================

import re

from core.db import get_conn
from core.logger import log
from steps import covers, publish

FACTOR_CAPA = "capa"
MAX_ATTEMPTS = 3

# Cool-down de manutenção: um título cuja regeneração de sinopse foi concluída
# (status='fixed') há menos de N dias não é re-avaliado — evita re-processar
# páginas recém-reparadas. Deve casar com MAINTENANCE_WINDOW_DAYS em
# steps/auditor.py (mantido local para não acoplar este hot-path ao auditor,
# que importa requests/bs4).
MAINTENANCE_WINDOW_DAYS = 30


def enqueue_covers(conn, source_report=None) -> tuple[int, int]:
    """Enfileira (status=pending) livros publicados sem capa.

    Idempotente: o índice parcial único (livro_id, factor) impede duplicar uma
    remediação ainda aberta. Retorna (novos_enfileirados, total_detectados).
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT id FROM livros
        WHERE status_publish = 1
          AND (imagem_url IS NULL OR imagem_url = '')
          AND COALESCE(qa_quarantine, 0) = 0
    """)
    ids = [r[0] for r in cur.fetchall()]
    novos = 0
    for lid in ids:
        try:
            cur.execute("""
                INSERT INTO qa_remediation (livro_id, factor, reason, status, source_report)
                VALUES (?, ?, ?, 'pending', ?)
            """, (lid, FACTOR_CAPA, "publicado sem capa", source_report))
            novos += 1
        except Exception:
            pass  # já há remediação aberta para (livro, capa)
    conn.commit()
    return novos, len(ids)


def drain_covers(conn, limit: int = 50) -> dict:
    """Reprocessa, COM PRIORIDADE, as capas pendentes (fix-in-place)."""
    cur = conn.cursor()
    cur.execute("""
        SELECT id, livro_id FROM qa_remediation
        WHERE factor = ? AND status IN ('pending', 'reprocessing')
        ORDER BY attempts ASC, detected_at ASC
        LIMIT ?
    """, (FACTOR_CAPA, limit))
    fila = cur.fetchall()
    if not fila:
        return {"processados": 0, "corrigidos": 0, "quarentena": 0}

    rem_ids  = [r[0] for r in fila]
    book_ids = [r[1] for r in fila]

    # Reset da flag-causa → o step padrão de capas regenera. Marca a fila como
    # reprocessing e incrementa attempts (commit antes de chamar o step, que
    # abre conexão própria).
    qm = ",".join("?" * len(book_ids))
    cur.execute(f"UPDATE livros SET status_cover = 0 WHERE id IN ({qm})", tuple(book_ids))
    rm = ",".join("?" * len(rem_ids))
    cur.execute(
        f"""UPDATE qa_remediation
            SET status='reprocessing', attempts=attempts+1, last_attempt_at=CURRENT_TIMESTAMP
            WHERE id IN ({rm})""",
        tuple(rem_ids),
    )
    conn.commit()

    # Reuso dos STEPS PADRÃO, targeted nos ids (prioridade). idioma=None: o
    # alvo é explícito (book_ids), sem filtrar por idioma.
    covers.run(None, len(book_ids), book_ids=book_ids)

    # Classifica cada livro após a geração de capa:
    #   - sem capa            → nenhuma fonte achou (retry → quarentena por tentativas)
    #   - capa + passa o gate → republicável (propaga ao Supabase via publish)
    #   - capa + falha o gate → bloqueado: defeito mais profundo (is_publishable /
    #     status_synopsis). NÃO mexe em status_publish (evita estrandar) e vai p/
    #     quarentena COM MOTIVO — é caso da próxima fatia (sinopse).
    publicaveis, bloqueados, sem_capa = [], [], []
    for rem_id, lid in fila:
        row = cur.execute(
            """SELECT imagem_url, is_publishable, status_synopsis,
                      length(COALESCE(sinopse, ''))
               FROM livros WHERE id=?""", (lid,)
        ).fetchone()
        if not (row and row[0]):
            sem_capa.append((rem_id, lid))
        elif row[1] == 1 and row[2] == 1 and (row[3] or 0) >= 80:
            publicaveis.append((rem_id, lid))
        else:
            bloqueados.append((rem_id, lid))

    # Propaga ao Supabase SÓ os republicáveis. status_publish=0 reenfileira para o
    # publish padrão (upsert) — o site permanece no ar (lê o Supabase). Restaura
    # pub=1 para qualquer um que o publish não tenha levado (robustez: nunca estranda).
    if publicaveis:
        ids = [lid for _, lid in publicaveis]
        ph = ",".join("?" * len(ids))
        cur.execute(f"UPDATE livros SET status_publish=0 WHERE id IN ({ph}) AND status_publish=1", tuple(ids))
        conn.commit()
        publish.run(None, len(ids), book_ids=ids)
        cur.execute(f"UPDATE livros SET status_publish=1 WHERE id IN ({ph}) AND status_publish=0", tuple(ids))
        conn.commit()

    corrigidos = bloqueados_n = quarentena = 0

    for rem_id, lid in publicaveis:
        row = cur.execute("SELECT imagem_url, status_publish FROM livros WHERE id=?", (lid,)).fetchone()
        if row and row[0] and row[1] == 1:
            cur.execute("UPDATE qa_remediation SET status='fixed' WHERE id=?", (rem_id,))
            corrigidos += 1
        else:
            cur.execute("UPDATE qa_remediation SET status='pending' WHERE id=?", (rem_id,))

    for rem_id, lid in bloqueados:
        cur.execute(
            "UPDATE qa_remediation SET status='quarantined', reason=? WHERE id=?",
            ("capa obtida; publish bloqueado (is_publishable/status_synopsis pendente) — fatia sinopse", rem_id),
        )
        cur.execute("UPDATE livros SET qa_quarantine=1 WHERE id=?", (lid,))
        bloqueados_n += 1

    for rem_id, lid in sem_capa:
        att = cur.execute("SELECT attempts FROM qa_remediation WHERE id=?", (rem_id,)).fetchone()[0]
        if att >= MAX_ATTEMPTS:
            cur.execute(
                "UPDATE qa_remediation SET status='quarantined', reason=? WHERE id=?",
                ("sem fonte de capa após múltiplas tentativas", rem_id),
            )
            cur.execute("UPDATE livros SET qa_quarantine=1 WHERE id=?", (lid,))
            quarentena += 1
        else:
            cur.execute("UPDATE qa_remediation SET status='pending' WHERE id=?", (rem_id,))

    conn.commit()
    return {"processados": len(fila), "corrigidos": corrigidos,
            "bloqueados": bloqueados_n, "quarentena": quarentena}


def run_covers(limit: int = 50) -> dict:
    """Passe de remediação de CAPAS: enfileira + drena com prioridade."""
    conn = get_conn()
    try:
        novos, total = enqueue_covers(conn)
        log(f"[QA-REMEDIA][capa] enfileirados: {novos} (de {total} publicados sem capa)")
        res = drain_covers(conn, limit=limit)
        log(f"[QA-REMEDIA][capa] processados={res['processados']} "
            f"corrigidos={res['corrigidos']} bloqueados={res.get('bloqueados', 0)} "
            f"quarentena={res['quarentena']}")
        return res
    finally:
        conn.close()


# ============================================================
# Fatia: SINOPSE — reconcile (NÃO-LLM)
# ============================================================
#
# Caso comum revelado em produção: livro PUBLICADO com sinopse VÁLIDA mas
# status_synopsis=0 (flag fora de sincronia com o conteúdo) → is_publishable=0.
# É um defeito de DADO, não de conteúdo — não precisa de LLM. Aqui:
#   sinopse passa validate_synopsis (mesma do pipeline) → status_synopsis=1 →
#   quality_gate (recomputa is_publishable) → publish (upsert) — fix-in-place.
# Sinopse inválida/ausente NÃO é tocada (é caso de regeneração LLM, fatia futura).

FACTOR_SYNOPSIS = "synopsis"


def reconcile_synopsis(conn, limit: int = 50) -> dict:
    """Reconcilia a flag de sinopse dos publicados com status_synopsis=0 cujo
    texto JÁ é válido. Reusa validate_synopsis + quality_gate + publish padrão."""
    from steps.synopsis_import import validate_synopsis
    from steps import quality_gate

    cur = conn.cursor()
    cur.execute("""
        SELECT id, idioma, sinopse FROM livros
        WHERE status_publish = 1 AND status_synopsis = 0
        ORDER BY updated_at DESC
        LIMIT ?
    """, (limit,))
    rows = cur.fetchall()

    por_idioma: dict = {}
    validos: list = []
    invalidos = 0
    for lid, idioma, sinopse in rows:
        if validate_synopsis(sinopse or "")[0]:
            por_idioma.setdefault((idioma or "PT"), []).append(lid)
            validos.append(lid)
        else:
            invalidos += 1

    reconciliados = 0
    if validos:
        ph = ",".join("?" * len(validos))
        # Flag correta + limpa quarentena (estamos consertando) + toggle p/ QG/publish.
        # COALESCE: alguns publicados com status_synopsis=0 também têm idioma=NULL
        # (anomalia do review), o que bloquearia o gate. Default PT (catálogo é
        # 99% PT e a sinopse é PT); a checagem de idioma do próprio QG é a rede de
        # segurança — se não for PT, o gate reprova e nada é propagado com erro.
        cur.execute(f"UPDATE livros SET status_synopsis=1, qa_quarantine=0, idioma=COALESCE(idioma,'PT') WHERE id IN ({ph})", tuple(validos))
        cur.execute(f"UPDATE livros SET status_publish=0 WHERE id IN ({ph}) AND status_publish=1", tuple(validos))
        conn.commit()

        # QG por grupo de idioma → a checagem de idioma do gate fica correta.
        for idioma, ids in por_idioma.items():
            quality_gate.run(idioma_base=idioma, book_ids=ids)
        # Propaga ao Supabase (upsert) os que o QG aprovou. publish já é idioma-opcional c/ book_ids.
        publish.run(None, len(validos), book_ids=validos)
        # Robustez: restaura pub=1 p/ quem o publish não levou (ex.: reprovado no QG) — nunca estranda.
        cur.execute(f"UPDATE livros SET status_publish=1 WHERE id IN ({ph}) AND status_publish=0", tuple(validos))
        conn.commit()

        cur.execute(
            f"""SELECT COUNT(*) FROM livros
                WHERE id IN ({ph}) AND status_synopsis=1 AND is_publishable=1 AND status_publish=1""",
            tuple(validos),
        )
        reconciliados = cur.fetchone()[0]

    return {"candidatos": len(rows), "validos": len(validos),
            "reconciliados": reconciliados, "invalidos_llm": invalidos}


def run_synopsis_reconcile(limit: int = 50) -> dict:
    """Passe de reconcile de SINOPSE (não-LLM)."""
    conn = get_conn()
    try:
        res = reconcile_synopsis(conn, limit=limit)
        log(f"[QA-REMEDIA][sinopse-reconcile] candidatos={res['candidatos']} "
            f"válidos={res['validos']} reconciliados={res['reconciliados']} "
            f"inválidos→LLM={res['invalidos_llm']}")
        return res
    finally:
        conn.close()


# ============================================================
# Fatia: SINOPSE — regeneração (GATILHO não-LLM)
# ============================================================
#
# Caso: publicado com status_synopsis=1 (o pipeline considera "pronto") mas o
# TEXTO falha validate_synopsis (placeholder/marcador genérico/heading markdown/
# muito curta). É "concluído mas ruim". Aqui só DETECTAMOS e RESETAMOS
# status_synopsis=0 — a GERAÇÃO em si é feita pelo motor LLM padrão (O/G),
# que reprocessa os status_synopsis=0. Anti-thrash: após MAX_ATTEMPTS
# regenerações sem ficar válido → quarentena (para o loop).
#
# Roda no G (que tem a fase LLM logo a seguir), NÃO no A (não-LLM: marcar
# pendências sem regenerar só inflaria o count_pending do autopilot).

FACTOR_SYNOPSIS_REGEN = "synopsis_regen"


def flag_synopsis_for_regen(conn, limit: int = 500) -> dict:
    """Marca (status_synopsis=0) publicados cuja sinopse está concluída mas
    inválida, para o motor LLM padrão regenerar. Anti-thrash via quarentena."""
    from steps.synopsis_import import validate_synopsis
    cur = conn.cursor()

    # 1. Fecha pendências já resolvidas (regeneração produziu sinopse válida).
    cur.execute(
        "SELECT id, livro_id FROM qa_remediation WHERE factor=? AND status IN ('pending','reprocessing')",
        (FACTOR_SYNOPSIS_REGEN,),
    )
    for rid, lid in cur.fetchall():
        r = cur.execute("SELECT status_synopsis, sinopse FROM livros WHERE id=?", (lid,)).fetchone()
        if r and r[0] == 1 and validate_synopsis(r[1] or "")[0]:
            # Carimba last_attempt_at ao confirmar o fix → relógio do cool-down
            # (passo 2) fica sempre correto, mesmo p/ quem foi corrigido de 1ª.
            cur.execute(
                "UPDATE qa_remediation SET status='fixed', last_attempt_at=CURRENT_TIMESTAMP WHERE id=?",
                (rid,),
            )
    conn.commit()

    # 2. Detecta "concluído mas inválido" → reseta p/ regeneração.
    #    ORDER BY RANDOM(): sem ordem fixa a mesma janela LIMIT era re-varrida a
    #    cada passe (rowid), nunca alcançando o resto do catálogo. RANDOM faz a
    #    varredura rotacionar e, ao longo de vários passes, cobrir todos os livros.
    cur.execute("""
        SELECT id, sinopse FROM livros
        WHERE status_publish=1 AND status_synopsis=1 AND COALESCE(qa_quarantine,0)=0
        ORDER BY RANDOM()
        LIMIT ?
    """, (limit,))
    flagged = quarentena = 0
    for lid, sin in cur.fetchall():
        ok, motivo = validate_synopsis(sin or "")
        if ok:
            continue

        # Cool-down: pula quem teve regeneração concluída (fixed) há menos de
        # MAINTENANCE_WINDOW_DAYS — não re-processa títulos recém-reparados.
        recente = cur.execute(
            """SELECT 1 FROM qa_remediation
               WHERE livro_id=? AND factor=? AND status='fixed'
                 AND last_attempt_at >= datetime('now', ?)""",
            (lid, FACTOR_SYNOPSIS_REGEN, f"-{MAINTENANCE_WINDOW_DAYS} days"),
        ).fetchone()
        if recente:
            continue
        rowq = cur.execute(
            "SELECT id, attempts FROM qa_remediation WHERE livro_id=? AND factor=? AND status IN ('pending','reprocessing')",
            (lid, FACTOR_SYNOPSIS_REGEN),
        ).fetchone()
        if rowq:
            rid, att = rowq[0], rowq[1] + 1
            if att > MAX_ATTEMPTS:
                cur.execute(
                    "UPDATE qa_remediation SET status='quarantined', attempts=?, reason=? WHERE id=?",
                    (att, f"sinopse inválida após {att} regenerações: {motivo}", rid),
                )
                cur.execute("UPDATE livros SET qa_quarantine=1 WHERE id=?", (lid,))
                quarentena += 1
                continue
            cur.execute(
                "UPDATE qa_remediation SET attempts=?, last_attempt_at=CURRENT_TIMESTAMP WHERE id=?",
                (att, rid),
            )
        else:
            cur.execute(
                "INSERT INTO qa_remediation (livro_id, factor, reason, status, attempts) VALUES (?, ?, ?, 'pending', 1)",
                (lid, FACTOR_SYNOPSIS_REGEN, motivo),
            )
        cur.execute("UPDATE livros SET status_synopsis=0 WHERE id=?", (lid,))  # → regeneração LLM
        flagged += 1
    conn.commit()
    return {"flagged": flagged, "quarentena": quarentena}


def run_synopsis_regen(limit: int = 500) -> dict:
    """Gatilho de regeneração de SINOPSE (não-LLM): marca as ruins p/ o motor
    LLM padrão (O/G) regenerar. Pensado p/ rodar no G, antes da fase LLM."""
    conn = get_conn()
    try:
        res = flag_synopsis_for_regen(conn, limit=limit)
        log(f"[QA-REMEDIA][sinopse-regen] marcadas p/ regeneração={res['flagged']} "
            f"quarentena={res['quarentena']}")
        return res
    finally:
        conn.close()


# ============================================================
# P1 → FILA: ingestão dos relatórios de auditoria → qa_remediation
# ============================================================
#
# Liga os relatórios NNNN_audit_<mode>.json (P1) à fila de remediação: cada
# achado per-livro vira uma linha qa_remediation(livro_id, factor, source_report,
# pending). Generaliza o ENQUEUE para todos os fatores — os drains específicos
# (capa, sinopse, e os futuros categoria/oferta/bio) consomem a fila.
#
# Idempotente: pula relatórios já ingeridos (source_report presente) e o índice
# parcial único impede duplicar remediação aberta. NÃO move os arquivos —
# o comando /audit segue responsável por arquivar (correções de código).

# mode → [(chave_lista_no_relatório, factor)]  — só listas de LIVRO baseadas em
# SLUG (a fila é keyed por livro_id). author_bio fica de fora: é remediação de
# AUTOR (tabela autores), fatia separada — não cabe aqui.
_REPORT_FACTORS = {
    "covers":         [("publicados_sem_capa", "capa"), ("capas_mortas", "capa")],
    "classification": [("publicados_sem_categoria", "categoria"),
                       ("sem_categoria_primaria", "categoria")],
    "content":        [("results", "synopsis_regen")],          # filtra severity medium|high
    "consistency":    [("livros_sem_oferta", "oferta"),
                       ("sinopses_suspeitas", "synopsis_regen")],
    "prices":         [("results", "oferta")],                  # filtra status != active
}

# NNNN_audit_<mode>.json — captura o NNNN e o modo (que pode ter '_': author_bio,
# title_verify). Usado pela poda/arquivamento de data/logs/.
_REPORT_RE = re.compile(r"^(\d{4})_audit_(.+)\.json$")


def ingest_audit_reports(conn, logs_dir: str = None) -> dict:
    """Enfileira remediações a partir dos relatórios NNNN_audit_<mode>.json."""
    import glob
    import os
    import json
    from core.audit_report import REPORT_DIR

    logs_dir = logs_dir or str(REPORT_DIR)
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT source_report FROM qa_remediation WHERE source_report IS NOT NULL")
    ingeridos = {r[0] for r in cur.fetchall()}

    relatorios = enfileiradas = 0
    for path in sorted(glob.glob(os.path.join(logs_dir, "[0-9][0-9][0-9][0-9]_audit_*.json"))):
        fname = os.path.basename(path)
        if fname in ingeridos:
            continue
        try:
            d = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        specs = _REPORT_FACTORS.get(d.get("mode"))
        if not specs:
            continue  # integrity/connectivity/list/title_verify: sem mapeamento per-livro

        algum = False
        for key, factor in specs:
            for it in (d.get(key) or []):
                if isinstance(it, dict):
                    slug = it.get("slug")
                    if d.get("mode") == "prices" and it.get("status") == "active":
                        continue
                    if d.get("mode") == "content" and it.get("severity") not in ("medium", "high"):
                        continue
                else:
                    slug = it  # author_bio: lista de slugs (strings)
                if not slug:
                    continue
                row = cur.execute("SELECT id FROM livros WHERE slug=?", (slug,)).fetchone()
                if not row:
                    continue
                try:
                    cur.execute(
                        """INSERT INTO qa_remediation (livro_id, factor, reason, status, source_report)
                           VALUES (?, ?, ?, 'pending', ?)""",
                        (row[0], factor, f"auditoria {d.get('mode')}/{key}", fname),
                    )
                    enfileiradas += 1
                    algum = True
                except Exception:
                    pass  # já há remediação aberta p/ (livro, factor)
        if algum or specs:
            relatorios += 1
    conn.commit()
    return {"relatorios": relatorios, "enfileiradas": enfileiradas}


def archive_processed_reports(logs_dir: str = None) -> dict:
    """Poda data/logs/: move relatórios já consumidos para processed_logs/.

    Fecha o buraco do "processado automaticamente": o ingest enfileira as
    remediações, mas sem isto os JSONs se acumulavam em logs/ até alguém rodar
    /audit manualmente (1 por vez). Critérios conservadores:

      • Modos operacionais/mecânicos (author_bio + os de _REPORT_FACTORS): a
        remediação é feita pelos steps / loop mecânico e o /audit os dispensa
        como "lacunas operacionais". Uma vez ingeridos, são arquivados.
      • Modos de revisão do /audit (integrity, connectivity, list, title_verify,
        …): mantém o MAIS RECENTE de cada modo em logs/ (estado atual p/ o /audit
        revisar) e arquiva os snapshots antigos, já superados pelo mais novo.

    Arquivar = mover para data/log_analysis/processed_logs/ (não apaga; sufixo de
    timestamp em caso de colisão de nome). A numeração NNNN segue segura: o
    escritor (core/audit_report) varre processed_logs/ ao gerar o próximo.
    """
    import os
    import glob
    import shutil
    from datetime import datetime, timezone
    from core.audit_report import REPORT_DIR

    logs_dir = logs_dir or str(REPORT_DIR)
    processed_dir = os.path.join(
        os.path.dirname(logs_dir), "log_analysis", "processed_logs")
    os.makedirs(processed_dir, exist_ok=True)

    operational = set(_REPORT_FACTORS) | {"author_bio"}

    # Agrupa por modo, preservando a ordem crescente por NNNN.
    por_modo: dict[str, list[str]] = {}
    for path in sorted(glob.glob(
            os.path.join(logs_dir, "[0-9][0-9][0-9][0-9]_audit_*.json"))):
        m = _REPORT_RE.match(os.path.basename(path))
        if not m:
            continue
        por_modo.setdefault(m.group(2), []).append(path)

    a_arquivar: list[str] = []
    for modo, paths in por_modo.items():
        if modo in operational:
            a_arquivar.extend(paths)          # todos — já ingeridos/dispensados
        else:
            a_arquivar.extend(paths[:-1])     # mantém o mais recente do modo

    arquivados = 0
    for path in a_arquivar:
        dest = os.path.join(processed_dir, os.path.basename(path))
        if os.path.exists(dest):
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%Sz")
            base, ext = os.path.splitext(os.path.basename(path))
            dest = os.path.join(processed_dir, f"{base}__{ts}{ext}")
        try:
            shutil.move(path, dest)
            arquivados += 1
        except Exception:
            pass

    if arquivados:
        log(f"[QA-REMEDIA][archive] relatórios movidos p/ processed_logs/: {arquivados}")
    return {"arquivados": arquivados}


def run_ingest_audit() -> dict:
    """P1 → fila: ingere os relatórios de auditoria na fila de remediação e
    arquiva os já consumidos (poda data/logs/ — sem depender do /audit manual)."""
    conn = get_conn()
    try:
        res = ingest_audit_reports(conn)
        log(f"[QA-REMEDIA][ingest] relatórios={res['relatorios']} "
            f"remediações enfileiradas={res['enfileiradas']}")
    finally:
        conn.close()

    arch = archive_processed_reports()
    res["arquivados"] = arch["arquivados"]
    return res


# ============================================================
# Fatia: TÍTULO — despublicar publicados sem título (NÃO-LLM)
# ============================================================
#
# Blindagem estrutural (par do check_title do quality_gate): o gate agora
# reprova título vazio, impedindo NOVOS registros de entrarem. Mas livros JÁ
# publicados com titulo nulo/vazio precisam ser REBAIXADOS — renderizam um card
# quebrado e uma página sem identidade. Aqui detectamos e DESPUBLICAMOS
# (SQLite + Supabase) reusando o mesmo caminho da blacklist. Auto-remediação no
# loop de QA (G/A) — sem passo manual.

def demote_untitled_published(conn, limit: int = 500) -> dict:
    """Despublica (SQLite + Supabase) livros publicados com titulo nulo/vazio.
    Reusa o caminho de despublicação da blacklist. Retorna contadores."""
    from steps.apply_blacklist import (
        _despublish_sqlite, _despublish_supabase, _load_env,
    )

    cur = conn.cursor()
    cur.execute("""
        SELECT slug FROM livros
        WHERE status_publish = 1
          AND (titulo IS NULL OR TRIM(titulo) = '')
          AND slug IS NOT NULL AND TRIM(slug) <> ''
        LIMIT ?
    """, (limit,))
    slugs = [r[0] for r in cur.fetchall()]
    if not slugs:
        return {"detectados": 0, "despublicados": 0}

    supabase_url, key = _load_env()
    despublicados = 0
    for slug in slugs:
        local_id = _despublish_sqlite(
            conn, slug, dry_run=False, reason="Título vazio", severity="high"
        )
        if not local_id:
            continue
        _despublish_supabase(slug, supabase_url, key, dry_run=False)
        despublicados += 1
    return {"detectados": len(slugs), "despublicados": despublicados}


def run_demote_untitled(limit: int = 500) -> dict:
    """Passe de despublicação de publicados sem título (não-LLM)."""
    conn = get_conn()
    try:
        res = demote_untitled_published(conn, limit=limit)
        if res["detectados"]:
            log(f"[QA-REMEDIA][titulo-vazio] despublicados={res['despublicados']} "
                f"(de {res['detectados']} publicados sem título)")
        else:
            log("[QA-REMEDIA][titulo-vazio] nenhum publicado sem título")
        return res
    finally:
        conn.close()


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="QA — remediação (capas / sinopse / ingest)")
    p.add_argument("--mode",
                   choices=["covers", "synopsis-reconcile", "synopsis-regen",
                            "ingest", "demote-untitled"],
                   default="covers")
    p.add_argument("--limit", type=int, default=50)
    a = p.parse_args()
    if a.mode == "covers":
        run_covers(limit=a.limit)
    elif a.mode == "synopsis-reconcile":
        run_synopsis_reconcile(limit=a.limit)
    elif a.mode == "synopsis-regen":
        run_synopsis_regen(limit=a.limit)
    elif a.mode == "demote-untitled":
        run_demote_untitled(limit=a.limit)
    else:
        run_ingest_audit()
