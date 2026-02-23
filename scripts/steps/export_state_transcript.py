import os
import json
import sqlite3
import requests
from datetime import datetime
from pathlib import Path


# =========================
# ENV LOADER (NOVO BLOCO)
# =========================

# =========================
# ENV LOADER (NOVO BLOCO) — PATCH CONSERVADOR EXPANDIDO
# =========================

try:
    from dotenv import load_dotenv

    CURRENT_FILE = Path(__file__).resolve()

    ROOT_DIR = CURRENT_FILE.parents[2]
    SCRIPTS_DIR_ENV = CURRENT_FILE.parents[1]

    ENV_PATHS = [

        # raiz
        ROOT_DIR / ".env",
        ROOT_DIR / ".env.local",

        # scripts
        SCRIPTS_DIR_ENV / ".env",
        SCRIPTS_DIR_ENV / ".env.local",
    ]

    print("\n[ENV] Iniciando carregamento de variáveis...")

    for env_path in ENV_PATHS:

        if env_path.exists():

            load_dotenv(env_path)

            print(f"[ENV] Carregado: {env_path}")

        else:

            print(f"[ENV] Não encontrado: {env_path}")

    # LOG FINAL DE DETECÇÃO
    print("\n[ENV] Variáveis críticas:")

    print(
        "NEXT_PUBLIC_SUPABASE_URL:",
        bool(os.getenv("NEXT_PUBLIC_SUPABASE_URL"))
    )

    print(
        "SUPABASE_SERVICE_ROLE_KEY:",
        bool(os.getenv("SUPABASE_SERVICE_ROLE_KEY"))
    )

except Exception as e:

    print(f"[ENV] ERRO ao carregar .env: {str(e)}")


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
PIPELINE_EXTENSIONS = [".py", ".json"]

SITE_FOLDERS = ["app", "lib", "public"]
PIPELINE_FOLDERS = ["scripts"]

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
# TREE — SITE
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


def build_site_tree_full():

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

            for file in files:
                rel_file = rel / file
                lines.append(str(rel_file))

    return "\n".join(lines)


# =========================
# TREE — PIPELINE
# =========================

def build_pipeline_tree():

    lines = []

    for folder in PIPELINE_FOLDERS:

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

            for file in files:
                rel_file = rel / file
                lines.append(str(rel_file))

    return "\n".join(lines)


# =========================
# SQLITE SUMMARY
# =========================

def summarize_sqlite(path):

    if not path.exists():
        return {"error": "db not found"}

    conn = sqlite3.connect(path)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table';"
    )

    tables = [t[0] for t in cursor.fetchall()]

    summary = {}

    for table in tables:

        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]

        cursor.execute(f"PRAGMA table_info({table});")
        cols = cursor.fetchall()

        summary[table] = {
            "rows": count,
            "columns": [
                {"name": c[1], "type": c[2]}
                for c in cols
            ]
        }

    conn.close()
    return summary


# =========================
# SQLITE SCHEMA FULL
# =========================

def extract_sqlite_schema(path):

    if not path.exists():
        return {"error": "db not found"}

    conn = sqlite3.connect(path)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table';"
    )

    tables = [t[0] for t in cursor.fetchall()]

    schema = {}

    for table in tables:

        cursor.execute(f"PRAGMA table_info({table});")
        cols = cursor.fetchall()

        cursor.execute(f"PRAGMA index_list({table});")
        indexes = cursor.fetchall()

        schema[table] = {
            "columns": [
                {
                    "name": c[1],
                    "type": c[2],
                    "notnull": bool(c[3]),
                    "default": c[4],
                    "pk": bool(c[5])
                }
                for c in cols
            ],
            "indexes": [
                {
                    "name": i[1],
                    "unique": bool(i[2])
                }
                for i in indexes
            ]
        }

    conn.close()
    return schema


# =========================
# SUPABASE SCHEMA + LOGS (PATCH CONSERVADOR)
# =========================

