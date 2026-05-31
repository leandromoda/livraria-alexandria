# ============================================================
# STEP 0 — PIPELINE STATUS
# Livraria Alexandria
#
# Painel de situação do pipeline: funil de livros,
# contadores por step, gargalos evidenciados,
# histórico de execuções e controle de auditoria.
# Não modifica dados — só leitura.
# ============================================================

import json
from datetime import datetime, timezone
from pathlib import Path

from core.db import get_conn
from core.logger import log


# =========================
# CAMINHOS
# =========================

_SCRIPTS_DIR = Path(__file__).resolve().parents[1]
_DATA_DIR    = _SCRIPTS_DIR / "data"
_LOGS_DIR    = _DATA_DIR / "logs"

GARGALO_PLAN_PATH = _DATA_DIR / "gargalo_plan.json"


# =========================
# REGISTROS DE STEPS
# =========================

# (label_exibição, [variantes de step_name em pipeline_runs])
_PIPELINE_STEPS = [
    ("1  Importar Seeds",      ["1  Seeds",              "offer_seed"]),
    ("3  Resolver Ofertas",    ["3  Resolver Ofertas",    "offer_resolver"]),
    ("4  Scraper Marketplace", ["4  Scraper",             "marketplace_scraper"]),
    ("5  Gerar Slugs",         ["5  Slugs",               "slugify"]),
    ("6  Slugify Autores",     ["6  Slugs Autores",       "slugify_autores"]),
    ("7  Dedup Autores",       ["7  Dedup Autores",       "dedup_autores"]),
    ("8  Deduplicar",          ["8  Dedup",               "dedup"]),
    ("9  Review",              ["9  Review",              "review"]),
    ("10 Categorizar (LLM)",   ["10 Categorizar",         "categorize"]),
    ("11 Sinopses (LLM)",      ["11 Sinopses",            "synopsis"]),
    ("12 Capas",               ["12 Capas",               "covers"]),
    ("13 Quality Gate",        ["13 Quality Gate",        "quality_gate"]),
    ("14 Publicar Livros",     ["14 Publicar Livros",     "publish"]),
    ("15 Publicar Autores",    ["15 Publicar Autores",    "publish_autores"]),
    ("16 Publicar Cats",       ["16 Publicar Cats",       "publish_categorias"]),
    ("17 Publicar Ofertas",    ["17 Publicar Ofertas",    "publish_ofertas"]),
    ("18 Listas SEO",          ["18 Listas SEO",          "list_composer"]),
    ("19 Publicar Listas",     ["19 Publicar Listas",     "publish_listas"]),
    ("20 Monitor Preços",      ["offer_price_monitor",    "20 Monitor Precos"]),
    ("23 Reparar Publicações", ["repair",                 "23"]),
    ("25 Apply Blacklist",     ["apply_blacklist",        "25 Apply Blacklist"]),
    ("29 Bios de Autores",     ["author_bio",             "29"]),
]

# (label, [pipeline_runs variants], glob_pattern_em_logs, max_age_hours)
_AUDIT_STEPS = [
    ("21 Conectividade",     [],                     "*connectivity*",   24),
    ("22 Conteúdo (LLM)",   [],                     "*content*",        48),
    ("28 Integridade",       ["autopilot_audit"],    None,               12),
    ("29 Listas SEO",        [],                     "*audit_list*",     48),
    ("30 Autores sem bio",   [],                     "*author_bio*",     72),
    ("31 Título Verac.",     [],                     "*title_verify*",  168),
    ("32 Consistência",      ["consistency_check"],  "*consistency*",    48),
]

# (label, [pipeline_runs variants], Path opcional para fallback mtime)
_LLM_OUTPUT_STEPS = [
    ("Blacklist aplicada",  ["apply_blacklist"],   _DATA_DIR / "blacklist.json"),
    ("LLM Orchestrator",    ["llm_orchestrator"],  None),
    ("Cowork Import",       ["cowork_import"],     None),
    ("Offer List Importer", ["offer_list_importer"], None),
]


