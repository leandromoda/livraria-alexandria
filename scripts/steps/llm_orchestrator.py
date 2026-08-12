# ============================================================
# LLM ORCHESTRATOR — Opção O
# Livraria Alexandria
#
# Autopilot cíclico para agentes LLM via claude CLI local.
# Roda de forma exaustiva até não restar trabalho pendente.
#
# Agentes:
#   1. synopsis      — sinopses via synopsis_batch
#   2. classify      — categorias via classify_batch
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

from core.claude_runner import agent_prompt_path, claude_available, input_hint, run_agent
from core.claude_usage_tracker import status as claude_usage_status, is_limit_error as _is_limit_error


class ClaudeAuthError(RuntimeError):
    """Raised when Claude CLI returns 401 / authentication failure.

    Distinct from session-limit errors: waiting for reset won't help.
    The user must run 'claude' in a terminal and log in again.
    """
    pass


# Fonte única em core.claude_runner — evita que os padrões divirjam entre o
# pré-voo do G e a detecção durante o ciclo.
from core.claude_runner import is_auth_error as _is_auth_error


from core.batch_numbering import next_batch_number, pending_batch_input
from core import kv_state
from core.db import get_conn
from core.export_for_audit import run as _run_export_audit
from core.logger import log
from steps import autopilot


# =========================
# CONFIG
# =========================

SCRIPTS_DIR   = Path(__file__).parent.parent
DATA_DIR      = SCRIPTS_DIR / "data"
BATCH_DIR    = DATA_DIR / "batch"
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

# Rotação de bios (ver "Rotação de bios" no CLAUDE.md).
# Cota de autores — não de lotes — processados no INÍCIO de cada ciclo, antes
# da sinopse. Sem isso as bios nunca rodam: a fase de bios fica atrás de
# sinopse e categorização, que juntas somam ~1.300 lotes e não zeram numa
# janela de 5h. 0 desliga a rotação e restaura o comportamento antigo.
BIO_POR_CICLO = int(os.getenv("BIO_POR_CICLO", "10"))

# Mesma fome que as bios, com fila maior e prejuízo já no ar: em 2026-07-25,
# 2.620 dos 4.403 livros publicados (60%) estavam no site sem categoria
# temática — fora das páginas de categoria e das listas. Categorização é
# barata (~6,5 s/livro contra ~26 s/livro da sinopse), então a cota padrão é
# um lote cheio. 0 desliga.
CLASSIFY_POR_CICLO = int(os.getenv("CLASSIFY_POR_CICLO", "25"))

# ── SLOT SECUNDÁRIO ──────────────────────────────────────────────────────
# MEDIÇÃO QUE ORIGINOU ISTO (2026-08-09, n=3 — logs pipeline_2026-08-04_21-21-31,
# _08-05_21-12-07 e _08-06_21-17-39; contagem dos pares "→ <agente>: invocando
# claude CLI" / "✓ <agente> concluído" até "limite de uso persistente"):
#
#   janela          | chamadas | author_bio | classify | synopsis
#   08-04 (20m19s)  |    5     |     1      |    1     |    3
#   08-05 (25m51s)  |    6     |     1      |    1     |    4
#   08-06 (26m32s)  |    6     |     1      |    1     |    4
#
# Uma janela de 5h comporta 5-6 chamadas, não centenas — e o limite bate ~30 min
# depois do início, no Ciclo 1 dos três logs (ou seja: 1 ciclo ≈ 1 janela, e
# "cota por ciclo" é na prática "cota por janela"). As duas rotações fixas
# consumiam 2 dessas 5-6 chamadas = 33-40% da janela, TODA janela.
#
# ⚠ Isto corrige a justificativa escrita em `_rotacao_author_bio` e no
# scripts/CLAUDE.md ("1 chamada por ciclo contra as centenas gastas em
# sinopse"). Não são centenas: são 3-4.
#
# O slot troca as 2 chamadas fixas por UMA, disputada por prioridade:
#   1º  auditoria LLM vencida (limiar em pipeline_status._AUDIT_STEPS:
#       content 48h, title-verify 168h) — rara por construção;
#   2º  senão, rodízio author_bio ↔ classify, com cursor persistido.
#
# Efeito: sobra 1 chamada por janela para a sinopse (3-4 → 4-5, ~+15 livros
# publicados por janela) E as auditorias LLM passam a rodar — antes disso elas
# estavam em "nunca executado" e o plano do G mandava o usuário rodá-las à mão,
# o que o scripts/CLAUDE.md proíbe.
#
# Contrapartida: bio e classify drenam ~2× mais devagar. As duas filas já eram
# inalcançáveis no ritmo anterior (13.571 classify a ~120/dia = 113 dias), e a
# sinopse é o hard-block do Quality Gate — a troca segue a prioridade do gargalo.
#
# 0 restaura o comportamento antigo (as duas rotações fixas, 2 chamadas).
SLOT_SECUNDARIO = int(os.getenv("SLOT_SECUNDARIO", "1"))

