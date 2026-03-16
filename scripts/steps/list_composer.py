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
MAX_LISTAS_EXEC  = 200
MIN_LIVROS_LISTA_AUTOR = 3


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
# AUTOR — FETCH
# ============================================================

def fetch_autores_validos():

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            a.id,
            a.nome,
            a.slug,
            COUNT(la.livro_id) as total
        FROM autores a
        JOIN livros_autores la ON la.autor_id = a.id
        JOIN livros l ON l.id = la.livro_id
        WHERE l.status_publish = 1
          AND l.editorial_score >= 1
        GROUP BY a.id
        HAVING COUNT(la.livro_id) >= ?
    """, (MIN_LIVROS_LISTA_AUTOR,))

    rows = cur.fetchall()
    conn.close()

    return rows


def fetch_livros_autor(autor_id):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            l.id,
            l.editorial_score
        FROM livros l
        JOIN livros_autores la ON la.livro_id = l.id
        WHERE la.autor_id = ?
          AND l.status_publish = 1
          AND l.editorial_score >= 1
        ORDER BY l.editorial_score DESC
        LIMIT ?
    """, (autor_id, MAX_LIVROS_LISTA))

    rows = cur.fetchall()
    conn.close()

    return rows


# ============================================================
# AUTOR — SLUG / TITULO / DESCRICAO
# ============================================================

def slug_autor(autor_slug):
    return f"melhores-livros-de-{autor_slug}"


def titulo_lista_autor(nome):
    return f"Melhores livros de {nome}"


def descricao_lista_autor(nome):
    return (
        f"Seleção das melhores obras de {nome}, "
        "reunidas por critérios editoriais e relevância cultural."
    )


# ============================================================
# LISTAS TEMÁTICAS (livros_categorias_tematicas)
# ============================================================

MIN_LIVROS_TEMATICA = 4


def fetch_categorias_tematicas_validas():
    """Retorna categorias temáticas com >= MIN_LIVROS_TEMATICA livros publicados."""

    conn = get_conn()
    cur  = conn.cursor()

    cur.execute("""
        SELECT
            lct.categoria_slug,
            COUNT(DISTINCT l.id) as total
        FROM livros_categorias_tematicas lct
        JOIN livros l ON l.id = lct.livro_id
        WHERE l.status_publish = 1
          AND l.editorial_score >= 1
        GROUP BY lct.categoria_slug
        HAVING COUNT(DISTINCT l.id) >= ?
    """, (MIN_LIVROS_TEMATICA,))

    rows = cur.fetchall()
    conn.close()

    return rows


def fetch_livros_tematica(categoria_slug):
    """Retorna livros publicados nessa categoria, ordenados por confidence DESC, score DESC."""

    conn = get_conn()
    cur  = conn.cursor()

    cur.execute("""
        SELECT
            l.id,
            l.editorial_score,
            lct.confidence
        FROM livros_categorias_tematicas lct
        JOIN livros l ON l.id = lct.livro_id
        WHERE lct.categoria_slug = ?
          AND l.status_publish   = 1
          AND l.editorial_score  >= 1
        ORDER BY lct.confidence DESC, l.editorial_score DESC
        LIMIT ?
    """, (categoria_slug, MAX_LIVROS_LISTA))

    rows = cur.fetchall()
    conn.close()

    return rows


def _gerar_listas_tematicas(listas_ja_criadas):
    """Gera listas por categoria temática. Retorna quantidade criada."""

    categorias = fetch_categorias_tematicas_validas()

    if not categorias:
        log("Nenhuma categoria temática elegível.")
        return 0

    listas_tematicas = 0

    for row in categorias:

        categoria_slug = row[0]

        if listas_ja_criadas + listas_tematicas >= MAX_LISTAS_EXEC:
            break

        slug = f"melhores-livros-de-{categoria_slug}"

        # Dedup: não criar lista se slug idêntico já existir
        if lista_existe(slug):
            continue

        livros = fetch_livros_tematica(categoria_slug)

        if len(livros) < MIN_LIVROS_TEMATICA:
            continue

        titulo    = f"Melhores livros de {categoria_slug.replace('-', ' ').title()}"
        descricao = (
            f"Seleção das melhores obras de {categoria_slug.replace('-', ' ')}, "
            "curadas por critérios editoriais e relevância temática."
        )

        # Converter para formato (id, editorial_score) para inserir_livros
        livros_fmt = [(r[0], r[1]) for r in livros]

        lista_id = criar_lista(slug, titulo, descricao, categoria_slug)
        inserir_livros(lista_id, livros_fmt)

        listas_tematicas += 1
        log(f"Lista temática criada → {titulo}")

    return listas_tematicas


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

    log(f"List Composer finalizado → {listas_criadas} listas de categoria geradas.")

    # --------------------------------------------------------
    # LISTAS POR AUTOR
    # --------------------------------------------------------

    autores = fetch_autores_validos()
    listas_autor = 0

    for autor_row in autores:

        if listas_criadas + listas_autor >= MAX_LISTAS_EXEC:
            break

        autor_id   = autor_row[0]
        autor_nome = autor_row[1]
        autor_slug = autor_row[2]

        slug = slug_autor(autor_slug)

        if lista_existe(slug):
            continue

        livros = fetch_livros_autor(autor_id)

        if len(livros) < MIN_LIVROS_LISTA_AUTOR:
            continue

        titulo    = titulo_lista_autor(autor_nome)
        descricao = descricao_lista_autor(autor_nome)

        lista_id = criar_lista(slug, titulo, descricao, autor_slug)

        inserir_livros(lista_id, livros)

        listas_autor += 1

        log(f"Lista criada → {titulo}")

    log(f"List Composer finalizado → {listas_autor} listas de autor geradas.")

    # --------------------------------------------------------
    # LISTAS POR CATEGORIA TEMÁTICA
    # --------------------------------------------------------

    listas_tematicas = _gerar_listas_tematicas(listas_criadas + listas_autor)
    log(f"List Composer finalizado → {listas_tematicas} listas temáticas geradas.")