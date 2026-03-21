# ============================================================
# DB RESTORE
# Livraria Alexandria
#
# Lista backups disponíveis e restaura o selecionado.
# Cria backup de segurança do db atual antes de sobrescrever.
# ============================================================

import shutil
from datetime import datetime
from pathlib import Path

from core.logger import log


# =========================
# CONFIG
# =========================

SCRIPTS_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR     = SCRIPTS_ROOT / "data"
DB_PATH      = DATA_DIR / "books.db"
BACKUP_DIR   = DATA_DIR / "backup"


# =========================
# HELPERS
# =========================

def _listar_backups():
    """Retorna backups timestampados + books.db legado, do mais novo ao mais antigo."""

    timestampados = sorted(BACKUP_DIR.glob("books_????????_??????.db"), reverse=True)
    legado        = BACKUP_DIR / "books.db"
    legados       = [legado] if legado.exists() else []

    return timestampados + legados


def _resumo(path: Path) -> str:
    """Tenta extrair contagem de livros de um backup."""
    try:
        import sqlite3
        conn = sqlite3.connect(str(path))
        cur  = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM livros")
        total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM livros WHERE status_publish=1")
        pub = cur.fetchone()[0]
        conn.close()
        return f"{total} livros, {pub} publicados"
    except Exception:
        return "conteúdo desconhecido"


# =========================
# RUN
# =========================

def run():

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    backups = _listar_backups()

    if not backups:
        log("[RESTORE] Nenhum backup encontrado em data/backup/.")
        return

    print("\nBackups disponíveis:\n")
    for i, b in enumerate(backups, 1):
        size_kb = b.stat().st_size // 1024
        resumo  = _resumo(b)
        print(f"  {i:>2} → {b.name:<35} {size_kb:>5} KB   {resumo}")

    print()
    escolha = input("Escolha o backup (número) ou Enter para cancelar: ").strip()

    if not escolha:
        log("[RESTORE] Cancelado.")
        return

    try:
        idx      = int(escolha) - 1
        selected = backups[idx]
    except (ValueError, IndexError):
        log("[RESTORE] Seleção inválida.")
        return

    # Backup de segurança do db atual antes de sobrescrever
    if DB_PATH.exists():
        ts     = datetime.now().strftime("%Y%m%d_%H%M%S")
        safety = BACKUP_DIR / f"books_pre_restore_{ts}.db"
        shutil.copy2(DB_PATH, safety)
        log(f"[RESTORE] Backup de segurança criado: {safety.name}")

    shutil.copy2(selected, DB_PATH)

    size_kb = DB_PATH.stat().st_size // 1024
    log(f"[RESTORE] OK: Banco restaurado de: {selected.name} ({size_kb} KB)")
    log("[RESTORE] Rode 'S' no menu para verificar o estado do pipeline.")
