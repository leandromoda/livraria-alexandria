# ============================================================
# WS4 — ESTÁGIO DE QA (orquestrador)
# Livraria Alexandria
#
# qa.py NÃO reimplementa checagens: ele ORQUESTRA os módulos já
# validados em produção, fechando o ciclo de qualidade/remediação:
#
#   - auditor connectivity (41) → conexões (não-LLM)
#   - offer_price_monitor  (40) → preços/disponibilidade de ofertas (não-LLM)
#   - auditor covers       (54) → qualidade/cobertura de capas (não-LLM)
#   - auditor classification(55)→ qualidade/cobertura da classificação (não-LLM)
#   - auditor list         (48) → auditoria de listas SEO (não-LLM)
#   - autopilot_audit      (47) → integridade do pipeline (não-LLM)
#   - consistency_check    (51) → consistência SQLite↔Supabase (não-LLM)
#   - apply_blacklist      (45) → despublica + persiste causa (não-LLM)
#   - reprocess_blacklist       → recupera/quarentena por causa (não-LLM, WS5)
#   - auditor content      (42) → auditoria de conteúdo (LLM, opcional)
#   - auditor title        (50) → veracidade de títulos (LLM, opcional)
#
# P3: `audit` é o PASSE ÚNICO de auditoria do site todo (todos os domínios
# não-LLM acima emitem NNNN_audit_<mode>.json, consumível pelo /audit).
# `full` = audit + remediação. O "passe de remediação" (default) e o `audit`
# são 100% NÃO-LLM e seguros para o orquestrador G (WS6). Os modos LLM são
# explícitos e respeitam a própria quota de sessão.
# ============================================================

import argparse

from core.logger import log

# Modos que NÃO consomem a sessão LLM (seguros para o passe automático).
NON_LLM_MODES = ("consistency", "blacklist", "reprocess", "lists", "covers",
                 "classification", "connectivity", "prices", "integrity",
                 "audit", "remediate", "remediate_covers", "reconcile_synopsis",
                 "flag_synopsis_regen", "ingest_audit", "remediate_mechanical",
                 "full")
# Modos que consomem a sessão Claude PRO.
LLM_MODES = ("content", "titles")
ALL_MODES = NON_LLM_MODES + LLM_MODES


def _run_consistency():
    from steps import consistency_check
    log("[QA] → consistência (relatório)")
    return consistency_check.run()


def _run_apply_blacklist(dry_run):
    import os
    from steps import apply_blacklist
    # load_blacklist() faz sys.exit(1) se o arquivo não existir — guardar para
    # não derrubar o orquestrador quando não há blacklist do agente.
    if not os.path.exists(apply_blacklist.BLACKLIST_PATH):
        log("[QA] → aplicar blacklist: blacklist.json ausente — pulando")
        return
    log("[QA] → aplicar blacklist")
    apply_blacklist.run(dry_run=dry_run)


def _run_reprocess(dry_run, limit):
    from steps import reprocess_blacklist
    log("[QA] → reprocessar blacklist")
    return reprocess_blacklist.run(dry_run=dry_run, limit=limit)


def _run_auditor(mode, limit, dry_run, scope="all"):
    from steps import auditor
    log(f"[QA] → auditor (mode={mode})")
    ns = argparse.Namespace(mode=mode, limit=limit, dry_run=dry_run, scope=scope)
    auditor.run(ns)


def _run_prices(dry_run, limit):
    from steps import offer_price_monitor
    # limite limitado: None varreria TODAS as ofertas (LIMIT NULL) — caro.
    n = limit or 50
    log(f"[QA] → preços/ofertas (limit={n})")
    return offer_price_monitor.run(limit=n, dry_run=dry_run)


def _run_integrity():
    from steps import autopilot_audit
    log("[QA] → integridade do pipeline")
    return autopilot_audit.run()


def site_audit(dry_run=False, limit=None):
    """Passe ÚNICO de auditoria do site todo (100% NÃO-LLM).

    Cada domínio emite seu relatório padronizado NNNN_audit_<mode>.json em
    data/logs/, consumível pelo /audit. Não consome a sessão Claude PRO.
    Domínios: conexões, preços/ofertas, capas, classificação, listas,
    integridade do pipeline e consistência SQLite↔Supabase.
    """
    log(f"[QA] ===== PASSE DE AUDITORIA DO SITE (dry_run={dry_run}) =====")
    _run_auditor("connectivity", limit, dry_run)
    _run_prices(dry_run, limit)
    _run_auditor("covers", limit, dry_run)
    _run_auditor("classification", limit, dry_run)
    _run_auditor("list", limit, dry_run)
    _run_integrity()
    _run_consistency()
    log("[QA] ===== auditoria do site concluída =====")


def remediate(dry_run=False, limit=None):
    """Passe de remediação NÃO-LLM: aplica a blacklist do agente e reprocessa
    os títulos recuperáveis (recupera ou quarentena por causa)."""
    log(f"[QA] ===== PASSE DE REMEDIAÇÃO (dry_run={dry_run}) =====")
    _run_apply_blacklist(dry_run)
    counts = _run_reprocess(dry_run, limit)
    log("[QA] ===== remediação concluída =====")
    return counts


