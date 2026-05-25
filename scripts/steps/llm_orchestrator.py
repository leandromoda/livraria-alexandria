# ============================================================
# LLM ORCHESTRATOR — Opção O
# Livraria Alexandria
#
# Gerador de relatórios de manutenção via claude CLI.
# Executa UMA VEZ por invocação (sem loop); recomendado
# chamar a cada 5 ciclos da opção A.
#
# Agentes:
#   1. log_analysis  — análise dos logs do pipeline
#   2. consistency   — relatório de consistência Supabase
#
# Quando o limite de uso Claude é atingido, aciona
# automaticamente o Autopilot não-LLM (opção A) como fallback.
# ============================================================

import glob
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from core.claude_runner import agent_prompt_path, claude_available, run_agent
from core.claude_usage_tracker import status as claude_usage_status, is_limit_error as _is_limit_error
from core.cowork_numbering import next_batch_number
from core.db import get_conn
from core.export_for_audit import run as _run_export_audit
from core.logger import log
from steps import autopilot


# =========================
# CONFIG
# =========================

SCRIPTS_DIR   = Path(__file__).parent.parent
DATA_DIR      = SCRIPTS_DIR / "data"
COWORK_DIR    = DATA_DIR / "cowork"
LOGS_DIR      = DATA_DIR / "logs"
AGENTS_DIR    = SCRIPTS_DIR.parent / "agents"

BATCH_SIZE_SYNOPSIS   = 10   # ~430s por batch (43s/livro × 10) — margem segura antes do timeout de 900s
BATCH_SIZE_CLASSIFY   = 10   # classify é mais rápido (~5-10s/livro), 10 é conservador
BATCH_SIZE_AUTHOR_BIO = 25
PACOTE_AUTOPILOT      = 100  # pacote do autopilot não-LLM após cada ciclo
MAX_TEXT_LEN          = 800

# Agentes de manutenção: rodam 1× a cada N ciclos (evitam timeout e poupam sessões)
LOG_ANALYSIS_EVERY_N_CYCLES    = 5
CONSISTENCY_REVIEW_EVERY_N_CYCLES = 5
TIMEOUT_MAINTENANCE            = 1800  # 30 min — suficiente para logs acumulados

NUM_PAT = re.compile(r"^(\d{3})_")


# =========================
# PENDING CHECKS
# =========================

def _count_pending_synopsis(conn, idioma: str) -> int:
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM livros
        WHERE status_synopsis = 0
          AND status_review   = 1
          AND is_book         = 1
          AND idioma          = ?
    """, (idioma,))
    return cur.fetchone()[0]


def _count_pending_classify(conn) -> int:
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM livros
        WHERE status_categorize = 0
          AND status_review     = 1
    """)
    return cur.fetchone()[0]


def _count_pending_author_bio(conn) -> int:
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM autores WHERE descricao IS NULL")
    return cur.fetchone()[0]


def _count_pending_offers(conn) -> int:
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM livros
        WHERE is_publishable = 1
          AND status_publish = 1
          AND (offer_url IS NULL OR offer_status != 1)
    """)
    return cur.fetchone()[0]


def _count_pending_audit(conn) -> int:
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM livros
        WHERE is_publishable = 1
          AND id NOT IN (SELECT livro_id FROM audit_log WHERE mode = 'content')
        LIMIT 1
    """)
    row = cur.fetchone()
    return row[0] if row else 0


# =========================
# EXPORT — SYNOPSIS
# =========================

