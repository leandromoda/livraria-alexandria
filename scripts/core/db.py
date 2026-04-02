import sqlite3
from pathlib import Path

# ============================================
# PATH CORRIGIDO — SCRIPTS/DATA
# ============================================

CURRENT_DIR = Path(__file__).resolve()
SCRIPTS_ROOT = CURRENT_DIR.parent.parent

DATA_DIR = SCRIPTS_ROOT / "data"
DB_PATH = DATA_DIR / "books.db"


# ============================================
# CONNECTION
# ============================================

def get_conn():

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(
        DB_PATH,
        timeout=60,              # espera lock até 60s
        isolation_level=None     # autocommit seguro
    )

    conn.row_factory = sqlite3.Row

    _configure_sqlite(conn)

    ensure_schema(conn)

    return conn


# alias compatibilidade
def get_connection():
    return get_conn()


# ============================================
# SQLITE RUNTIME CONFIG
# ============================================

def _configure_sqlite(conn):

    cur = conn.cursor()

    # WAL = readers não bloqueiam writers
    cur.execute("PRAGMA journal_mode=WAL;")

    # melhora concorrência
    cur.execute("PRAGMA synchronous=NORMAL;")

    # espera lock ao invés de falhar
    cur.execute("PRAGMA busy_timeout = 60000;")

    # cache maior (pipeline longo)
    cur.execute("PRAGMA cache_size = -20000;")

    cur.close()


# ============================================
# SCHEMA
# ============================================

def ensure_schema(conn):

    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS livros (

        id TEXT PRIMARY KEY,

        titulo TEXT,
        slug TEXT,

        autor TEXT,
        descricao TEXT,

        isbn TEXT,
        ano_publicacao INTEGER,

        imagem_url TEXT,

        idioma TEXT,
        cluster TEXT,
        fonte TEXT,

        preco REAL,

        status_slug INTEGER DEFAULT 0,
        status_dedup INTEGER DEFAULT 0,
        status_synopsis INTEGER DEFAULT 0,
        status_review INTEGER DEFAULT 0,
        status_cover INTEGER DEFAULT 0,
        status_publish INTEGER DEFAULT 0,
        status_publish_oferta INTEGER DEFAULT 0,

        supabase_id TEXT,

        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Migrações para bancos existentes (colunas novas)
    for col, definition in [
        ("preco",                 "REAL"),
        ("status_publish_oferta", "INTEGER DEFAULT 0"),
        ("status_enrich",         "INTEGER DEFAULT 0"),
        ("preco_atual",           "REAL"),
        ("preco_anterior",        "REAL"),
        ("preco_updated_at",      "DATETIME"),
        ("offer_status",          "TEXT DEFAULT 'active'"),
        ("reactivation_pending",  "INTEGER DEFAULT 0"),
        ("status_categorize",     "INTEGER DEFAULT 0"),
        ("editorial_score",       "INTEGER DEFAULT 0"),
        ("sinopse",               "TEXT"),
        ("is_book",               "INTEGER DEFAULT 1"),
        ("is_publishable",        "INTEGER DEFAULT 0"),
        ("offer_url",             "TEXT"),
        ("marketplace",           "TEXT"),
        ("lookup_query",          "TEXT"),
        ("categoria",             "TEXT"),
        ("categorize_attempts",   "INTEGER DEFAULT 0"),
        ("status_descricao",      "INTEGER DEFAULT 0"),
        ("priority_score",        "INTEGER DEFAULT 0"),
    ]:
        try:
            cur.execute(f"ALTER TABLE livros ADD COLUMN {col} {definition}")
        except Exception:
            pass  # coluna já existe

    cur.execute("""
    CREATE TABLE IF NOT EXISTS autores (

        id TEXT PRIMARY KEY,

        nome TEXT NOT NULL,
        slug TEXT NOT NULL UNIQUE,

        nacionalidade TEXT,

        status_publish INTEGER DEFAULT 0,
        supabase_id TEXT,

        deduped INTEGER DEFAULT 0,

        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Migrações para bancos existentes (autores)
    for col, definition in [
        ("deduped",   "INTEGER DEFAULT 0"),
        ("descricao", "TEXT"),
    ]:
        try:
            cur.execute(f"ALTER TABLE autores ADD COLUMN {col} {definition}")
        except Exception:
            pass  # coluna já existe

    cur.execute("""
    CREATE TABLE IF NOT EXISTS livros_autores (

        livro_id TEXT NOT NULL REFERENCES livros(id),
        autor_id TEXT NOT NULL REFERENCES autores(id),

        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

        PRIMARY KEY (livro_id, autor_id)
    );
    """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_livros_autores_autor_id
    ON livros_autores(autor_id);
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS categorias (

        id TEXT PRIMARY KEY,

        nome TEXT NOT NULL,
        slug TEXT NOT NULL UNIQUE,

        status_publish INTEGER DEFAULT 0,
        supabase_id TEXT,

        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS livros_categorias (

        livro_id     TEXT NOT NULL REFERENCES livros(id),
        categoria_id TEXT NOT NULL REFERENCES categorias(id),

        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

        PRIMARY KEY (livro_id, categoria_id)
    );
    """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_livros_categorias_categoria_id
    ON livros_categorias(categoria_id);
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS seed_imports (
        filename    TEXT PRIMARY KEY,
        imported_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        inserted    INTEGER DEFAULT 0,
        skipped     INTEGER DEFAULT 0
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS offer_price_log (
        id            TEXT PRIMARY KEY,
        livro_id      TEXT NOT NULL REFERENCES livros(id),
        preco_anterior REAL,
        preco_novo    REAL,
        offer_status  TEXT,
        marketplace   TEXT,
        captured_at   DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_offer_price_log_livro_id
    ON offer_price_log(livro_id);
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS livros_categorias_tematicas (
        livro_id      TEXT NOT NULL REFERENCES livros(id),
        categoria_slug TEXT NOT NULL,
        confidence    REAL DEFAULT 1.0,
        primary_cat   INTEGER DEFAULT 0,
        created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (livro_id, categoria_slug)
    );
    """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_lct_categoria_slug
    ON livros_categorias_tematicas(categoria_slug);
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS pipeline_runs (
        id           TEXT PRIMARY KEY,
        step_name    TEXT NOT NULL,
        idioma       TEXT,
        pacote       INTEGER,
        started_at   TEXT NOT NULL,
        finished_at  TEXT,
        duracao_s    REAL,
        status       TEXT DEFAULT 'running',
        erro_msg     TEXT,
        invocado_por TEXT DEFAULT 'manual'
    );
    """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_pipeline_runs_started_at
    ON pipeline_runs(started_at);
    """)

    conn.commit()