def remediate_mechanical(dry_run=False, limit=None):
    """Remediação MECÂNICA não-LLM dos fatores de qualidade: ingere os relatórios
    de auditoria na fila (P1→fila) e remedia capas + reconcile de sinopse. Reusa
    os steps padrão via book_ids. Seguro para A e G."""
    from steps import qa_remediation
    n = limit or 50
    log("[QA] ===== REMEDIAÇÃO MECÂNICA (ingest + capas + reconcile sinopse) =====")
    qa_remediation.run_ingest_audit()
    qa_remediation.run_covers(limit=n)
    qa_remediation.run_synopsis_reconcile(limit=n)
    log("[QA] ===== remediação mecânica concluída =====")


def run(mode: str = "remediate", dry_run: bool = False, limit=None, scope: str = "all"):
    """Orquestra o estágio de QA.

    mode:
      remediate (default) → apply_blacklist + reprocess_blacklist (não-LLM)
      remediate_covers    → fecha o ciclo de CAPAS: reprocessa publicados sem
                            capa com prioridade (covers+publish padrão, não-LLM)
      reconcile_synopsis  → reconcilia flag de SINOPSE: publicados com
                            status_synopsis=0 e texto válido → flag + QG + publish
                            (não-LLM; sinopse inválida fica p/ regeneração LLM)
      flag_synopsis_regen → marca sinopses concluídas mas inválidas
                            (status_synopsis=1 + texto ruim) → status_synopsis=0
                            p/ o motor LLM (O/G) regenerar. Gatilho não-LLM;
                            usar no G antes da fase LLM. Anti-thrash via quarentena
      ingest_audit        → P1→fila: ingere os relatórios NNNN_audit_<mode>.json
                            na fila qa_remediation (idempotente, não move arquivos)
      remediate_mechanical→ ingest_audit + capas + reconcile de sinopse num passe
                            (não-LLM). Usado pelos ciclos de A e G.
      audit               → PASSE ÚNICO de auditoria do site todo (não-LLM):
                            conexões + preços + capas + classificação + listas
                            + integridade + consistência → NNNN_audit_*.json
      full                → audit + remediate (não-LLM)
      consistency         → só o relatório de consistência
      blacklist           → só apply_blacklist
      reprocess           → só reprocess_blacklist
      lists               → auditoria de listas SEO (não-LLM)
      covers              → qualidade/cobertura de capas (não-LLM)
      classification      → qualidade/cobertura da classificação (não-LLM)
      connectivity        → conexões do site (não-LLM)
      prices              → preços/disponibilidade de ofertas (não-LLM)
      integrity           → integridade do pipeline (não-LLM)
      content             → auditoria de conteúdo (LLM)
      titles              → veracidade de títulos (LLM)
    """
    if mode not in ALL_MODES:
        log(f"[QA] modo inválido: {mode} (válidos: {', '.join(ALL_MODES)})")
        return None

    if mode == "remediate":
        return remediate(dry_run=dry_run, limit=limit)

    if mode == "remediate_covers":
        from steps import qa_remediation
        return qa_remediation.run_covers(limit=limit or 50)

    if mode == "reconcile_synopsis":
        from steps import qa_remediation
        return qa_remediation.run_synopsis_reconcile(limit=limit or 50)

    if mode == "flag_synopsis_regen":
        from steps import qa_remediation
        return qa_remediation.run_synopsis_regen(limit=limit or 500)

    if mode == "ingest_audit":
        from steps import qa_remediation
        return qa_remediation.run_ingest_audit()

    if mode == "remediate_mechanical":
        return remediate_mechanical(dry_run=dry_run, limit=limit)

    if mode == "audit":
        return site_audit(dry_run=dry_run, limit=limit)

    if mode == "full":
        site_audit(dry_run=dry_run, limit=limit)
        return remediate(dry_run=dry_run, limit=limit)

    if mode == "consistency":
        return _run_consistency()

    if mode == "blacklist":
        return _run_apply_blacklist(dry_run)

    if mode == "reprocess":
        return _run_reprocess(dry_run, limit)

    if mode == "lists":
        return _run_auditor("list", limit, dry_run)

    if mode == "covers":
        return _run_auditor("covers", limit, dry_run)

    if mode == "classification":
        return _run_auditor("classification", limit, dry_run)

    if mode == "connectivity":
        return _run_auditor("connectivity", limit, dry_run)

    if mode == "prices":
        return _run_prices(dry_run, limit)

    if mode == "integrity":
        return _run_integrity()

    if mode == "content":
        return _run_auditor("content", limit, dry_run)

    if mode == "titles":
        return _run_auditor("title-verify", limit, dry_run, scope=scope)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Estágio de QA (WS4) — orquestrador")
    p.add_argument("--mode", default="remediate", choices=ALL_MODES)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--scope", default="all", choices=["all", "published", "pipeline"])
    a = p.parse_args()
    run(mode=a.mode, dry_run=a.dry_run, limit=a.limit, scope=a.scope)