# =========================
# HELPERS BÁSICOS
# =========================

def pct(part, total):
    if not total:
        return 0.0
    return part / total * 100


def bar(part, total, width=20):
    filled = int(pct(part, total) / 100 * width)
    return "█" * filled + "░" * (width - filled)


def q(conn, sql, *params):
    """Executa query e retorna primeiro valor, ou 0 se falhar."""
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        row = cur.fetchone()
        return row[0] if row else 0
    except Exception:
        return 0


# =========================
# SESSÃO CLAUDE PRO (WS7)
# =========================

def _print_session_pro():
    """Painel da janela de sessão PRO (quota do plano via claude CLI).

    Mostra quantas chamadas foram feitas na janela atual e, se um limite foi
    atingido, quanto falta para o reset — permite decidir entre seguir gastando
    a janela no gargalo, aguardar o reset ou cair para fallback não-LLM.
    """
    try:
        from core.claude_usage_tracker import session_window, SESSION_RESET_MINUTES
    except Exception:
        return

    win = session_window()
    sep = "─" * 62

    print()
    print(f"  SESSÃO CLAUDE PRO (janela {SESSION_RESET_MINUTES}min)")
    print(f"  {sep}")
    print(f"    Chamadas na janela atual: {win['session_calls']:,}")

    if win["in_cooldown"]:
        secs = win["seconds_until_reset"]
        h, rem = divmod(secs, 3600)
        m = rem // 60
        falta = f"{h}h{m:02d}min" if h else f"{m}min"
        reset_local = ""
        if win.get("reset_at"):
            try:
                rt = datetime.fromisoformat(win["reset_at"])
                reset_local = f" (reset às {rt.strftime('%H:%M UTC')})"
            except (ValueError, TypeError):
                pass
        print(f"    ⚠  LIMITE ATINGIDO — aguardando reset: faltam {falta}{reset_local}")
    else:
        print("    ✓  Janela disponível — sem cooldown ativo")


# =========================
# HELPERS DE HISTÓRICO
# =========================

def _fmt_age(dt):
    """Retorna string legível da idade de um datetime (pode ser None)."""
    if dt is None:
        return "nunca"
    try:
        now = datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = now - dt
        h = delta.total_seconds() / 3600
        if h < 1:
            mins = max(1, int(delta.total_seconds() / 60))
            return f"{mins}min atrás"
        elif h < 24:
            return f"{int(h)}h atrás"
        elif h < 48:
            return f"ontem {dt.strftime('%H:%M')}"
        else:
            d = int(h / 24)
            return f"{d}d {dt.strftime('%H:%M')}"
    except Exception:
        return "?"


def _last_run_db(conn, step_names):
    """Retorna (datetime|None, status|None) da última execução de qualquer um dos step_names."""
    if not step_names:
        return None, None
    try:
        ph = ",".join("?" * len(step_names))
        cur = conn.cursor()
        cur.execute(
            f"SELECT started_at, status FROM pipeline_runs "
            f"WHERE step_name IN ({ph}) ORDER BY started_at DESC LIMIT 1",
            step_names,
        )
        row = cur.fetchone()
        if row:
            try:
                dt = datetime.fromisoformat(row[0])
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt, row[1]
            except Exception:
                return None, row[1]
    except Exception:
        pass
    return None, None