# Quantos LIVROS a auditoria audita quando ocupa o slot.
#
# HISTÓRICO DA UNIDADE — importante para não regredir. Até 2026-08-11 a
# auditoria chamava o LLM uma vez POR LIVRO, então este número era, na prática,
# um número de CHAMADAS. Medido rodando o G: com 25, o `claude_usage_tracker`
# foi de 5 para 30 chamadas no dia (25 chamadas, 13m45s, num slot só) — contra
# uma janela que comporta 5-6 chamadas de lote (medido 2026-08-09, n=3). Ou
# seja, gastava 4-5 janelas numa auditoria.
#
# Hoje a auditoria é BATCH (`auditor.AUDIT_BATCH_SIZE`, padrão 10 livros por
# chamada), então este valor custa ceil(N / AUDIT_BATCH_SIZE) chamadas: com 10,
# **1 chamada**, o mesmo que qualquer outro ocupante do slot. Subir daqui só
# multiplica em passos de AUDIT_BATCH_SIZE.
#
# 0 desliga as auditorias LLM.
AUDIT_LLM_POR_CICLO = int(os.getenv("AUDIT_LLM_POR_CICLO", "10"))

# Ordem do rodízio e chave do cursor persistido. O cursor PRECISA sobreviver ao
# processo: em memória ele reiniciaria a cada `python main.py` e, como o limite
# bate no Ciclo 1, o primeiro da lista ganharia o slot SEMPRE e o segundo nunca
# rodaria. Mesma armadilha do seed de `repair_synced_ids` (steps/autopilot.py) e
# dos guards zerados a cada re-invocação (core/drain_loop.py).
_RODIZIO_SLOT = ("author_bio", "classify")
_CURSOR_KEY   = "slot_secundario.cursor"

# (label em pipeline_status._AUDIT_STEPS, modo de steps/qa.py)
_AUDITORIAS_LLM = (
    ("22 Conteúdo (LLM)", "content"),
    ("31 Título Verac.",  "titles"),
)

PACOTE_AUTOPILOT      = 100  # pacote do autopilot não-LLM após cada ciclo
MAX_TEXT_LEN          = 800

# Agentes de manutenção: rodam 1× a cada N ciclos (evitam timeout e poupam sessões)
LOG_ANALYSIS_EVERY_N_CYCLES    = 5
CONSISTENCY_REVIEW_EVERY_N_CYCLES = 5
TIMEOUT_MAINTENANCE            = 1800  # 30 min — suficiente para logs acumulados

NUM_PAT = re.compile(r"^(\d+)_")


# =========================
# PENDING CHECKS
# =========================

def _count_pending_synopsis(conn, idioma: str) -> int:
    """Pendentes EXPORTÁVEIS — só os que têm descrição.

    Livro sem descrição é rejeição garantida pelo agente, então contá-lo aqui
    faria o orquestrador esperar quota para um trabalho impossível: o G ficaria
    em loop multijanela achando que há 11 mil sinopses a fazer. Use
    `_count_sem_descricao` para enxergar os excluídos.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM livros
        WHERE status_synopsis = 0
          AND status_review   = 1
          AND is_book         = 1
          AND idioma          = ?
          AND descricao IS NOT NULL
          AND TRIM(descricao) <> ''
    """, (idioma,))
    return cur.fetchone()[0]


