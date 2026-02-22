import os
import json
import sqlite3
from datetime import datetime
from pathlib import Path


# =========================
# ROOT SAFE (CORRIGIDO)
# =========================

CURRENT_DIR = Path(__file__).resolve()

SCRIPTS_DIR = CURRENT_DIR.parents[1]
PROJECT_ROOT = CURRENT_DIR.parents[2]

STATE_DIR = PROJECT_ROOT / "state"
STATE_DIR.mkdir(exist_ok=True)

DATA_DIR = SCRIPTS_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

SQLITE_DB_PATH = DATA_DIR / "books.db"


# =========================
# CONFIG
# =========================

MAX_CHARS = 25000

SITE_EXTENSIONS = [".tsx", ".ts", ".css", ".json"]
PIPELINE_EXTENSIONS = [".py", ".json", ".db"]

SITE_FOLDERS = ["app", "lib", "public"]
PIPELINE_FOLDERS = ["scripts", "state"]

EXCLUDE_DIRS = {
    "node_modules",
    ".next",
    "venv",
    "__pycache__"
}


# =========================
# UTILS
# =========================

def now():
    return datetime.now().strftime("%Y-%m-%d_%H-%M")


# =========================
# SPLIT
# =========================

def split_text(text):

    parts = []
    start = 0

    while start < len(text):
        parts.append(text[start:start + MAX_CHARS])
        start += MAX_CHARS

    return parts


def write_parts(name, data):

    text = json.dumps(
        data,
        indent=2,
        ensure_ascii=False
    )

    parts = split_text(text)

    paths = []

    for i, part in enumerate(parts, 1):

        file = STATE_DIR / f"{name}_part_{i:03}.json"

        with open(file, "w", encoding="utf-8") as f:
            f.write(part)

        paths.append(file)

    return paths


# =========================
# TREE
# =========================

def build_site_tree():

    lines = []

    for folder in SITE_FOLDERS:

        base = PROJECT_ROOT / folder

        if not base.exists():
            continue

        for root, dirs, files in os.walk(base):

            dirs[:] = [
                d for d in dirs
                if d not in EXCLUDE_DIRS
            ]

            rel = Path(root).relative_to(PROJECT_ROOT)
            lines.append(str(rel))

    return "\n".join(lines)


# =========================
# FILE COLLECT
# =========================

def collect_files(folders, extensions=None):

    collected = {}

    for folder in folders:

        base = PROJECT_ROOT / folder

        if not base.exists():
            continue

        for root, dirs, files in os.walk(base):

            dirs[:] = [
                d for d in dirs
                if d not in EXCLUDE_DIRS
            ]

            for file in files:

                if extensions and not any(
                    file.endswith(ext)
                    for ext in extensions
                ):
                    continue

                path = Path(root) / file
                rel = str(path.relative_to(PROJECT_ROOT))

                if file.endswith(".db"):
                    collected[rel] = dump_sqlite(path)
                else:
                    collected[rel] = read_file(path)

    return collected


# =========================
# FILE READ
# =========================

def read_file(path):

    try:
        return path.read_text(encoding="utf-8")
    except:
        return "[binary or unreadable]"


# =========================
# SQLITE DUMP
# =========================

def dump_sqlite(path):

    if not path.exists():
        return {"error": "db not found"}

    try:

        conn = sqlite3.connect(path)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table';"
        )

        tables = [t[0] for t in cursor.fetchall()]

        dump = {}

        for table in tables:

            cursor.execute(
                f"PRAGMA table_info({table});"
            )

            cols = cursor.fetchall()

            dump[table] = [
                {
                    "name": c[1],
                    "type": c[2]
                }
                for c in cols
            ]

        conn.close()

        return dump

    except:
        return {"error": "failed to read sqlite"}


# =========================
# ABSTRACT LOADERS
# =========================

def load_project_state():

    path = PROJECT_ROOT / "project_state.json"

    if path.exists():
        return path.read_text(encoding="utf-8")

    return "project_state.json não encontrado."


def load_db_schema():

    path = PROJECT_ROOT / "database_schema.json"

    if path.exists():
        return path.read_text(encoding="utf-8")

    return "database_schema.json não encontrado."


# =========================
# MODES
# =========================

def export_site():

    name = f"{now()}_site_bootstrap"

    data = {
        "tree_site": build_site_tree(),
        "project_state": load_project_state(),
        "database_schema_abstract": load_db_schema(),
        "files": collect_files(
            SITE_FOLDERS,
            SITE_EXTENSIONS
        )
    }

    return write_parts(name, data)


def export_pipeline():

    name = f"{now()}_pipeline_full"

    data = {
        "sqlite_dump": dump_sqlite(SQLITE_DB_PATH),
        "files": collect_files(
            PIPELINE_FOLDERS,
            PIPELINE_EXTENSIONS
        )
    }

    return write_parts(name, data)


def export_full():

    name = f"{now()}_full_snapshot"

    data = {
        "tree_site": build_site_tree(),
        "sqlite_dump": dump_sqlite(SQLITE_DB_PATH),
        "files": collect_files(
            ["."],
            None
        )
    }

    return write_parts(name, data)


# =========================
# ENTRY
# =========================

def export_state_transcript(mode="site"):

    if mode == "site":
        paths = export_site()

    elif mode == "pipeline":
        paths = export_pipeline()

    elif mode == "full":
        paths = export_full()

    else:
        print("Modo inválido.")
        return

    print("\nTranscript gerado:\n")

    for p in paths:
        print(p)

    print("\nTotal partes:", len(paths), "\n")


# =========================

if __name__ == "__main__":
    export_state_transcript("site")