def _last_file_time(glob_pattern):
    """Retorna mtime do arquivo mais recente que bate com glob_pattern em _LOGS_DIR."""
    if not _LOGS_DIR.exists():
        return None
    try:
        files = sorted(
            _LOGS_DIR.glob(glob_pattern),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        if files:
            return datetime.fromtimestamp(files[0].stat().st_mtime, tz=timezone.utc)
    except Exception:
        pass
    return None


def _file_mtime(path):
    """Retorna mtime de um arquivo específico, ou None."""
    try:
        if path and path.exists():
            return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except Exception:
        pass
    return None


def _count_pending_audit_logs():
    """Conta JSONs em data/logs/ ainda não arquivados em processed_logs/."""
    if not _LOGS_DIR.exists():
        return 0
    try:
        processed_dir = _LOGS_DIR / "processed_logs"
        processed = (
            {f.name for f in processed_dir.iterdir() if f.is_file()}
            if processed_dir.exists() else set()
        )
        pending = [f for f in _LOGS_DIR.glob("*.json") if f.is_file() and f.name not in processed]
        return len(pending)
    except Exception:
        return 0


# =========================
# SEEDS PENDENTES
# =========================

def count_seeds_pendentes(conn):
    """Conta arquivos NNN_offer_seed(s).json ainda não ingeridos."""
    seeds_dir = _SCRIPTS_DIR / "data" / "seeds"
    if not seeds_dir.exists():
        return 0
    arquivos = list(seeds_dir.glob("*_offer_seed*.json"))
    if not arquivos:
        return 0
    try:
        cur = conn.cursor()
        cur.execute("SELECT filename FROM seed_imports")
        ingeridos = {r[0] for r in cur.fetchall()}
    except Exception:
        ingeridos = set()
    return len([f for f in arquivos if f.name not in ingeridos])


# =========================
# SEÇÕES DE HISTÓRICO
# =========================

def _print_step_history(conn):
    """Exibe última execução de cada step principal do pipeline."""
    sep = "─" * 62
    W_LABEL, W_AGE = 26, 16
    print()
    print("  ÚLTIMA EXECUÇÃO — STEPS PRINCIPAIS")
    print(f"  {sep}")
    print(f"  {'Step':<{W_LABEL}}  {'Última exec.':<{W_AGE}}  Status")
    print(f"  {'─'*W_LABEL}  {'─'*W_AGE}  ──────")
    for label, step_names in _PIPELINE_STEPS:
        dt, status = _last_run_db(conn, step_names)
        age = _fmt_age(dt)
        if dt is None:
            icon = "–"
        elif status == "success":
            icon = "✓"
        elif status == "error":
            icon = "✗"
        else:
            icon = "·"
        print(f"  {label:<{W_LABEL}}  {age:<{W_AGE}}  {icon}")


def _print_audit_history(conn):
    """Exibe situação dos steps de auditoria e processamento LLM de outputs."""
    sep = "─" * 62
    now = datetime.now(timezone.utc)
    W_LABEL, W_AGE = 24, 16

    # ── Audit steps ──────────────────────────────────────────
    print()
    print("  AUDITORIA — ÚLTIMA EXECUÇÃO E SITUAÇÃO")
    print(f"  {sep}")
    print(f"  {'Step':<{W_LABEL}}  {'Última exec.':<{W_AGE}}  Situação")
    print(f"  {'─'*W_LABEL}  {'─'*W_AGE}  ────────")

    stale_labels = []
    for label, step_names, log_pattern, max_age_h in _AUDIT_STEPS:
        dt_db, _ = _last_run_db(conn, step_names)
        dt_file  = _last_file_time(log_pattern) if log_pattern else None
        candidates = [d for d in [dt_db, dt_file] if d is not None]
        dt = max(candidates) if candidates else None

        age = _fmt_age(dt)
        if dt is None:
            icon, situacao = "–", "nunca executado"
            stale_labels.append(label)
        else:
            h_ago = (now - dt).total_seconds() / 3600
            if h_ago > max_age_h:
                icon, situacao = "⚠", f"stale (limite {max_age_h}h)"
                stale_labels.append(label)
            else:
                icon, situacao = "✓", f"ok (<{max_age_h}h)"

        print(f"  {label:<{W_LABEL}}  {age:<{W_AGE}}  {icon} {situacao}")

    # ── LLM output processing ─────────────────────────────────
    print()
    print("  LLM — PROCESSAMENTO DE OUTPUTS DE AUDITORIA")
    print(f"  {sep}")
    print(f"  {'Ação':<{W_LABEL}}  {'Última exec.':<{W_AGE}}  Status")
    print(f"  {'─'*W_LABEL}  {'─'*W_AGE}  ──────")

    for label, step_names, file_path in _LLM_OUTPUT_STEPS:
        dt_db, status = _last_run_db(conn, step_names)
        dt_file = _file_mtime(file_path)
        candidates = [d for d in [dt_db, dt_file] if d is not None]
        dt = max(candidates) if candidates else None

        age = _fmt_age(dt)
        if dt is None:
            icon = "–"
        elif status == "error":
            icon = "✗"
        else:
            icon = "✓"
        print(f"  {label:<{W_LABEL}}  {age:<{W_AGE}}  {icon}")

    # ── Pending audit logs ────────────────────────────────────
    n_pending = _count_pending_audit_logs()
    if n_pending > 0:
        print()
        print(f"  ⚠  {n_pending} arquivo(s) em data/logs/ aguardando revisão LLM")

    return stale_labels


# =========================
# GARGALO PLAN
# =========================

def build_gargalo_plan(conn, idioma="PT"):
    """
    Analisa o estado atual do pipeline e constrói um plano
    priorizado de steps para atacar os gargalos.

    Salva em data/gargalo_plan.json e retorna o dict.

    Lógica de priorização:
      1. Steps de auditoria stale (não-LLM) → executáveis automaticamente
      2. Apply Blacklist se houver entradas pendentes
      3. Gargalos de pipeline não-LLM com mais pendentes
      4. Steps LLM bloqueados (informativo — não auto-executáveis)
      5. Autopilot A (sempre ao final)
    """
    now = datetime.now(timezone.utc)
    steps = []
    order = 1

    # ── 1. Audit steps stale ─────────────────────────────────
    _AUTO_KEY = {
        "21 Conectividade":   "audit_connectivity",
        "28 Integridade":     "autopilot_audit",
        "29 Listas SEO":      "audit_list",
        "30 Autores sem bio": "audit_author_bios",
        "32 Consistência":    "consistency_check",
    }
    _LLM_KEY = {
        "22 Conteúdo (LLM)": "audit_content",
        "31 Título Verac.":   "audit_title_verify",
    }

    for label, step_names, log_pattern, max_age_h in _AUDIT_STEPS:
        dt_db, _ = _last_run_db(conn, step_names)
        dt_file  = _last_file_time(log_pattern) if log_pattern else None
        candidates = [d for d in [dt_db, dt_file] if d is not None]
        dt = max(candidates) if candidates else None

        stale = dt is None or (now - dt).total_seconds() / 3600 > max_age_h
        if not stale:
            continue

        reason = "nunca executado" if dt is None else f"stale — não roda há >{max_age_h}h"

        if label in _AUTO_KEY:
            steps.append({
                "order":  order,
                "type":   "audit",
                "key":    _AUTO_KEY[label],
                "label":  label,
                "reason": reason,
                "auto":   True,
            })
        else:
            num = label.split()[0]
            steps.append({
                "order":  order,
                "type":   "audit_llm",
                "key":    _LLM_KEY.get(label, label),
                "label":  label,
                "reason": f"{reason} — requer LLM (menu 5 → {num})",
                "auto":   False,
            })
        order += 1

    # ── 2. Blacklist pendente ─────────────────────────────────
    try:
        bl_path = _DATA_DIR / "blacklist.json"
        if bl_path.exists():
            bl_data = json.loads(bl_path.read_text(encoding="utf-8"))
            if isinstance(bl_data, list) and bl_data:
                steps.append({
                    "order":   order,
                    "type":    "maintenance",
                    "key":     "apply_blacklist",
                    "label":   "25 Apply Blacklist",
                    "pending": len(bl_data),
                    "reason":  f"{len(bl_data)} entradas pendentes em blacklist.json",
                    "auto":    True,
                })
                order += 1
    except Exception:
        pass

    # ── 3. Gargalos pipeline não-LLM ─────────────────────────
    try:
        from steps.autopilot import _count_per_step
        counts = _count_per_step(conn)

        _GARGALO_MAP = {
            "2  Enriquecer Desc":   "enrich_descricao",
            "3  Resolver Ofertas":  "offer_resolver",
            "4  Scraper":           "marketplace_scraper",
            "5  Slugs":             "slugify",
            "8  Dedup":             "dedup",
            "9  Review":            "review",
            "12 Capas":             "covers",
            "13 Quality Gate":      "quality_gate",
            "14 Publicar Livros":   "publish",
            "15 Publicar Autores":  "publish_autores",
            "16 Publicar Cats":     "publish_categorias",
            "17 Publicar Ofertas":  "publish_ofertas",
            "19 Publicar Listas":   "publish_listas",
        }

        bottlenecks = sorted(
            [(n, c) for n, c in counts.items() if c > 0 and n in _GARGALO_MAP],
            key=lambda x: -x[1],
        )

        for name, cnt in bottlenecks[:6]:
            steps.append({
                "order":   order,
                "type":    "pipeline",
                "key":     _GARGALO_MAP[name],
                "label":   name,
                "pending": cnt,
                "reason":  f"{cnt} itens pendentes — cobertos pelo Autopilot A",
                "auto":    True,
            })
            order += 1
    except Exception:
        pass

    # ── 4. Gargalos LLM (informativo) ────────────────────────
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM livros WHERE status_categorize = 0 AND status_review = 1"
        )
        n_cat = cur.fetchone()[0]
        cur.execute(
            "SELECT COUNT(*) FROM livros WHERE status_synopsis = 0 AND status_review = 1"
        )
        n_syn = cur.fetchone()[0]

        if n_cat > 0:
            steps.append({
                "order":   order,
                "type":    "llm",
                "key":     "categorize",
                "label":   "10 Categorizar",
                "pending": n_cat,
                "reason":  f"{n_cat} livros aguardando categorização LLM (use C ou O)",
                "auto":    False,
            })
            order += 1

        if n_syn > 0:
            steps.append({
                "order":   order,
                "type":    "llm",
                "key":     "synopsis",
                "label":   "11 Sinopses",
                "pending": n_syn,
                "reason":  f"{n_syn} livros aguardando sinopse LLM (use C ou O)",
                "auto":    False,
            })
            order += 1
    except Exception:
        pass

    # ── 5. Autopilot A (sempre ao final) ─────────────────────
    steps.append({
        "order":  order,
        "type":   "autopilot",
        "key":    "autopilot",
        "label":  "A  Autopilot",
        "reason": "Consolidar progresso — todos os steps não-LLM até exaustão",
        "auto":   True,
    })

    plan = {
        "generated_at": now.isoformat(),
        "idioma": idioma,
        "steps": steps,
    }

    try:
        GARGALO_PLAN_PATH.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass

    return plan