def extract_supabase_schema():

    print("\n[Supabase] Iniciando extração de schema...")

    try:

        SUPABASE_URL = os.getenv("NEXT_PUBLIC_SUPABASE_URL")
        SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

        print(f"[Supabase] URL detectada: {bool(SUPABASE_URL)}")
        print(f"[Supabase] SERVICE_ROLE detectada: {bool(SERVICE_ROLE_KEY)}")

        if not SUPABASE_URL or not SERVICE_ROLE_KEY:
            print("[Supabase] ERRO: Variáveis de ambiente ausentes.")
            return {"error": "supabase env vars missing"}

        headers = {
            "apikey": SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {SERVICE_ROLE_KEY}"
        }

        url = (
            f"{SUPABASE_URL}/rest/v1/information_schema.columns"
            "?select=table_name,column_name,data_type,is_nullable,column_default"
        )

        print(f"[Supabase] Endpoint: {url}")

        response = requests.get(url, headers=headers, timeout=15)

        print(f"[Supabase] Status HTTP: {response.status_code}")

        if response.status_code != 200:
            print("[Supabase] ERRO HTTP ao consultar schema.")
            return {"error": f"http {response.status_code}"}

        rows = response.json()

        print(f"[Supabase] Colunas encontradas: {len(rows)}")

        schema = {}

        for r in rows:

            table = r["table_name"]

            if table not in schema:
                schema[table] = []

            schema[table].append({
                "name": r["column_name"],
                "type": r["data_type"],
                "nullable": r["is_nullable"],
                "default": r["column_default"]
            })

        print(f"[Supabase] Tabelas mapeadas: {len(schema)}")

        return schema

    except Exception as e:
        print(f"[Supabase] EXCEPTION: {str(e)}")
        return {"error": str(e)}


# =========================
# SEO DETECTION
# =========================

def detect_indexable_routes(tree):

    routes = []

    for line in tree.splitlines():

        if "page.tsx" in line and "(internal)" not in line:
            route = line.split("app")[-1]
            route = route.replace("\\page.tsx", "")
            route = route.replace("\\", "/")

            if route == "":
                route = "/"

            routes.append(route)

    return routes


def detect_seo_surface(routes):

    surface = {
        "listas": False,
        "livros": False,
        "categorias": False,
        "ofertas": False
    }

    for r in routes:

        if "/listas" in r:
            surface["listas"] = True

        if "/livros" in r:
            surface["livros"] = True

        if "/categorias" in r:
            surface["categorias"] = True

        if "/ofertas" in r:
            surface["ofertas"] = True

    return surface


def detect_structured_data():

    schemas = set()

    for root, _, files in os.walk(PROJECT_ROOT / "app"):

        for f in files:

            if not f.endswith(".tsx"):
                continue

            path = Path(root) / f

            try:
                content = path.read_text(encoding="utf-8")

                if "Product" in content:
                    schemas.add("Product")

                if "Offer" in content:
                    schemas.add("Offer")

                if "ItemList" in content:
                    schemas.add("ItemList")

            except:
                pass

    return list(schemas)


# =========================
# LOADERS
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
# EXPORT — SITE
# =========================

def export_site():

    name = f"{now()}_site_bootstrap"

    tree_full = build_site_tree_full()
    routes = detect_indexable_routes(tree_full)

    data = {
        "tree_site": tree_full,
        "indexable_routes": routes,
        "seo_surface": detect_seo_surface(routes),
        "structured_data": detect_structured_data(),
        "project_state": load_project_state(),
        "database_schema_abstract": load_db_schema()
    }

    return write_parts(name, data)


# =========================
# EXPORT — PIPELINE
# =========================

def export_pipeline_summary():

    name = f"{now()}_pipeline_summary"

    data = {
        "pipeline_tree": build_pipeline_tree(),
        "sqlite_path": str(SQLITE_DB_PATH.resolve()),
        "sqlite_summary": summarize_sqlite(SQLITE_DB_PATH),
        "project_state": load_project_state()
    }

    return write_parts(name, data)


# =========================
# EXPORT — DATABASE (LOCAL + SUPABASE)
# =========================

def export_database_transcript():

    name = f"{now()}_database_transcript"

    data = {
        "sqlite_path": str(SQLITE_DB_PATH.resolve()),
        "sqlite_summary": summarize_sqlite(SQLITE_DB_PATH),
        "sqlite_schema": extract_sqlite_schema(SQLITE_DB_PATH),
        "supabase_schema": extract_supabase_schema()
    }

    return write_parts(name, data)


# =========================
# ENTRY
# =========================

def export_state_transcript(mode="site"):

    if mode == "site":
        paths = export_site()

    elif mode == "pipeline_summary":
        paths = export_pipeline_summary()

    elif mode == "database":
        paths = export_database_transcript()

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