def _export_synopsis(conn, idioma: str) -> int:
    from steps.synopsis_export import fetch_pending

    os.makedirs(COWORK_DIR, exist_ok=True)
    os.makedirs(COWORK_DIR / "processed_synopsis", exist_ok=True)

    rows = fetch_pending(conn, idioma, BATCH_SIZE_SYNOPSIS)

    if not rows:
        return 0

    livros = []
    for livro_id, titulo, slug, autor, idioma_livro, descricao in rows:
        if not descricao or not descricao.strip():
            continue
        livros.append({
            "id":        livro_id,
            "slug":      slug or "",
            "titulo":    titulo,
            "autor":     autor or "",
            "idioma":    idioma_livro,
            "descricao": descricao,
        })

    if not livros:
        return 0

    num = next_batch_number(str(COWORK_DIR), "synopsis")
    output_path = COWORK_DIR / f"{num}_synopsis_input.json"

    payload = {
        "meta": {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "idioma":      idioma,
            "batch":       num,
            "total":       len(livros),
        },
        "livros": livros,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    ids = [l["id"] for l in livros]
    conn.executemany(
        "UPDATE livros SET status_synopsis = 3, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        [(lid,) for lid in ids],
    )
    conn.commit()

    log(f"[LLM_ORCH] synopsis export → {len(livros)} livros → {output_path.name}")
    return len(livros)


# =========================
# IMPORT — SYNOPSIS
# =========================

def _import_synopsis() -> int:
    from steps.synopsis_import import run as synopsis_import_run
    synopsis_import_run()

    outputs = glob.glob(str(COWORK_DIR / "*_synopsis_output.json"))
    return len(outputs)


# =========================
# EXPORT — CLASSIFY
# =========================

def _export_classify(conn) -> int:
    os.makedirs(COWORK_DIR, exist_ok=True)
    os.makedirs(COWORK_DIR / "processed_categorize", exist_ok=True)

    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, titulo, slug, autor, descricao, sinopse
            FROM livros
            WHERE status_categorize = 0
              AND status_review     = 1
            ORDER BY priority_score DESC, created_at ASC
            LIMIT ?
        """, (BATCH_SIZE_CLASSIFY,))
    except Exception:
        cur.execute("""
            SELECT id, titulo, slug, autor, descricao, NULL AS sinopse
            FROM livros
            WHERE status_categorize = 0
              AND status_review     = 1
            ORDER BY created_at ASC
            LIMIT ?
        """, (BATCH_SIZE_CLASSIFY,))

    rows = cur.fetchall()

    if not rows:
        return 0

    livros = []
    for row in rows:
        livros.append({
            "id":        row["id"],
            "slug":      row["slug"] or "",
            "titulo":    row["titulo"],
            "autor":     row["autor"] or "",
            "descricao": (row["descricao"] or "")[:MAX_TEXT_LEN],
            "sinopse":   (row["sinopse"] or "")[:MAX_TEXT_LEN],
        })

    num = next_batch_number(str(COWORK_DIR), "categorize")
    output_path = COWORK_DIR / f"{num}_categorize_input.json"

    payload = {
        "meta": {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "batch":       num,
            "total":       len(livros),
        },
        "livros": livros,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    ids = [l["id"] for l in livros]
    conn.executemany(
        "UPDATE livros SET status_categorize = 3, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        [(lid,) for lid in ids],
    )
    conn.commit()

    log(f"[LLM_ORCH] classify export → {len(livros)} livros → {output_path.name}")
    return len(livros)


# =========================
# IMPORT — CLASSIFY
# =========================

def _import_classify() -> int:
    from steps.categorize_import import run as categorize_import_run
    categorize_import_run()

    outputs = glob.glob(str(COWORK_DIR / "*_categorize_output.json"))
    return len(outputs)


# =========================
# EXPORT — AUTHOR BIO
# =========================

def _export_author_bio(conn) -> int:
    processed_dir = COWORK_DIR / "processed_author_bio"
    os.makedirs(COWORK_DIR, exist_ok=True)
    os.makedirs(processed_dir, exist_ok=True)

    cur = conn.cursor()
    cur.execute("""
        SELECT a.id, a.nome, a.nacionalidade,
               GROUP_CONCAT(l.titulo, ' | ') AS titulos
        FROM autores a
        LEFT JOIN livros_autores la ON la.autor_id = a.id
        LEFT JOIN livros l ON l.id = la.livro_id
        WHERE a.descricao IS NULL
        GROUP BY a.id
        ORDER BY a.nome ASC
        LIMIT ?
    """, (BATCH_SIZE_AUTHOR_BIO,))

    rows = cur.fetchall()

    if not rows:
        return 0

    autores = []
    for row in rows:
        titulos_str = row["titulos"] or ""
        titulos = [t.strip() for t in titulos_str.split("|") if t.strip()] if titulos_str else []
        autores.append({
            "id":            row["id"],
            "nome":          row["nome"],
            "nacionalidade": row["nacionalidade"] or "",
            "titulos":       titulos,
            "idioma":        "PT",
        })

    num = next_batch_number(str(COWORK_DIR), "author_bio")
    output_path = COWORK_DIR / f"{num}_author_bio_input.json"

    payload = {
        "meta": {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "batch":       num,
            "total":       len(autores),
        },
        "autores": autores,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    log(f"[LLM_ORCH] author_bio export → {len(autores)} autores → {output_path.name}")
    return len(autores)


# =========================
# IMPORT — AUTHOR BIO
# =========================

def _import_author_bio() -> int:
    output_pat = re.compile(r"^(\d{3})_author_bio_output\.json$")
    processed_dir = COWORK_DIR / "processed_author_bio"
    os.makedirs(processed_dir, exist_ok=True)

    output_files = sorted(
        [(int(m.group(1)), COWORK_DIR / fname)
         for fname in os.listdir(COWORK_DIR)
         if (m := output_pat.match(fname))],
        key=lambda x: x[0]
    )

    if not output_files:
        return 0

    conn = get_conn()
    total_ok = 0

    for _num, filepath in output_files:
        fname = filepath.name
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            log(f"[LLM_ORCH] author_bio import JSON inválido em {fname}: {e}")
            continue

        resultados = data.get("resultados", [])

        for item in resultados:
            autor_id = item.get("id", "")
            bio      = item.get("bio", "")
            status   = item.get("status", "")

            if status != "APPROVED" or not bio.strip():
                continue

            conn.execute("""
                UPDATE autores
                SET descricao  = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (bio.strip(), autor_id))
            total_ok += 1

        conn.commit()

        dest = processed_dir / fname
        try:
            shutil.move(str(filepath), str(dest))
            log(f"[LLM_ORCH] author_bio import → {fname} ({len(resultados)} autores)")
        except Exception as e:
            log(f"[LLM_ORCH] AVISO: falha ao mover {fname}: {e}")

    conn.close()
    return total_ok


