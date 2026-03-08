# ============================================================
# STEP — LIST COMPOSER
# Livraria Alexandria
#
# Gera listas SEO automaticamente a partir de livros
#
# SAFE:
# - cria tabelas automaticamente
# - deduplicação por slug
# - limites de geração
# - usa editorial_score
# - filtro anti thin-content
# ============================================================

from core.db import get_conn
from core.logger import log


# ============================================================
# CONFIG
# ============================================================

MIN_LIVROS_LISTA = 6
MAX_LIVROS_LISTA = 12
MAX_LISTAS_EXEC = 200


# ============================================================
# SCHEMA
# ============================================================

def ensure_schema():

    conn = get_conn()
    cur = conn.cursor()

    log("Verificando schema de listas...")

    cur.execute("""

    CREATE TABLE IF NOT EXISTS listas (

        id TEXT PRIMARY KEY,

        slug TEXT UNIQUE,

        titulo TEXT,
        descricao TEXT,

        categoria_slug TEXT,

        source TEXT,

        idioma TEXT,

        created_at DATETIME DEFAULT CURRENT_TIMESTAMP

    )

    """)

    cur.execute("""

    CREATE TABLE IF NOT EXISTS listas_livros (

        lista_id TEXT,
        livro_id TEXT,

        position INTEGER,
        editorial_weight INTEGER,

        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

        PRIMARY KEY (lista_id, livro_id)

    )

    """)

    conn.commit()
    conn.close()


# ============================================================
# FETCH CATEGORIAS
# ============================================================

def fetch_categorias_validas():

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""

    SELECT
        categoria,
        COUNT(*) as total
    FROM livros
    WHERE editorial_score >= 2
    AND status_publish = 1
    GROUP BY categoria
    HAVING COUNT(*) >= ?

    """, (MIN_LIVROS_LISTA,))

    rows = cur.fetchall()
    conn.close()

    return rows


# ============================================================
# FETCH LIVROS DA CATEGORIA
# ============================================================

def fetch_livros_categoria(categoria):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""

    SELECT
        id,
        editorial_score
    FROM livros
    WHERE categoria = ?
    AND editorial_score >= 2
    AND status_publish = 1
    ORDER BY editorial_score DESC
    LIMIT ?

    """, (categoria, MAX_LIVROS_LISTA))

    rows = cur.fetchall()
    conn.close()

    return rows


# ============================================================
# QUALITY FILTER (ANTI THIN CONTENT)
# ============================================================

def categoria_tem_qualidade(livros):

    fortes = 0

    for livro in livros:

        score = livro[1]

        if score >= 3:
            fortes += 1

    return fortes >= 2


# ============================================================
# CHECK EXISTING
# ============================================================

def lista_existe(slug):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""

    SELECT id
    FROM listas
    WHERE slug = ?
    LIMIT 1

    """, (slug,))

    row = cur.fetchone()

    conn.close()

    return row is not None


# ============================================================
# CREATE LISTA
# ============================================================

def criar_lista(slug, titulo, descricao, categoria):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""

    INSERT INTO listas (

        id,
        slug,
        titulo,
        descricao,
        categoria_slug,
        source,
        idioma

    )
    VALUES (

        lower(hex(randomblob(12))),
        ?,
        ?,
        ?,
        ?,
        'auto_categoria',
        'PT'

    )

    """, (

        slug,
        titulo,
        descricao,
        categoria

    ))

    conn.commit()

    cur.execute("""

    SELECT id
    FROM listas
    WHERE slug = ?
    LIMIT 1

    """, (slug,))

    row = cur.fetchone()

    conn.close()

    return row[0]


# ============================================================
# INSERT LIVROS
# ============================================================

def inserir_livros(lista_id, livros):

    conn = get_conn()
    cur = conn.cursor()

    pos = 1

    for livro in livros:

        livro_id = livro[0]
        score = livro[1]

        cur.execute("""

        INSERT OR IGNORE INTO listas_livros (

            lista_id,
            livro_id,
            position,
            editorial_weight

        )
        VALUES (?, ?, ?, ?)

        """, (

            lista_id,
            livro_id,
            pos,
            score

        ))

        pos += 1

    conn.commit()
    conn.close()


# ============================================================
# SLUG
# ============================================================

def slug_categoria(cat):

    cat = cat.strip().lower().replace(" ", "-")

    return f"melhores-livros-de-{cat}"


# ============================================================
# TITULO
# ============================================================

def titulo_lista(cat):

    return f"Melhores livros de {cat}"


# ============================================================
# DESCRICAO
# ============================================================

def descricao_lista(cat):

    return (
        f"Seleção de livros recomendados sobre {cat}. "
        "Esta lista reúne obras relevantes avaliadas por critérios "
        "editoriais e impacto cultural."
    )


# ============================================================
# RUN
# ============================================================

def run():

    log("List Composer iniciado...")

    ensure_schema()

    categorias = fetch_categorias_validas()

    if not categorias:

        log("Nenhuma categoria elegível encontrada.")
        return

    listas_criadas = 0

    for row in categorias:

        categoria = row[0]
        total = row[1]

        if listas_criadas >= MAX_LISTAS_EXEC:
            break

        slug = slug_categoria(categoria)

        if lista_existe(slug):
            continue

        livros = fetch_livros_categoria(categoria)

        if len(livros) < MIN_LIVROS_LISTA:
            continue

        # filtro anti thin-content
        if not categoria_tem_qualidade(livros):
            log(f"Categoria ignorada (baixa qualidade) → {categoria}")
            continue

        titulo = titulo_lista(categoria)

        descricao = descricao_lista(categoria)

        lista_id = criar_lista(

            slug,
            titulo,
            descricao,
            categoria

        )

        inserir_livros(lista_id, livros)

        listas_criadas += 1

        log(f"Lista criada → {titulo}")

    log(f"List Composer finalizado → {listas_criadas} listas geradas.")