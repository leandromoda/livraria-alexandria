# ============================================================
# DB BACKUP
# Livraria Alexandria
#
# Salva cópia timestampada de books.db em data/backup/.
# Mantém os últimos 10 backups automaticamente.
# ============================================================

import shutil
from datetime import datetime
from pathlib import Path

from core.db import get_conn
from core.logger import log


# =========================
# CONFIG
# =========================

SCRIPTS_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR     = SCRIPTS_ROOT / "data"
DB_PATH      = DATA_DIR / "books.db"
BACKUP_DIR   = DATA_DIR / "backup"
MAX_BACKUPS  = 10


# =========================
# RUN
# =========================

def run():

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    if not DB_PATH.exists():
        log("[BACKUP] books.db não encontrado — nada a fazer.")
        return

    # Conta registros antes de copiar
    try:
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM livros")
        total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM livros WHERE status_publish=1")
        publicados = cur.fetchone()[0]
        conn.close()
    except Exception:
        total = publicados = "?"

    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_DIR / f"books_{ts}.db"

    shutil.copy2(DB_PATH, dest)

    size_kb = dest.stat().st_size // 1024
    log(f"[BACKUP] OK: {dest.name} — {total} livros ({publicados} publicados) — {size_kb} KB")

    # Rotação: mantém apenas os MAX_BACKUPS mais recentes
    backups = sorted(BACKUP_DIR.glob("books_????????_??????.db"))
    for old in backups[:-MAX_BACKUPS]:
        old.unlink()
        log(f"[BACKUP] Removido backup antigo: {old.name}")