# =========================
# EXPORT — CONSISTENCY
# =========================

def _export_consistency() -> bool:
    from steps.consistency_check import run as consistency_run
    out = consistency_run()
    if out:
        log(f"[LLM_ORCH] consistency export → {out.name}")
        return True
    return False


# =========================
# IMPORT — CONSISTENCY ACTIONS
# =========================

def _import_consistency_actions(conn) -> int:
    """Lê o arquivo *_consistency_actions.json mais recente e executa as ações
    automáticas identificadas pelo agente consistency_review.

    Ações suportadas:
      - livro_sem_oferta   → limpa offer_url / offer_status para re-disparar
                             offer_resolver no próximo ciclo do autopilot.
      - sinopse_suspeita   → reseta sinopse/status_synopsis quando o problema
                             for ausência ou tamanho (não padrão suspeito, que
                             requer revisão humana).

    Retorna o número de registros alterados no SQLite.
    """
    pattern = str(COWORK_DIR / "*_consistency_actions.json")
    files = sorted(glob.glob(pattern))
    if not files:
        return 0

    latest = files[-1]
    try:
        with open(latest, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        log(f"[LLM_ORCH] AVISO: falha ao ler consistency_actions ({latest}): {exc}")
        return 0

    acoes = data.get("acoes_manuais", [])
    if not acoes:
        log("[LLM_ORCH] consistency_actions: nenhuma ação manual pendente.")
        return 0

    processed = 0
    for acao in acoes:
        tipo    = acao.get("tipo", "")
        slug    = acao.get("slug", "")
        livro_id = acao.get("id") or acao.get("livro_id", "")
        problema = acao.get("problema", "")

        if tipo == "livro_sem_oferta" and slug:
            # Re-disparar pipeline de oferta: limpa offer_url para que
            # offer_resolver tente novamente na próxima rodada do autopilot.
            conn.execute("""
                UPDATE livros
                SET offer_url           = NULL,
                    offer_status        = NULL,
                    status_publish_oferta = 0,
                    updated_at          = CURRENT_TIMESTAMP
                WHERE slug = ?
            """, (slug,))
            log(f"[LLM_ORCH] consistency_actions → offer reset: {slug}")
            processed += 1

        elif tipo == "sinopse_suspeita" and livro_id:
            # Só reseta sinopses ausentes/curtas; padrões suspeitos requerem
            # revisão humana e não são tocados automaticamente.
            if "padrao_suspeito" not in problema:
                conn.execute("""
                    UPDATE livros
                    SET sinopse         = NULL,
                        status_synopsis = 0,
                        updated_at      = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (livro_id,))
                log(f"[LLM_ORCH] consistency_actions → synopsis reset: {livro_id}")
                processed += 1

    if processed:
        conn.commit()
        log(f"[LLM_ORCH] consistency_actions → {processed} ação(ões) automáticas aplicadas.")
    return processed


# =========================
# EXPORT — TITLE AUDITOR
# =========================

def _export_audit() -> bool:
    audit_path = DATA_DIR / "audit_input.json"
    _run_export_audit(limit=0, fmt="json")
    return audit_path.exists()


# =========================
# IMPORT — TITLE AUDITOR
# =========================

def _import_audit() -> int:
    blacklist_path = DATA_DIR / "blacklist.json"
    if not blacklist_path.exists():
        return 0

    try:
        from steps.apply_blacklist import run as apply_blacklist_run
        apply_blacklist_run(dry_run=False)
        return 1
    except Exception as e:
        log(f"[LLM_ORCH] ERRO ao aplicar blacklist: {e}")
        return 0


# =========================
# IMPORT — OFFER FINDER
# =========================

def _import_offers() -> int:
    offer_path = DATA_DIR / "offer_list.json"
    if not offer_path.exists():
        return 0

    try:
        from steps.offer_list_importer import run as offer_import_run
        offer_import_run(pacote=500)
        return 1
    except Exception as e:
        log(f"[LLM_ORCH] ERRO ao importar ofertas: {e}")
        return 0


# =========================
# RUN SINGLE AGENT
# =========================

def _run_agent_step(label: str, prompt_name: str, timeout: int = 600) -> tuple[bool, bool]:
    """Invoca um agente via claude CLI.

    Retorna (success, limit_persists):
      - success: True se o agente concluiu sem erro.
      - limit_persists: True se o limite de uso ainda está ativo APÓS o retry
        automático feito dentro de run_agent(). Quando True, o ciclo inteiro
        deve ser interrompido para não disparar novas chamadas com limite ativo.
    """
    prompt = agent_prompt_path(prompt_name)
    log(f"[LLM_ORCH] → {label}: invocando claude CLI…")
    success, output = run_agent(prompt, timeout=timeout)

    if success:
        log(f"[LLM_ORCH] ✓ {label} concluído")
        return True, False

    # Falha — verificar se ainda é erro de limite após o retry interno
    limit_persists = _is_limit_error(output)
    if limit_persists:
        log(f"[LLM_ORCH] ⛔ {label} — limite de uso persistente após retry. Ciclo será interrompido.")
    else:
        log(f"[LLM_ORCH] ✗ {label} falhou: {output[:200]}")
    return False, limit_persists


# =========================
# MAIN CYCLE
# =========================

def run(idioma: str):
    """Manutenção LLM (opção O): gera relatórios de log e consistência.

    Executa log_analysis e consistency_review via claude CLI (uma vez por
    invocação, sem loop). Recomendado: chamar a cada 5 ciclos da opção A.

    Se o limite de uso Claude for atingido, aciona o Autopilot não-LLM
    (opção A) como fallback automático.
    """

    from core.claude_runner import _find_claude
    claude_bin = _find_claude()
    if not claude_bin:
        log("[LLM_ORCH] ERRO: claude CLI não encontrado.")
        log("[LLM_ORCH] Solução recomendada (instala globalmente via npm):")
        log("[LLM_ORCH]   npm install -g @anthropic-ai/claude-code")
        log("[LLM_ORCH] Após instalar, reabra o terminal e rode a opção O novamente.")
        log("[LLM_ORCH] Alternativa (caminho explícito em scripts/.env):")
        log("[LLM_ORCH]   CLAUDE_BIN=C:/Users/.../AppData/Roaming/Claude/claude-code/VERSION/claude.exe")
        return

    usage = claude_usage_status()
    log("[LLM_ORCH] ══════════════════════════════════════")
    log("[LLM_ORCH] Opção O — Relatórios de Manutenção LLM")
    log(
        f"[LLM_ORCH] Claude: {usage['calls_today']} chamadas hoje | "
        f"{usage['calls_total']} total | "
        f"limites atingidos: {usage['limit_hit_count']}"
    )
    log("[LLM_ORCH] ══════════════════════════════════════")

    limit_hit = False

    # ── 1. LOG ANALYSIS ─────────────────────────────────
    log("[LLM_ORCH] log_analysis: iniciando…")
    ok, limit_persists = _run_agent_step("log_analysis", "log_analysis_cowork", timeout=TIMEOUT_MAINTENANCE)
    if limit_persists:
        limit_hit = True
    elif ok:
        log("[LLM_ORCH] log_analysis: concluído")
    else:
        log("[LLM_ORCH] log_analysis: falhou (sem limite de uso)")

    # ── 2. CONSISTENCY REVIEW ────────────────────────────
    if not limit_hit:
        log("[LLM_ORCH] consistency_review: gerando relatório…")
        has_report = _export_consistency()
        if has_report:
            ok, limit_persists = _run_agent_step(
                "consistency_review", "consistency_review", timeout=TIMEOUT_MAINTENANCE
            )
            if limit_persists:
                limit_hit = True
            elif ok:
                conn = get_conn()
                _import_consistency_actions(conn)
                conn.close()
        else:
            log("[LLM_ORCH] consistency_review: nenhum dado para exportar — skip")

    # ── FALLBACK: Autopilot não-LLM quando limite atingido ──
    if limit_hit:
        log("[LLM_ORCH] ⛔ Limite Claude atingido — iniciando Autopilot não-LLM como fallback…")
        try:
            autopilot.run(idioma, PACOTE_AUTOPILOT, manter_cowork=True)
        except Exception as e:
            log(f"[LLM_ORCH] AVISO: autopilot retornou com exceção: {e}")

    log("[LLM_ORCH] ══════════════════════════════════════")
    log("[LLM_ORCH] Opção O concluída.")
    log("[LLM_ORCH] ══════════════════════════════════════")