# =========================
# RUN
# =========================

def run():

    conn = get_conn()

    # ── Livros ──────────────────────────────────────────────────
    total = q(conn, "SELECT COUNT(*) FROM livros")

    if not total:
        log("[STATUS] Banco vazio — nenhum livro importado.")
        conn.close()
        return

    # Por idioma
    cur = conn.cursor()
    cur.execute("""
        SELECT COALESCE(idioma, 'UNKNOWN'), COUNT(*)
        FROM livros
        GROUP BY 1
        ORDER BY 2 DESC
    """)
    por_idioma = cur.fetchall()

    # Funil principal
    com_descricao      = q(conn, "SELECT COUNT(*) FROM livros WHERE descricao IS NOT NULL AND trim(descricao) != ''")
    com_offer_url      = q(conn, "SELECT COUNT(*) FROM livros WHERE offer_url IS NOT NULL AND trim(offer_url) != ''")
    com_scraper        = q(conn, "SELECT COUNT(*) FROM livros WHERE status_enrich IN (1, 2)")
    com_slug           = q(conn, "SELECT COUNT(*) FROM livros WHERE status_slug = 1")
    deduplicados       = q(conn, "SELECT COUNT(*) FROM livros WHERE status_dedup = 1")
    revisados          = q(conn, "SELECT COUNT(*) FROM livros WHERE status_review = 1")
    categorizados      = q(conn, "SELECT COUNT(*) FROM livros WHERE status_categorize = 1")
    com_sinopse        = q(conn, "SELECT COUNT(*) FROM livros WHERE status_synopsis = 1")
    com_capa           = q(conn, "SELECT COUNT(*) FROM livros WHERE status_cover IN (1, 2)")
    publicaveis        = q(conn, "SELECT COUNT(*) FROM livros WHERE is_publishable = 1")
    publicados         = q(conn, "SELECT COUNT(*) FROM livros WHERE status_publish = 1")
    oferta_publicada   = q(conn, "SELECT COUNT(*) FROM livros WHERE status_publish_oferta = 1")

    pub_categorias = q(conn, """
        SELECT COUNT(DISTINCT livro_id) FROM livros_categorias_tematicas
    """)

    # Pendentes (gargalos)
    revisados_sem_sinopse  = q(conn, "SELECT COUNT(*) FROM livros WHERE status_review = 1 AND status_synopsis = 0")
    com_sinopse_sem_gate   = q(conn, "SELECT COUNT(*) FROM livros WHERE status_synopsis = 1 AND (is_publishable IS NULL OR is_publishable = 0)")
    publicaveis_nao_pub    = q(conn, "SELECT COUNT(*) FROM livros WHERE is_publishable = 1 AND status_publish = 0")
    pub_sem_oferta         = q(conn, "SELECT COUNT(*) FROM livros WHERE status_publish = 1 AND status_publish_oferta = 0 AND offer_url IS NOT NULL")

    # ── Autores ─────────────────────────────────────────────────
    total_autores      = q(conn, "SELECT COUNT(*) FROM autores")
    autores_publicados  = q(conn, "SELECT COUNT(*) FROM autores WHERE status_publish = 1")
    autores_pendentes   = total_autores - autores_publicados

    # ── Seeds ───────────────────────────────────────────────────
    seeds_pendentes = count_seeds_pendentes(conn)

    # ── Ofertas ─────────────────────────────────────────────────
    total_com_oferta    = q(conn, "SELECT COUNT(*) FROM livros WHERE offer_url IS NOT NULL")
    oferta_ativa        = q(conn, "SELECT COUNT(*) FROM livros WHERE COALESCE(offer_status, 'active') = 'active' AND offer_url IS NOT NULL")
    oferta_indisponivel = q(conn, "SELECT COUNT(*) FROM livros WHERE offer_status = 'unavailable'")

    # ── Listas ──────────────────────────────────────────────────
    total_listas      = q(conn, "SELECT COUNT(*) FROM listas")
    listas_publicadas = q(conn, "SELECT COUNT(*) FROM listas WHERE status_publish = 1")

    conn.close()

    # ── Exibição ─────────────────────────────────────────────────
    sep = "─" * 62

    print()
    print("=" * 62)
    print("  LIVRARIA ALEXANDRIA — STATUS DO PIPELINE")
    print("=" * 62)

    # Seeds
    print()
    print(f"  SEEDS AGUARDANDO INGESTÃO: {seeds_pendentes} arquivo(s)")

    # Livros por idioma
    print()
    print(f"  LIVROS — TOTAL: {total:,}")
    print(f"  {sep}")
    for lang, cnt in por_idioma:
        print(f"    {lang:<10} {cnt:>5,}  {bar(cnt, total, 16)}  {pct(cnt, total):5.1f}%")

    # Funil
    steps_funil = [
        ("1  Importados",         total,            total),
        ("2  Com descrição",       com_descricao,    total),
        ("3  Com offer_url",       com_offer_url,    total),
        ("4  Marketplace scraper", com_scraper,      total),
        ("5  Com slug",            com_slug,         total),
        ("8  Deduplicados",        deduplicados,     total),
        ("9  Com review",          revisados,        total),
        ("10 Categorizados",       categorizados,    total),
        ("11 Com sinopse",         com_sinopse,      total),
        ("12 Com capa",            com_capa,         total),
        ("13 Publicáveis (gate)",  publicaveis,      total),
        ("14 Publicados",          publicados,       total),
        ("16 Cat. pub. (livros)",  pub_categorias,   total),
        ("17 Oferta publicada",    oferta_publicada, total),
    ]

    print()
    print("  FUNIL DO PIPELINE")
    print(f"  {sep}")

    prev = total
    for label, cnt, base in steps_funil:
        drop = prev - cnt if label != "1  Importados" else 0
        drop_str = f"  (↓{drop:,})" if drop > 0 else ""
        print(f"  Step {label:<24} {cnt:>5,}  {bar(cnt, base, 16)}  {pct(cnt, base):5.1f}%{drop_str}")
        prev = cnt

    # Gargalos
    gargalos = []
    if revisados_sem_sinopse > 0:
        gargalos.append(f"Step 11 (Sinopses):         {revisados_sem_sinopse:>5,} com review mas sem sinopse")
    if com_sinopse_sem_gate > 0:
        gargalos.append(f"Step 13 (Quality Gate):     {com_sinopse_sem_gate:>5,} com sinopse mas não publicáveis")
    if publicaveis_nao_pub > 0:
        gargalos.append(f"Step 14 (Publicar):         {publicaveis_nao_pub:>5,} publicáveis ainda não publicados")
    if pub_sem_oferta > 0:
        gargalos.append(f"Step 17 (Pub. Ofertas):     {pub_sem_oferta:>5,} publicados sem oferta publicada")
    if seeds_pendentes > 0:
        gargalos.append(f"Step 1  (Seeds):            {seeds_pendentes:>5,} arquivo(s) aguardando ingestão")

    if gargalos:
        print()
        print("  GARGALOS")
        print(f"  {sep}")
        for g in gargalos:
            print(f"  ⚠  {g}")

    # Autores
    print()
    print(f"  AUTORES — TOTAL: {total_autores:,}")
    print(f"  {sep}")
    print(f"    Publicados  {autores_publicados:>5,}  {bar(autores_publicados, total_autores, 16)}  {pct(autores_publicados, total_autores):5.1f}%")
    print(f"    Pendentes   {autores_pendentes:>5,}  {bar(autores_pendentes,   total_autores, 16)}  {pct(autores_pendentes, total_autores):5.1f}%")

    # Ofertas
    print()
    print(f"  OFERTAS (livros com offer_url): {total_com_oferta:,}")
    print(f"  {sep}")
    print(f"    Ativas         {oferta_ativa:>5,}  {bar(oferta_ativa, total_com_oferta, 16)}  {pct(oferta_ativa, total_com_oferta):5.1f}%")
    print(f"    Indisponíveis  {oferta_indisponivel:>5,}  {bar(oferta_indisponivel, total_com_oferta, 16)}  {pct(oferta_indisponivel, total_com_oferta):5.1f}%")

    # Listas
    print()
    print(f"  LISTAS SEO: {total_listas:,} total, {listas_publicadas:,} publicadas")

    # ── Sessão Claude PRO (WS7) ───────────────────────────────
    _print_session_pro()

    # ── Histórico de execução ─────────────────────────────────
    conn2 = get_conn()
    _print_step_history(conn2)
    _print_audit_history(conn2)
    conn2.close()

    # ── Rodapé ───────────────────────────────────────────────
    print()
    print(f"  {sep}")
    print("  G → Propor e executar sequência de ataque a gargalos")
    print("=" * 62)
    print()
