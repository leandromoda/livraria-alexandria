# ============================================================
# LLM ORCHESTRATOR — Opção O
# Livraria Alexandria
#
# Autopilot cíclico para 7 agentes LLM via claude CLI local.
# Roda de forma exaustiva até não restar trabalho pendente.
#
# Agentes:
#   1. synopsis      — sinopses via synopsis_cowork
#   2. classify      — categorias via classify_cowork
#   3. author_bio    — bios de autores via author_bio
#   4. log_analysis  — análise de logs (1x por ciclo)
#   5. consistency   — relatório de consistência Supabase (1x por ciclo)
#   6. offer_finder  — busca de ofertas afiliadas via web
#   7. title_auditor — auditoria de sinopses/capas publicadas
# ============================================================

import glob
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from core.claude_runner import agent_prompt_path, claude_available, run_agent
from core.cowork_numbering import next_batch_number
from core.db import get_conn
from core.export_for_audit import run as _run_export_audit
from core.logger import log


# =========================
# CONFIG
# =========================

SCRIPTS_DIR   = Path(__file__).parent.parent
DATA_DIR      = SCRIPTS_DIR / "data"
COWORK_DIR    = DATA_DIR / "cowork"
LOGS_DIR      = DATA_DIR / "logs"
AGENTS_DIR    = SCRIPTS_DIR.parent / "agents"

BATCH_SIZE_SYNOPSIS   = 25
BATCH_SIZE_CLASSIFY   = 25
BATCH_SIZE_AUTHOR_BIO = 25
MAX_TEXT_LEN          = 800

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

def _run_agent_step(label: str, prompt_name: str, timeout: int = 600) -> bool:
    prompt = agent_prompt_path(prompt_name)
    log(f"[LLM_ORCH] → {label}: invocando claude CLI…")
    success, output = run_agent(prompt, timeout=timeout)

    if success:
        log(f"[LLM_ORCH] ✓ {label} concluído")
    else:
        log(f"[LLM_ORCH] ✗ {label} falhou: {output[:200]}")

    return success


# =========================
# MAIN CYCLE
# =========================

def run(idioma: str, pacote: int):

    if not claude_available():
        log("[LLM_ORCH] ERRO: claude CLI não encontrado no PATH.")
        log("[LLM_ORCH] Instale o Claude Code e tente novamente, ou use a opção C (cowork manual).")
        return

    log("[LLM_ORCH] ══════════════════════════════════════")
    log("[LLM_ORCH] LLM Autopilot iniciado (opção O)")
    log(f"[LLM_ORCH] Idioma: {idioma} | Pacote: {pacote}")
    log("[LLM_ORCH] ══════════════════════════════════════")

    cycle = 0

    while True:
        cycle += 1
        log(f"[LLM_ORCH] ── Ciclo {cycle} ─────────────────────")
        cycle_done = 0

        conn = get_conn()

        # ── 1. SYNOPSIS ──────────────────────────────────────
        n_syn = _count_pending_synopsis(conn, idioma)
        if n_syn > 0:
            log(f"[LLM_ORCH] synopsis: {n_syn} pendentes")
            exported = _export_synopsis(conn, idioma)
            if exported > 0:
                ok = _run_agent_step("synopsis", "synopsis_cowork", timeout=900)
                if ok:
                    _import_synopsis()
                    cycle_done += exported
        else:
            log("[LLM_ORCH] synopsis: nenhum pendente — skip")

        # ── 2. CLASSIFY ──────────────────────────────────────
        n_cls = _count_pending_classify(conn)
        if n_cls > 0:
            log(f"[LLM_ORCH] classify: {n_cls} pendentes")
            exported = _export_classify(conn)
            if exported > 0:
                ok = _run_agent_step("classify", "classify_cowork", timeout=900)
                if ok:
                    _import_classify()
                    cycle_done += exported
        else:
            log("[LLM_ORCH] classify: nenhum pendente — skip")

        conn.close()

        # ── 3. AUTHOR BIO ─────────────────────────────────────
        conn = get_conn()
        n_bio = _count_pending_author_bio(conn)
        if n_bio > 0:
            log(f"[LLM_ORCH] author_bio: {n_bio} pendentes")
            exported = _export_author_bio(conn)
            if exported > 0:
                ok = _run_agent_step("author_bio", "author_bio", timeout=900)
                if ok:
                    imported = _import_author_bio()
                    cycle_done += imported
        else:
            log("[LLM_ORCH] author_bio: nenhum pendente — skip")
        conn.close()

        # ── 4. LOG ANALYSIS (sempre, 1x por ciclo) ────────────
        log("[LLM_ORCH] log_analysis: executando…")
        ok = _run_agent_step("log_analysis", "log_analysis_cowork", timeout=600)
        if ok:
            cycle_done += 1

        # ── 5. CONSISTENCY REVIEW (sempre, 1x por ciclo) ──────
        log("[LLM_ORCH] consistency_review: gerando relatório…")
        has_report = _export_consistency()
        if has_report:
            ok = _run_agent_step("consistency_review", "consistency_review", timeout=600)
            if ok:
                cycle_done += 1

        # ── 6. OFFER FINDER ───────────────────────────────────
        conn = get_conn()
        n_off = _count_pending_offers(conn)
        conn.close()
        if n_off > 0:
            log(f"[LLM_ORCH] offer_finder: {n_off} livros sem oferta ativa")
            ok = _run_agent_step("offer_finder", "offer_finder", timeout=1800)
            if ok:
                imported = _import_offers()
                cycle_done += imported
        else:
            log("[LLM_ORCH] offer_finder: nenhum pendente — skip")

        # ── 7. TITLE AUDITOR ──────────────────────────────────
        conn = get_conn()
        n_aud = _count_pending_audit(conn)
        conn.close()
        if n_aud > 0:
            log(f"[LLM_ORCH] title_auditor: {n_aud} livros sem auditoria")
            has_export = _export_audit()
            if has_export:
                ok = _run_agent_step("title_auditor", "title_auditor", timeout=1200)
                if ok:
                    imported = _import_audit()
                    cycle_done += imported
        else:
            log("[LLM_ORCH] title_auditor: nenhum pendente — skip")

        # ── FIM DO CICLO ─────────────────────────────────────
        log(f"[LLM_ORCH] Ciclo {cycle} concluído — trabalho realizado: {cycle_done}")

        if cycle_done == 0:
            log("[LLM_ORCH] Nenhum trabalho pendente em nenhum agente.")
            log("[LLM_ORCH] Orquestrador encerrado.")
            break

    log(f"[LLM_ORCH] ══════════════════════════════════════")
    log(f"[LLM_ORCH] Total de ciclos: {cycle}")
    log(f"[LLM_ORCH] ══════════════════════════════════════")
