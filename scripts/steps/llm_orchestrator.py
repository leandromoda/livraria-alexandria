# ============================================================
# LLM ORCHESTRATOR — Opção O
# Livraria Alexandria
#
# Autopilot cíclico para agentes LLM via claude CLI local.
# Roda de forma exaustiva até não restar trabalho pendente.
#
# Agentes:
#   1. synopsis      — sinopses via synopsis_cowork
#   2. classify      — categorias via classify_cowork
#   3. author_bio    — bios de autores via author_bio
#   4. log_analysis  — relatório de logs (1x/N ciclos; só gera, não aplica)
#   5. consistency   — relatório Supabase (1x/N ciclos; só gera, não aplica)
#   6. offer_finder  — busca de ofertas afiliadas via web
#   7. title_auditor — auditoria de sinopses/capas publicadas
#
# Relatórios (4 e 5) são gerados aqui mas lidos/aplicados por
# rotina externa ao pipeline.
# Quando limite Claude atingido: fallback automático para Autopilot
# não-LLM (opção A).
# ============================================================

import glob
import json
import os
import re
import shutil
import subprocess
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

# WS3: tamanhos de lote calibráveis via env, CALIBRADOS por medição empírica
# (tools/measure_batch.py, 2026-05-30, motor batch pós-WS2). Curva real:
#   synopsis: size 10→26,5s/item; size 15→25,7s/item, 385s wall (timeout 900s).
#             size 5 = 64,8s/item (overhead fixo não amortizado). 15 dá ~2,5x
#             throughput vs 5, com folga ampla antes do timeout.
#   classify: size 20→5,9s/item; size 25→6,5s/item, 161s wall. Barato; 25 dobra
#             o throughput vs 10 com folga enorme (cap do export = 25).
BATCH_SIZE_SYNOPSIS   = int(os.getenv("BATCH_SIZE_SYNOPSIS", "15"))
BATCH_SIZE_CLASSIFY   = int(os.getenv("BATCH_SIZE_CLASSIFY", "25"))
BATCH_SIZE_AUTHOR_BIO = int(os.getenv("BATCH_SIZE_AUTHOR_BIO", "25"))
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
# GIT COMMIT REPORTS
# =========================