def _count_sem_descricao(conn, idioma: str) -> int:
    """Pendentes de sinopse BLOQUEADOS por falta de descrição.

    Medido em 2026-07-26: 10.041 de 11.028 (91%). Todos com status_descricao=2
    (o enrich já tentou e falhou) e todos processados DEPOIS do PR #180, que
    trouxe fallback multi-idioma e match por autor — ou seja, re-enriquecer com
    o código atual não os recupera. Ver TASK-SYN-016 e TASK-ENRICH-002.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM livros
        WHERE status_synopsis = 0
          AND status_review   = 1
          AND is_book         = 1
          AND idioma          = ?
          AND (descricao IS NULL OR TRIM(descricao) = '')
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

    os.makedirs(BATCH_DIR, exist_ok=True)
    os.makedirs(BATCH_DIR / "processed_synopsis", exist_ok=True)

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

    num = next_batch_number(str(BATCH_DIR), "synopsis")
    output_path = BATCH_DIR / f"{num}_synopsis_input.json"

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

    outputs = glob.glob(str(BATCH_DIR / "*_synopsis_output.json"))
    return len(outputs)


# =========================
# EXPORT — CLASSIFY
# =========================

def _export_classify(conn, limite: int | None = None) -> int:
    """Exporta um lote de categorização. `limite` recorta abaixo de
    BATCH_SIZE_CLASSIFY para a cota da rotação."""
    os.makedirs(BATCH_DIR, exist_ok=True)
    os.makedirs(BATCH_DIR / "processed_categorize", exist_ok=True)

    tamanho = min(limite, BATCH_SIZE_CLASSIFY) if limite else BATCH_SIZE_CLASSIFY

    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, titulo, slug, autor, descricao, sinopse
            FROM livros
            WHERE status_categorize = 0
              AND status_review     = 1
            ORDER BY priority_score DESC, created_at ASC
            LIMIT ?
        """, (tamanho,))
    except Exception:
        cur.execute("""
            SELECT id, titulo, slug, autor, descricao, NULL AS sinopse
            FROM livros
            WHERE status_categorize = 0
              AND status_review     = 1
            ORDER BY created_at ASC
            LIMIT ?
        """, (tamanho,))

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

    num = next_batch_number(str(BATCH_DIR), "categorize")
    output_path = BATCH_DIR / f"{num}_categorize_input.json"

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

    outputs = glob.glob(str(BATCH_DIR / "*_categorize_output.json"))
    return len(outputs)


# =========================
# EXPORT — AUTHOR BIO
# =========================

