"""
scripts/steps/autopilot_manutencao.py

Autopilot de Manutenção — sem LLM.

Executa em sequência todos os checks de manutenção contínua do site:
  1. Offer Price Monitor    — preço e disponibilidade de ofertas
  2. Auditor Conectividade  — infra, rotas, imagens do site
  3. Auditor Listas SEO     — coerência das listas publicadas
  4. Check Bios de Autores  — autores publicados sem bio (report only)

Cada step salva relatório JSON em data/logs/ com prefixo sequencial.
Ao final, imprime um sumário consolidado.

Acionado via menu principal: opção M
"""

import argparse
import sys
import os

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_ROOT = os.path.dirname(SCRIPT_DIR)
if SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, SCRIPTS_ROOT)

from core.db     import get_conn
from core.logger import log

from steps import offer_price_monitor
from steps import auditor as _auditor


def run(price_limit: int = 50, dry_run: bool = False) -> None:
    log("=" * 60)
    log("[MANUTENCAO] Autopilot de Manutenção iniciado")
    log(f"[MANUTENCAO] price_limit={price_limit} | dry_run={dry_run}")
    log("=" * 60)

    sumario = {}

    # ------------------------------------------------------------------
    # 1. Offer Price Monitor
    # ------------------------------------------------------------------
    log("\n[MANUTENCAO] ▶ STEP 1/4 — Offer Price Monitor")
    try:
        offer_price_monitor.run(limit=price_limit, dry_run=dry_run)
        sumario["price_monitor"] = "OK"
    except Exception as e:
        log(f"[MANUTENCAO] ERRO no Price Monitor: {e}")
        sumario["price_monitor"] = f"ERRO: {e}"

    # ------------------------------------------------------------------
    # 2. Auditor Conectividade
    # ------------------------------------------------------------------
    log("\n[MANUTENCAO] ▶ STEP 2/4 — Auditoria de Conectividade")
    try:
        conn = get_conn()
        _auditor.ensure_audit_tables(conn)
        result_conn = _auditor.run_connectivity(conn, dry_run=dry_run)
        result_conn["generated_at"] = _auditor._now_iso()
        result_conn["dry_run"] = dry_run
        _auditor.save_report(result_conn)
        sumario["connectivity"] = f"{result_conn['ok']}/{result_conn['total']} OK"
        conn.close()
    except Exception as e:
        log(f"[MANUTENCAO] ERRO na Auditoria de Conectividade: {e}")
        sumario["connectivity"] = f"ERRO: {e}"

    # ------------------------------------------------------------------
    # 3. Auditoria de Listas SEO
    # ------------------------------------------------------------------
    log("\n[MANUTENCAO] ▶ STEP 3/4 — Auditoria de Listas SEO")
    try:
        conn = get_conn()
        _auditor.ensure_audit_tables(conn)
        result_list = _auditor.run_list_audit(conn, dry_run=dry_run)
        result_list["generated_at"] = _auditor._now_iso()
        result_list["dry_run"] = dry_run
        _auditor.save_report(result_list)
        despub = result_list.get("despublished", 0)
        refresh = len(result_list.get("needs_refresh_slugs", []))
        sumario["list_audit"] = f"Despublicadas={despub} | Needs refresh={refresh}"
        conn.close()
    except Exception as e:
        log(f"[MANUTENCAO] ERRO na Auditoria de Listas: {e}")
        sumario["list_audit"] = f"ERRO: {e}"

    # ------------------------------------------------------------------
    # 4. Check Bios de Autores
    # ------------------------------------------------------------------
    log("\n[MANUTENCAO] ▶ STEP 4/4 — Verificação de Bios de Autores")
    try:
        conn = get_conn()
        _auditor.ensure_audit_tables(conn)
        result_bios = _auditor.check_author_bios(conn)
        result_bios["generated_at"] = _auditor._now_iso()
        result_bios["dry_run"] = dry_run
        _auditor.save_report(result_bios)
        sem_bio = result_bios.get("without_bio", 0)
        total_pub = result_bios.get("total_published", 0)
        sumario["author_bios"] = f"{sem_bio}/{total_pub} sem bio"
        conn.close()
    except Exception as e:
        log(f"[MANUTENCAO] ERRO no Check de Bios: {e}")
        sumario["author_bios"] = f"ERRO: {e}"

    # ------------------------------------------------------------------
    # Sumário final
    # ------------------------------------------------------------------
    log("\n" + "=" * 60)
    log("[MANUTENCAO] SUMÁRIO FINAL")
    log("=" * 60)
    for step, resultado in sumario.items():
        log(f"  {step:<20} → {resultado}")
    log("=" * 60)
    log("[MANUTENCAO] Autopilot de Manutenção concluído.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Autopilot de Manutenção — sem LLM")
    parser.add_argument("--price-limit", type=int, default=50,
                        help="Limite de livros para o price monitor (default=50)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Executa sem aplicar alterações")
    args = parser.parse_args()
    run(price_limit=args.price_limit, dry_run=args.dry_run)