def _git_commit_reports(glob_patterns: list[str], label: str) -> None:
    """Commita arquivos de relatório gerados pelo pipeline para o git.

    O agente remoto (CCR) só enxerga arquivos versionados — sem commit,
    os relatórios ficam apenas no disco local e nunca são processados.

    Args:
        glob_patterns: Lista de padrões glob relativos à raiz do repo.
        label: Rótulo para o commit (ex: "log_analysis", "consistency").
    """
    repo_root = SCRIPTS_DIR.parent
    matched: list[str] = []
    for pattern in glob_patterns:
        matched.extend(glob.glob(str(repo_root / pattern)))

    if not matched:
        log(f"[LLM_ORCH] git_commit({label}): nenhum arquivo novo para commitar")
        return

    try:
        # git add
        subprocess.run(
            ["git", "add", "--"] + matched,
            cwd=str(repo_root),
            check=True,
            capture_output=True,
            text=True,
        )
        # git commit (--allow-empty-message não necessário; só commita se houver staged)
        result = subprocess.run(
            ["git", "commit", "-m", f"chore(pipeline): relatórios {label} gerados automaticamente"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            log(f"[LLM_ORCH] git_commit({label}): {len(matched)} arquivo(s) commitados")
        elif "nothing to commit" in result.stdout or "nothing to commit" in result.stderr:
            log(f"[LLM_ORCH] git_commit({label}): arquivos já commitados — sem alteração")
        else:
            log(f"[LLM_ORCH] git_commit({label}): AVISO — {result.stderr.strip()[:200]}")
    except Exception as e:
        log(f"[LLM_ORCH] git_commit({label}): erro ao commitar — {e}")


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
# LOG ANALYSIS WRAPPER
# =========================

def _run_log_analysis() -> tuple[bool, bool]:
    """Invoca o agente log_analysis com verificação de output.

    Garante que o JSON foi gravado em data/log_analysis/ (root).
    Casos tratados:
      - JSON no lugar correto → success
      - JSON em processed_logs/ por engano → copia para o root e success
      - Log consumido mas sem JSON em lugar algum → warning (não propaga erro)
      - Nenhum log pendente → skip (success imediato)

    Retorna (ok, limit_persists) igual a _run_agent_step.
    """
    pending_logs = sorted(glob.glob(str(LOGS_DIR / "pipeline_*.log")))
    if not pending_logs:
        log("[LLM_ORCH] log_analysis: nenhum log pendente em data/logs/ — skip")
        return True, False

    log(f"[LLM_ORCH] log_analysis: {len(pending_logs)} log(s) pendente(s) em data/logs/")

    # Snapshot antes da chamada
    log_analysis_dir = DATA_DIR / "log_analysis"
    processed_dir    = log_analysis_dir / "processed_logs"
    before_root = set(glob.glob(str(log_analysis_dir / "log_analysis_*.json")))
    before_proc = set(glob.glob(str(processed_dir / "log_analysis_*.json")))
    before_logs = set(pending_logs)

    # Invocar agente
    ok, limit_persists = _run_agent_step(
        "log_analysis", "log_analysis_cowork", timeout=TIMEOUT_MAINTENANCE
    )

    if limit_persists:
        return False, True

    # Verificar output
    after_root = set(glob.glob(str(log_analysis_dir / "log_analysis_*.json")))
    after_proc = set(glob.glob(str(processed_dir / "log_analysis_*.json")))
    after_logs = set(glob.glob(str(LOGS_DIR / "pipeline_*.log")))

    new_root = after_root - before_root
    new_proc = after_proc - before_proc
    consumed = before_logs - after_logs

    if new_root:
        # Caminho correto — relatório em data/log_analysis/
        log(f"[LLM_ORCH] log_analysis: ✓ relatório → {Path(list(new_root)[0]).name}")
        return True, False

    if new_proc:
        # Agente gravou em processed_logs/ em vez do root — corrigir
        import shutil as _shutil
        for json_path in new_proc:
            dest = log_analysis_dir / Path(json_path).name
            _shutil.copy2(json_path, dest)
            log(f"[LLM_ORCH] log_analysis: ⚠️ JSON estava em processed_logs/ — copiado para root → {dest.name}")
        return True, False

    # Nenhum JSON gerado
    if consumed:
        log(
            f"[LLM_ORCH] log_analysis: ⚠️ {len(consumed)} log(s) consumido(s) "
            f"mas JSON não encontrado em data/log_analysis/ nem em processed_logs/. "
            f"Possível timeout do agente antes do Write."
        )
    elif not ok:
        log("[LLM_ORCH] log_analysis: agente falhou sem consumir logs nem gerar JSON")
    else:
        log("[LLM_ORCH] log_analysis: agente concluiu mas não gerou JSON — verificar manualmente")

    return ok, False


# =========================
# DRAIN HELPERS (WS1 — priorização do gargalo)
# =========================
# Cada helper esvazia um agente de CONTEÚDO repetidamente (vários lotes) até
# zerar o backlog OU bater o limite de sessão. A janela de sessão PRO é gasta
# primeiro no gargalo (sinopse), depois categorização e bios — só então os
# agentes não-críticos (offer_finder/title_auditor/relatórios) rodam. Antes,
# cada ciclo fazia 1 único lote de sinopse e gastava o resto da janela em
# agentes que não destravam publicação.

def _drain_synopsis(idioma: str) -> tuple[int, bool]:
    """Esvazia o backlog de sinopses (lote a lote). Retorna (feitos, limit_hit)."""
    done = 0
    while True:
        conn = get_conn()
        n = _count_pending_synopsis(conn, idioma)
        if n <= 0:
            conn.close()
            break
        log(f"[LLM_ORCH] synopsis: {n} pendentes")
        exported = _export_synopsis(conn, idioma)
        conn.close()
        if exported <= 0:
            break
        ok, limit_persists = _run_agent_step("synopsis", "synopsis_cowork", timeout=900)
        if limit_persists:
            return done, True
        if ok:
            _import_synopsis()
            done += exported
        else:
            orphans = glob.glob(str(COWORK_DIR / "*_synopsis_input.json"))
            if orphans:
                log(
                    f"[LLM_ORCH] ⚠ synopsis timeout/erro — {len(orphans)} arquivo(s) "
                    f"input pendente(s) em cowork/. Livros ficam em status_synopsis=3 "
                    f"até o próximo ciclo processar o arquivo."
                )
            break  # não há como progredir nesta janela
    return done, False


def _drain_classify() -> tuple[int, bool]:
    """Esvazia o backlog de categorização (lote a lote). Retorna (feitos, limit_hit)."""
    done = 0
    while True:
        conn = get_conn()
        n = _count_pending_classify(conn)
        if n <= 0:
            conn.close()
            break
        log(f"[LLM_ORCH] classify: {n} pendentes")
        exported = _export_classify(conn)
        conn.close()
        if exported <= 0:
            break
        ok, limit_persists = _run_agent_step("classify", "classify_cowork", timeout=900)
        if limit_persists:
            return done, True
        if ok:
            _import_classify()
            done += exported
        else:
            break
    return done, False


def _drain_author_bio() -> tuple[int, bool]:
    """Esvazia o backlog de bios de autores (lote a lote). Retorna (feitos, limit_hit)."""
    done = 0
    while True:
        conn = get_conn()
        n = _count_pending_author_bio(conn)
        if n <= 0:
            conn.close()
            break
        log(f"[LLM_ORCH] author_bio: {n} pendentes")
        exported = _export_author_bio(conn)
        conn.close()
        if exported <= 0:
            break
        ok, limit_persists = _run_agent_step("author_bio", "author_bio", timeout=900)
        if limit_persists:
            return done, True
        if ok:
            done += _import_author_bio()
        else:
            break
    return done, False


def _content_backlog(idioma: str) -> int:
    """Soma do backlog de conteúdo que destrava publicação (sinopse + categoria)."""
    conn = get_conn()
    try:
        return _count_pending_synopsis(conn, idioma) + _count_pending_classify(conn)
    finally:
        conn.close()


# =========================
# MAIN CYCLE
# =========================

def run(idioma: str):
    """Autopilot LLM cíclico — processa sinopses, categorias, bios e ofertas.

    Priorização (WS1): a janela de sessão PRO é gasta PRIMEIRO no gargalo
    (sinopse), depois categorização e bios — esvaziando cada um (vários lotes)
    antes de tocar nos agentes não-críticos. Estes só rodam quando o backlog de
    conteúdo está zerado e ainda há sessão disponível.

    A cada N ciclos também gera relatórios de log e consistência (sem aplicar
    correções inline — leitura e aplicação são responsabilidade de rotina externa).

    Quando limite Claude atingido: aciona Autopilot não-LLM como fallback.
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

    log("[LLM_ORCH] ══════════════════════════════════════")
    log("[LLM_ORCH] LLM Autopilot iniciado (opção O)")
    log(f"[LLM_ORCH] Idioma: {idioma} | Batch: {BATCH_SIZE_SYNOPSIS} livro(s)/chamada")
    log("[LLM_ORCH] ══════════════════════════════════════")

    from steps import reclaim
    reclaim.run()

    cycle = 0

    while True:
        cycle += 1
        usage = claude_usage_status()
        log(
            f"[LLM_ORCH] ── Ciclo {cycle} ─────────────────────  "
            f"[Claude: {usage['calls_today']} chamadas hoje | "
            f"{usage['calls_total']} total | "
            f"limites atingidos: {usage['limit_hit_count']}]"
        )
        cycle_done      = 0
        cycle_limit_hit = False   # sinaliza se o limite persistiu após retry

        # ── 0. IMPORT DE OUTPUTS PENDENTES ───────────────────
        # Importa outputs já prontos de ciclos anteriores (ex: batch que gerou
        # output mas não foi importado por timeout). Conta ANTES de importar para
        # incrementar cycle_done — sem isso, o autopilot não-LLM não roda e os
        # livros importados ficam sem passar pelo Quality Gate / Publicação.
        _startup_outputs = glob.glob(str(COWORK_DIR / "*_synopsis_output.json"))
        if _startup_outputs:
            log(f"[LLM_ORCH] synopsis: {len(_startup_outputs)} output(s) pendente(s) de ciclo(s) anterior(es) — importando…")
            _import_synopsis()
            cycle_done += len(_startup_outputs)

        # ── FASE A — CONTEÚDO (prioridade): esvaziar o gargalo ───
        # Sinopse primeiro (maior gargalo, hard-block do Quality Gate), depois
        # categorização, depois bios — cada um drenado em vários lotes.
        syn_done, cycle_limit_hit = _drain_synopsis(idioma)
        cycle_done += syn_done
        if syn_done == 0 and not cycle_limit_hit:
            log("[LLM_ORCH] synopsis: nenhum pendente — skip")

        if not cycle_limit_hit:
            cls_done, cycle_limit_hit = _drain_classify()
            cycle_done += cls_done
            if cls_done == 0 and not cycle_limit_hit:
                log("[LLM_ORCH] classify: nenhum pendente — skip")

        if not cycle_limit_hit:
            bio_done, cycle_limit_hit = _drain_author_bio()
            cycle_done += bio_done
            if bio_done == 0 and not cycle_limit_hit:
                log("[LLM_ORCH] author_bio: nenhum pendente — skip")

        # ── FASE B — NÃO-CRÍTICOS ────────────────────────────
        # Só rodam quando o backlog de CONTEÚDO está zerado e ainda há sessão.
        # Evita que offer_finder/title_auditor/relatórios consumam a janela
        # enquanto há sinopse/categoria pendente (causa raiz do P1/P2).
        content_left = _content_backlog(idioma) if not cycle_limit_hit else -1
        run_non_critical = (not cycle_limit_hit) and content_left == 0
        if not cycle_limit_hit and not run_non_critical:
            log(f"[LLM_ORCH] não-críticos: adiados — {content_left} item(ns) de conteúdo ainda pendente(s)")

        # ── 4. LOG ANALYSIS (1× a cada N ciclos) ─────────────
        # Apenas gera o relatório — leitura e correções por rotina externa.
        if run_non_critical and cycle % LOG_ANALYSIS_EVERY_N_CYCLES == 0:
            log(f"[LLM_ORCH] log_analysis: executando (ciclo {cycle}, frequência 1/{LOG_ANALYSIS_EVERY_N_CYCLES})…")
            ok, limit_persists = _run_log_analysis()
            if limit_persists:
                cycle_limit_hit = True
            elif ok:
                _git_commit_reports(
                    ["scripts/data/log_analysis/log_analysis_*.json"],
                    "log_analysis",
                )
                cycle_done += 1
        elif run_non_critical:
            log(f"[LLM_ORCH] log_analysis: skip (ciclo {cycle}, próximo em ciclo {((cycle // LOG_ANALYSIS_EVERY_N_CYCLES) + 1) * LOG_ANALYSIS_EVERY_N_CYCLES})")

        # ── 5. CONSISTENCY REVIEW (1× a cada N ciclos) ────────
        # Apenas gera o relatório — leitura e correções por rotina externa.
        if run_non_critical and cycle % CONSISTENCY_REVIEW_EVERY_N_CYCLES == 0:
            log(f"[LLM_ORCH] consistency_review: gerando relatório (ciclo {cycle})…")
            has_report = _export_consistency()
            if has_report:
                ok, limit_persists = _run_agent_step("consistency_review", "consistency_review", timeout=TIMEOUT_MAINTENANCE)
                if limit_persists:
                    cycle_limit_hit = True
                elif ok:
                    _git_commit_reports(
                        [
                            "scripts/data/cowork/*_consistency.json",
                            "scripts/data/cowork/*_consistency_actions.json",
                        ],
                        "consistency_review",
                    )
                    cycle_done += 1
        elif run_non_critical:
            log(f"[LLM_ORCH] consistency_review: skip (ciclo {cycle})")

        # ── 6. OFFER FINDER ───────────────────────────────────
        if run_non_critical:
            conn = get_conn()
            n_off = _count_pending_offers(conn)
            conn.close()
            if n_off > 0:
                log(f"[LLM_ORCH] offer_finder: {n_off} livros sem oferta ativa")
                ok, limit_persists = _run_agent_step("offer_finder", "offer_finder", timeout=1800)
                if limit_persists:
                    cycle_limit_hit = True
                elif ok:
                    imported = _import_offers()
                    cycle_done += imported
            else:
                log("[LLM_ORCH] offer_finder: nenhum pendente — skip")

        # ── 7. TITLE AUDITOR ──────────────────────────────────
        if run_non_critical:
            conn = get_conn()
            n_aud = _count_pending_audit(conn)
            conn.close()
            if n_aud > 0:
                log(f"[LLM_ORCH] title_auditor: {n_aud} livros sem auditoria")
                has_export = _export_audit()
                if has_export:
                    ok, limit_persists = _run_agent_step("title_auditor", "title_auditor", timeout=1200)
                    if limit_persists:
                        cycle_limit_hit = True
                    elif ok:
                        imported = _import_audit()
                        cycle_done += imported
            else:
                log("[LLM_ORCH] title_auditor: nenhum pendente — skip")

        # ── AUTOPILOT NÃO-LLM ────────────────────────────────
        # Após imports de synopsis/classify, roda autopilot para processar
        # os livros desbloqueados até publicação (QG → Publish → Listas).
        if cycle_done > 0:
            log("[LLM_ORCH] Executando autopilot não-LLM para processar resultados importados...")
            try:
                autopilot.run(idioma, PACOTE_AUTOPILOT, manter_cowork=True)
            except Exception as e:
                log(f"[LLM_ORCH] AVISO: autopilot retornou com exceção: {e}")

        # ── FIM DO CICLO ─────────────────────────────────────
        log(f"[LLM_ORCH] Ciclo {cycle} concluído — trabalho realizado: {cycle_done}"
            + (" | ⛔ interrompido por limite de uso" if cycle_limit_hit else ""))

        if cycle_limit_hit:
            log("[LLM_ORCH] Limite de uso persistente após retry — iniciando Autopilot não-LLM como fallback…")
            try:
                autopilot.run(idioma, PACOTE_AUTOPILOT, manter_cowork=True)
            except Exception as e:
                log(f"[LLM_ORCH] AVISO: autopilot retornou com exceção: {e}")
            break

        if cycle_done == 0:
            log("[LLM_ORCH] Nenhum trabalho pendente em nenhum agente.")
            log("[LLM_ORCH] Orquestrador encerrado.")
            break

    log(f"[LLM_ORCH] ══════════════════════════════════════")
    log(f"[LLM_ORCH] Total de ciclos: {cycle}")
    log(f"[LLM_ORCH] ══════════════════════════════════════")
