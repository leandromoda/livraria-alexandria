# ============================================================
# WS4 — ESTÁGIO DE QA (orquestrador)
# Livraria Alexandria
#
# qa.py NÃO reimplementa checagens: ele ORQUESTRA os módulos já
# validados em produção, fechando o ciclo de qualidade/remediação:
#
#   - consistency_check (51)  → relatório de consistência (não-LLM)
#   - apply_blacklist   (45)  → despublica + persiste causa (não-LLM)
#   - reprocess_blacklist     → recupera/quarentena por causa (não-LLM, WS5)
#   - auditor content   (42)  → auditoria de conteúdo (LLM, opcional)
#   - auditor title     (50)  → veracidade de títulos (LLM, opcional)
#   - auditor list      (48)  → auditoria de listas SEO (não-LLM)
#
# O "passe de remediação" (default) é 100% NÃO-LLM e seguro para rodar
# como fase do orquestrador G (WS6) com cadência reduzida. Os modos LLM
# são explícitos e respeitam a própria quota de sessão.
# ============================================================

import argparse

from core.logger import log

# Modos que NÃO consomem a sessão LLM (seguros para o passe automático).
NON_LLM_MODES = ("consistency", "blacklist", "reprocess", "lists", "remediate", "full")
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


def remediate(dry_run=False, limit=None):
    """Passe de remediação NÃO-LLM: aplica a blacklist do agente e reprocessa
    os títulos recuperáveis (recupera ou quarentena por causa)."""
    log(f"[QA] ===== PASSE DE REMEDIAÇÃO (dry_run={dry_run}) =====")
    _run_apply_blacklist(dry_run)
    counts = _run_reprocess(dry_run, limit)
    log("[QA] ===== remediação concluída =====")
    return counts


def run(mode: str = "remediate", dry_run: bool = False, limit=None, scope: str = "all"):
    """Orquestra o estágio de QA.

    mode:
      remediate (default) → apply_blacklist + reprocess_blacklist (não-LLM)
      full                → consistency + remediate (não-LLM)
      consistency         → só o relatório de consistência
      blacklist           → só apply_blacklist
      reprocess           → só reprocess_blacklist
      lists               → auditoria de listas SEO (não-LLM)
      content             → auditoria de conteúdo (LLM)
      titles              → veracidade de títulos (LLM)
    """
    if mode not in ALL_MODES:
        log(f"[QA] modo inválido: {mode} (válidos: {', '.join(ALL_MODES)})")
        return None

    if mode == "remediate":
        return remediate(dry_run=dry_run, limit=limit)

    if mode == "full":
        _run_consistency()
        return remediate(dry_run=dry_run, limit=limit)

    if mode == "consistency":
        return _run_consistency()

    if mode == "blacklist":
        return _run_apply_blacklist(dry_run)

    if mode == "reprocess":
        return _run_reprocess(dry_run, limit)

    if mode == "lists":
        return _run_auditor("list", limit, dry_run)

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