def _export_author_bio(conn, limite: int | None = None) -> int:
    """Exporta um lote de bios. `limite` recorta abaixo de BATCH_SIZE_AUTHOR_BIO
    para a cota da rotação (ex: 10 autores), que é menor que um lote cheio."""
    processed_dir = BATCH_DIR / "processed_author_bio"
    os.makedirs(BATCH_DIR, exist_ok=True)
    os.makedirs(processed_dir, exist_ok=True)

    tamanho = min(limite, BATCH_SIZE_AUTHOR_BIO) if limite else BATCH_SIZE_AUTHOR_BIO

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
    """, (tamanho,))

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

    num = next_batch_number(str(BATCH_DIR), "author_bio")
    output_path = BATCH_DIR / f"{num}_author_bio_input.json"

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
    output_pat = re.compile(r"^(\d+)_author_bio_output\.json$")
    processed_dir = BATCH_DIR / "processed_author_bio"
    os.makedirs(processed_dir, exist_ok=True)

    output_files = sorted(
        [(int(m.group(1)), BATCH_DIR / fname)
         for fname in os.listdir(BATCH_DIR)
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
    pattern = str(BATCH_DIR / "*_consistency_actions.json")
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

def _run_agent_step(label: str, prompt_name: str, timeout: int = 600,
                    batch_prefix: str | None = None) -> tuple[bool, bool]:
    """Invoca um agente via claude CLI — NÃO bloqueia no limite de sessão.

    Usa wait_on_limit=False: ao bater o limite, run_agent retorna imediatamente
    (sem dormir 5h). Quem decide o fallback é o ciclo do orquestrador (rodar
    Autopilot A não-LLM e só então aguardar/retomar ou encerrar) — antes, a
    espera ficava escondida dentro do run_agent e o fallback A nunca rodava.

    `batch_prefix` (ex: "synopsis"): resolve o lote pendente em Python e anexa
    o caminho ao prompt, poupando os turnos de Glob/probe do agente. A regra é
    a mesma do prompt, então lotes órfãos continuam sendo drenados primeiro.

    Retorna (success, limit_persists):
      - success: True se o agente concluiu sem erro.
      - limit_persists: True se o output indica limite de sessão.
    """
    prompt = agent_prompt_path(prompt_name)

    extra_context = None
    if batch_prefix:
        pendente = pending_batch_input(str(BATCH_DIR), batch_prefix)
        if pendente:
            extra_context = input_hint(pendente)
            log(f"[LLM_ORCH] {label}: lote resolvido → {os.path.basename(pendente)}")

    log(f"[LLM_ORCH] → {label}: invocando claude CLI…")
    success, output = run_agent(prompt, timeout=timeout, wait_on_limit=False,
                                extra_context=extra_context)

    if success:
        log(f"[LLM_ORCH] ✓ {label} concluído")
        return True, False

    # Falha — distinguir auth (401), limite de sessão e outros erros
    if _is_auth_error(output):
        log(f"[LLM_ORCH] 🔑 {label} — ERRO DE AUTENTICAÇÃO (401). "
            f"A sessão do Claude CLI está inativa.")
        log(f"[LLM_ORCH]    Solução: abra um terminal, execute 'claude' e faça login, "
            f"depois reabra o pipeline.")
        raise ClaudeAuthError(f"agente '{label}' retornou 401 — sessão Claude CLI inativa")

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
        "log_analysis", "log_analysis_batch", timeout=TIMEOUT_MAINTENANCE
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
            bloqueados = _count_sem_descricao(conn, idioma)
            conn.close()
            if bloqueados:
                # Sem isto o relatório diria "nenhum pendente" com 10 mil livros
                # parados — o gargalo ficaria invisível justamente ao ser atingido.
                log(f"[LLM_ORCH] synopsis: 0 exportáveis, mas {bloqueados:,} livro(s) "
                    f"bloqueado(s) por falta de descrição — o gargalo é o "
                    f"enriquecimento, não a quota. Ver TASK-SYN-016.")
            break
        log(f"[LLM_ORCH] synopsis: {n} pendentes exportáveis")
        exported = _export_synopsis(conn, idioma)
        conn.close()
        if exported <= 0:
            break
        ok, limit_persists = _run_agent_step("synopsis", "synopsis_batch", timeout=900,
                                            batch_prefix="synopsis")
        if limit_persists:
            return done, True
        if ok:
            _import_synopsis()
            done += exported
        else:
            orphans = glob.glob(str(BATCH_DIR / "*_synopsis_input.json"))
            if orphans:
                log(
                    f"[LLM_ORCH] ⚠ synopsis timeout/erro — {len(orphans)} arquivo(s) "
                    f"input pendente(s) em batch/. Livros ficam em status_synopsis=3 "
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
        ok, limit_persists = _run_agent_step("classify", "classify_batch", timeout=900,
                                            batch_prefix="categorize")
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
        ok, limit_persists = _run_agent_step("author_bio", "author_bio", timeout=900,
                                            batch_prefix="author_bio")
        if limit_persists:
            return done, True
        if ok:
            done += _import_author_bio()
        else:
            break
    return done, False


def _auditoria_llm_vencida(conn):
    """Primeira auditoria LLM com o limiar estourado, ou None.

    O limiar vem de `pipeline_status._AUDIT_STEPS` via `audit_stale` — fonte
    única. Duplicá-lo aqui faria o painel de Status ("ok (<48h)") divergir do
    que o orquestrador gasta.
    """
    from steps import pipeline_status
    for label, modo in _AUDITORIAS_LLM:
        if pipeline_status.audit_stale(conn, label):
            return label, modo
    return None


def _rodar_auditoria_llm(label: str, modo: str, cota: int) -> tuple[int, bool]:
    """Roda UMA auditoria LLM no slot do ciclo. Retorna (0, limit_hit).

    Devolve 0 em `feitos` de propósito: auditoria não drena backlog de conteúdo,
    e contá-la como progresso enganaria o guard anti-giro do G — uma janela que
    só auditou seria lida como janela produtiva, e o loop multijanela seguiria
    girando sem publicar nada.

    `cota` é em LIVROS. Desde 2026-08-11 a auditoria é batch
    (`auditor.AUDIT_BATCH_SIZE`), então custa ceil(cota / AUDIT_BATCH_SIZE)
    chamadas — com os padrões, 1. Ver AUDIT_LLM_POR_CICLO no topo do módulo.
    """
    from steps import qa
    log(f"[LLM_ORCH] auditoria LLM '{label}' vencida — ocupando o slot "
        f"deste ciclo (modo={modo}, limit={cota})")
    try:
        qa.run(mode=modo, limit=cota, dry_run=False)
    except Exception as e:
        # Auditoria é diagnóstico: falha dela não pode derrubar o ciclo que
        # ainda vai gerar sinopse (o trabalho que de fato publica).
        log(f"[LLM_ORCH] AVISO: auditoria '{modo}' falhou: {e}")
    return 0, False


def _slot_secundario() -> tuple[int, bool]:
    """Resolve e executa o ÚNICO trabalho secundário do ciclo.

    Ver o bloco SLOT SECUNDÁRIO no topo do módulo para a medição que motivou
    trocar as duas rotações fixas por um slot só.

    Só gasta o slot em quem tem trabalho: se o dono da vez está sem pendências,
    passa a vez sem consumir chamada. O cursor avança ANTES de executar — se a
    chamada falhar, o slot foi gasto do mesmo jeito e a vez é do próximo.
    """
    if not SLOT_SECUNDARIO:
        # Comportamento anterior: as duas rotações fixas, 2 chamadas por ciclo.
        bio, hit = _rotacao_author_bio(BIO_POR_CICLO)
        if hit:
            return bio, True
        cls, hit = _rotacao_classify(CLASSIFY_POR_CICLO)
        return bio + cls, hit

    conn = get_conn()
    try:
        if AUDIT_LLM_POR_CICLO > 0:
            venc = _auditoria_llm_vencida(conn)
            if venc:
                label, modo = venc
                return _rodar_auditoria_llm(label, modo, AUDIT_LLM_POR_CICLO)

        pendentes = {
            "author_bio": _count_pending_author_bio(conn),
            "classify":   _count_pending_classify(conn),
        }
    finally:
        conn.close()

    cursor = 0
    try:
        cursor = int(kv_state.get(_CURSOR_KEY, "0") or 0) % len(_RODIZIO_SLOT)
    except (TypeError, ValueError):
        cursor = 0

    for i in range(len(_RODIZIO_SLOT)):
        nome = _RODIZIO_SLOT[(cursor + i) % len(_RODIZIO_SLOT)]
        if pendentes.get(nome, 0) <= 0:
            continue                       # sem trabalho: não gasta o slot
        kv_state.set(_CURSOR_KEY, (cursor + i + 1) % len(_RODIZIO_SLOT))

        if nome == "author_bio":
            feitos, hit = _rotacao_author_bio(BIO_POR_CICLO)
            if feitos:
                log(f"[LLM_ORCH] author_bio (slot): {feitos} bio(s) geradas neste ciclo")
            return feitos, hit

        feitos, hit = _rotacao_classify(CLASSIFY_POR_CICLO)
        if feitos:
            # "enviados", não "categorizados": o lote processado pode ser um
            # órfão anterior, não o que acabou de ser exportado.
            log(f"[LLM_ORCH] classify (slot): {feitos} livro(s) enviados ao classificador")
        return feitos, hit

    log("[LLM_ORCH] slot secundário: nada pendente (bios e categorização) — skip")
    return 0, False


def _rotacao_author_bio(cota: int) -> tuple[int, bool]:
    """Gera até `cota` bios — UM lote — no início do ciclo. Retorna (feitas, limit_hit).

    Por que existe: `_drain_author_bio` só é alcançado depois de sinopse E
    categorização zerarem. Medido em 2026-07-25, isso são ~1.300 lotes contra
    uma janela de 5h que não chega perto disso, então as bios ficavam em fome
    permanente — 8.034 autores sem bio e 0 gerada por janela.

    A rotação roda ANTES da sinopse de propósito. Rodar depois seria idêntico
    a não rodar: a janela acaba na sinopse e o fluxo nunca chega aqui.

    ⚠ CORREÇÃO (2026-08-09): estava escrito aqui que a cota padrão é "~1 lote
    contra as centenas gastas em sinopse". **Não são centenas: são 3-4.** Medido
    nos logs de 2026-08-04/05/06 (n=3), uma janela da sessão PRO comporta 5-6
    chamadas no total. Esta rotação custava, sozinha, ~17-20% da janela — e
    junto com a de classify, 33-40%. Por isso deixou de ser chamada
    incondicionalmente: hoje ela disputa o slot único (`_slot_secundario`), que
    é onde a conta de custo vive.
    """
    if cota <= 0:
        return 0, False

    conn = get_conn()
    try:
        n = _count_pending_author_bio(conn)
        if n <= 0:
            return 0, False
        log(f"[LLM_ORCH] author_bio (rotação): {n} pendentes — cota de {cota} neste ciclo")
        exportados = _export_author_bio(conn, limite=cota)
    finally:
        conn.close()

    if exportados <= 0:
        return 0, False

    ok, limit_persists = _run_agent_step("author_bio", "author_bio", timeout=900,
                                         batch_prefix="author_bio")
    if limit_persists:
        return 0, True

    if not ok:
        return 0, False

    return _import_author_bio(), False


def _rotacao_classify(cota: int) -> tuple[int, bool]:
    """Categoriza até `cota` livros — UM lote — no início do ciclo.

    Mesma justificativa da rotação de bios (`_rotacao_author_bio`): a fase de
    categorização fica atrás da sinopse, que não zera numa janela de 5h, então
    nunca era alcançada. Diferença: aqui o prejuízo já está no ar — 2.620 dos
    4.403 livros publicados (60%, medido em 2026-07-25) estão no site sem
    categoria temática, fora das páginas de categoria e das listas.

    Categorização é barata em TEMPO (~6,5 s/livro contra ~26 s/livro da
    sinopse), mas não em CHAMADAS — e a chamada é a unidade que a sessão PRO
    limita. Medido em 2026-08-09: a janela tem 5-6 chamadas, então este lote
    cheio custa ~17-20% dela. Por isso a rotação passou a disputar o slot único
    (`_slot_secundario`) em vez de rodar em todo ciclo.

    ⚠ Diferença em relação à rotação de bios: categorização **entra** em
    `_content_backlog()`, que é o que o guard anti-giro do G compara entre
    janelas. Logo, uma janela em que só a rotação de classify progrediu conta
    como progresso e o loop multijanela continua. Isso é correto — o backlog de
    conteúdo realmente diminuiu —, mas significa que, com a sinopse travada, o
    G segue rodando enquanto houver categorização a fazer (até ~555 janelas no
    backlog de 2026-07-25). Para encerrar antes, Ctrl+C ou CLASSIFY_POR_CICLO=0.
    """
    if cota <= 0:
        return 0, False

    conn = get_conn()
    try:
        n = _count_pending_classify(conn)
        if n <= 0:
            return 0, False
        log(f"[LLM_ORCH] classify (rotação): {n} pendentes — cota de {cota} neste ciclo")
        exportados = _export_classify(conn, limite=cota)
    finally:
        conn.close()

    if exportados <= 0:
        return 0, False

    ok, limit_persists = _run_agent_step("classify", "classify_batch", timeout=900,
                                         batch_prefix="categorize")
    if limit_persists:
        return 0, True

    if not ok:
        return 0, False

    _import_classify()

    # Retorna o EXPORTADO, não o categorizado — igual a `_drain_classify`. Os
    # dois números divergem de propósito: `_run_agent_step` resolve o lote de
    # MENOR número ainda sem output, que pode ser um órfão de ciclo anterior
    # (medido em 2026-07-25: 5 órfãos acumulados). O ciclo então exporta o lote
    # N e processa o órfão N-k — defasagem de um lote, herdada do desenho e
    # desejável, porque senão os órfãos nunca seriam drenados.
    return exportados, False


def _content_backlog(idioma: str) -> int:
    """Soma do backlog de conteúdo que destrava publicação (sinopse + categoria)."""
    conn = get_conn()
    try:
        return _count_pending_synopsis(conn, idioma) + _count_pending_classify(conn)
    finally:
        conn.close()


# =========================
# ESPERA DE RESET (não-bloqueante para o run_agent)
# =========================

def _wait_for_session_reset():
    """Aguarda o reset da sessão PRO confirmado via probe real (não por timer).

    Usa o mesmo mecanismo de _wait_and_probe do claude_runner: sonda a cada
    _PROBE_INTERVAL min em vez de depender do SESSION_RESET_MINUTES, evitando
    o dessincronismo onde a janela real é menor que o timer estimado.
    """
    import time as _time
    import os as _os
    from core.claude_runner import (
        _invoke, _PROBE_PROMPT, _PROBE_TIMEOUT,
        _PROBE_INITIAL_WAIT, _PROBE_INTERVAL, MAX_QUOTA_PROBES,
    )
    from core import claude_usage_tracker as _tracker

    env = {**_os.environ}
    log(f"[LLM_ORCH] Aguardando reset de sessão — primeira probe em {_PROBE_INITIAL_WAIT} min, "
        f"intervalo {_PROBE_INTERVAL} min.")
    _time.sleep(_PROBE_INITIAL_WAIT * 60)

    for attempt in range(1, MAX_QUOTA_PROBES + 1):
        log(f"[LLM_ORCH] Probe {attempt}/{MAX_QUOTA_PROBES}: verificando restauração de quota…")
        probe_ok, probe_out = _invoke(_PROBE_PROMPT, _PROBE_TIMEOUT, env)
        probe_limit = _tracker.record_call(probe_ok, probe_out)
        if not probe_limit:
            log("[LLM_ORCH] Sessão resetada — retomando fase LLM.")
            return
        if attempt < MAX_QUOTA_PROBES:
            log(f"[LLM_ORCH] Ainda limitada. Nova probe em {_PROBE_INTERVAL} min…")
            _time.sleep(_PROBE_INTERVAL * 60)

    log("[LLM_ORCH] AVISO: quota não restaurada após todas as probes. Retomando mesmo assim.")


# =========================
# MAIN CYCLE
# =========================

def run(idioma: str, wait_for_reset: bool = True):
    """Autopilot LLM cíclico — processa sinopses, categorias, bios e ofertas.

    Priorização (WS1): a janela de sessão PRO é gasta PRIMEIRO no gargalo
    (sinopse), depois categorização e bios — esvaziando cada um (vários lotes)
    antes de tocar nos agentes não-críticos. Estes só rodam quando o backlog de
    conteúdo está zerado e ainda há sessão disponível.

    A cada N ciclos também gera relatórios de log e consistência (sem aplicar
    correções inline — leitura e aplicação são responsabilidade de rotina externa).

    Fallback ao esgotar a sessão PRO (cadeia de custo zero):
      1. Autopilot A não-LLM (publica o que já foi gerado + ataca backlog não-LLM).
      2. Se `wait_for_reset=True` (opção O): aguarda o reset da sessão e RETOMA a
         fase LLM (loop ininterrupto através das janelas de 5h).
         Se `wait_for_reset=False` (opção G, passe único): ENCERRA e devolve o
         controle ao orquestrador G (que faz QA + Autopilot A + relatório).
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
    ended_on_limit = False   # True se o passe único (G) encerrou por limite de sessão

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
        _startup_outputs = glob.glob(str(BATCH_DIR / "*_synopsis_output.json"))
        if _startup_outputs:
            log(f"[LLM_ORCH] synopsis: {len(_startup_outputs)} output(s) pendente(s) de ciclo(s) anterior(es) — importando…")
            _import_synopsis()
            cycle_done += len(_startup_outputs)

        # ── FASE A — CONTEÚDO (prioridade): esvaziar o gargalo ───
        # Sinopse primeiro (maior gargalo, hard-block do Quality Gate), depois
        # categorização, depois bios — cada um drenado em vários lotes.
        # ClaudeAuthError aborta imediatamente: sessão inativa, aguardar não ajuda.
        try:
            # UM slot secundário ANTES da sinopse. A posição é o mecanismo:
            # depois seria o mesmo que não rodar, porque a janela acaba na
            # sinopse e o fluxo nunca chega aqui. O que mudou em 2026-08-09 foi
            # a LARGURA — eram 2 chamadas fixas (bio + classify) de uma janela
            # que só tem 5-6; agora é 1, disputada por auditoria vencida ou pelo
            # rodízio. Ver o bloco SLOT SECUNDÁRIO no topo do módulo.
            slot_done, cycle_limit_hit = _slot_secundario()
            cycle_done += slot_done

            if not cycle_limit_hit:
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

        except ClaudeAuthError as e:
            log(f"[LLM_ORCH] ⛔ Orquestrador encerrado por erro de autenticação: {e}")
            log("[LLM_ORCH]    Abra um terminal, execute 'claude' e faça login antes de rodar novamente.")
            break

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
                            "scripts/data/batch/*_consistency.json",
                            "scripts/data/batch/*_consistency_actions.json",
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

        # ── AUTOPILOT NÃO-LLM (publicação periódica) ─────────
        # Após imports, publica os livros desbloqueados (QG → Publish → Listas).
        # No caminho de limite, o Autopilot A roda no bloco de fallback abaixo
        # (guard `not cycle_limit_hit` evita rodar duas vezes no mesmo ciclo).
        if cycle_done > 0 and not cycle_limit_hit:
            log("[LLM_ORCH] Executando autopilot não-LLM para processar resultados importados...")
            try:
                # manter_batch=False: o orquestrador já gera os inputs LLM no
                # drain; o top-up de batch aqui só criaria status_synopsis=3 preso
                # (sem consumidor externo no fluxo automático O/G).
                autopilot.run(idioma, PACOTE_AUTOPILOT, manter_batch=False)
            except Exception as e:
                log(f"[LLM_ORCH] AVISO: autopilot retornou com exceção: {e}")

        # ── FIM DO CICLO ─────────────────────────────────────
        log(f"[LLM_ORCH] Ciclo {cycle} concluído — trabalho realizado: {cycle_done}"
            + (" | ⛔ limite de sessão atingido" if cycle_limit_hit else ""))

        if cycle_limit_hit:
            # FALLBACK DE CUSTO ZERO: roda Autopilot A não-LLM (publica o que já
            # foi gerado nesta janela + ataca o backlog não-LLM) ANTES de aguardar.
            log("[LLM_ORCH] Limite de sessão — fallback Autopilot não-LLM (publica + drena backlog não-LLM)…")
            try:
                # manter_batch=False: evita o churn de batch (status=3 preso)
                # observado no log pipeline_2026-06-02 — o drain do orquestrador
                # gera os inputs; não há consumidor externo no fluxo automático.
                autopilot.run(idioma, PACOTE_AUTOPILOT, manter_batch=False)
            except Exception as e:
                log(f"[LLM_ORCH] AVISO: autopilot retornou com exceção: {e}")

            if not wait_for_reset:
                log("[LLM_ORCH] Passe único: fase LLM encerrada (limite de sessão). "
                    "Controle devolvido ao orquestrador (QA + relatório).")
                ended_on_limit = True
                break

            # Opção O: aguarda o reset (descontando o tempo já gasto no Autopilot A)
            # e RETOMA a fase LLM no próximo ciclo.
            _wait_for_session_reset()
            cycle_limit_hit = False
            continue

        if cycle_done == 0:
            log("[LLM_ORCH] Nenhum trabalho pendente em nenhum agente.")
            log("[LLM_ORCH] Orquestrador encerrado.")
            break

    log(f"[LLM_ORCH] ══════════════════════════════════════")
    log(f"[LLM_ORCH] Total de ciclos: {cycle}")
    log(f"[LLM_ORCH] ══════════════════════════════════════")

    # ended_on_limit=True só no passe único (G) que parou por limite de sessão —
    # sinaliza ao orquestrador G que vale tentar um retry após o fallback longo
    # (quando a janela de 5h provavelmente já resetou). No modo O (wait_for_reset)
    # o loop só sai por trabalho exaurido/auth, então retorna False.
    return ended_on_limit
