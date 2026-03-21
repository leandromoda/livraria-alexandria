# ============================================================
# DB RECOVER
# Livraria Alexandria
#
# Recupera o banco local a partir do Supabase (fonte primária)
# e complementa com o backup local (livros não publicados).
#
# Estratégia:
#   1. Importa livros, autores, categorias e ofertas do Supabase
#      → todos marcados como totalmente processados
#   2. Mescla backup local para livros ainda não publicados
#      → preserva estado do pipeline (status_review, sinopse…)
# ============================================================

import os
import uuid
import sqlite3
import shutil
import requests

from datetime import datetime
from pathlib import Path

from core.db import get_conn
from core.logger import log


# =========================
# CONFIG SUPABASE
# =========================

SUPABASE_URL = os.environ.get(
    "NEXT_PUBLIC_SUPABASE_URL",
    "https://ncnexkuiiuzwujqurtsa.supabase.co",
)
SUPABASE_KEY = os.environ.get(
    "SUPABASE_SERVICE_ROLE_KEY",
    "",
)

HEADERS = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
}


# =========================
# CONFIG CAMINHOS
# =========================

SCRIPTS_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR     = SCRIPTS_ROOT / "data"
DB_PATH      = DATA_DIR / "books.db"
BACKUP_DIR   = DATA_DIR / "backup"
BACKUP_DB    = BACKUP_DIR / "books.db"          # legado (sem timestamp)


# =========================
# HELPERS SUPABASE
# =========================

def _sb_get_all(table: str, select: str = "*") -> list:
    """Pagina automaticamente e retorna todos os registros da tabela."""
    PAGE    = 1000
    offset  = 0
    results = []

    while True:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/{table}",
            headers={**HEADERS, "Range": f"{offset}-{offset + PAGE - 1}"},
            params={"select": select},
        )
        r.raise_for_status()
        batch = r.json()
        results.extend(batch)
        if len(batch) < PAGE:
            break
        offset += PAGE

    return results


# =========================
# FASE 1 — SUPABASE
# =========================

def _recuperar_supabase(conn):
    """Importa dados do Supabase para o banco local."""

    cur = conn.cursor()
    now = datetime.utcnow().isoformat()

    # ── Livros ──────────────────────────────────────────────
    log("[RECOVER] Buscando livros no Supabase…")
    sb_livros = _sb_get_all("livros")
    log(f"[RECOVER] {len(sb_livros)} livros encontrados.")

    livros_inseridos = 0
    for l in sb_livros:
        local_id = str(uuid.uuid4())
        try:
            cur.execute("""
                INSERT OR IGNORE INTO livros (
                    id, titulo, slug, autor, descricao, sinopse,
                    isbn, ano_publicacao, imagem_url, idioma,
                    is_book, is_publishable,
                    preco_atual, offer_status,
                    status_slug, status_dedup, status_enrich,
                    status_review, status_synopsis, status_cover,
                    status_publish, status_publish_oferta,
                    supabase_id, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,1,1,1,1,1,1,1,?,?,?)
            """, (
                local_id,
                l.get("titulo"),
                l.get("slug"),
                l.get("autor"),
                l.get("descricao"),
                l.get("descricao"),          # sinopse = descricao publicada
                l.get("isbn"),
                l.get("ano_publicacao"),
                l.get("imagem_url"),
                l.get("idioma"),
                1 if l.get("is_book", True) else 0,
                1 if l.get("is_publishable", True) else 0,
                l.get("preco_atual"),
                l.get("offer_status", "active"),
                l["id"],                     # supabase_id
                l.get("created_at", now),
                l.get("updated_at", now),
            ))
            if cur.rowcount:
                livros_inseridos += 1
        except Exception as e:
            log(f"[RECOVER] Erro ao inserir livro {l.get('slug')}: {e}")

    log(f"[RECOVER] Livros inseridos: {livros_inseridos} / {len(sb_livros)}")

    # Mapa supabase_id → local id (para junctions)
    cur.execute("SELECT id, supabase_id FROM livros WHERE supabase_id IS NOT NULL")
    sb_to_local_livro = {row[1]: row[0] for row in cur.fetchall()}

    # ── Autores ─────────────────────────────────────────────
    log("[RECOVER] Buscando autores no Supabase…")
    sb_autores = _sb_get_all("autores")
    autores_inseridos = 0
    for a in sb_autores:
        local_id = str(uuid.uuid4())
        try:
            cur.execute("""
                INSERT OR IGNORE INTO autores (
                    id, nome, slug, nacionalidade,
                    status_publish, supabase_id,
                    created_at, updated_at
                ) VALUES (?,?,?,?,1,?,?,?)
            """, (
                local_id,
                a.get("nome"),
                a.get("slug"),
                a.get("nacionalidade"),
                a["id"],
                a.get("created_at", now),
                a.get("created_at", now),
            ))
            if cur.rowcount:
                autores_inseridos += 1
        except Exception as e:
            log(f"[RECOVER] Erro ao inserir autor {a.get('slug')}: {e}")

    log(f"[RECOVER] Autores inseridos: {autores_inseridos} / {len(sb_autores)}")

    # Mapa supabase_id → local id
    cur.execute("SELECT id, supabase_id FROM autores WHERE supabase_id IS NOT NULL")
    sb_to_local_autor = {row[1]: row[0] for row in cur.fetchall()}

    # ── Livros × Autores ────────────────────────────────────
    log("[RECOVER] Buscando livros_autores no Supabase…")
    sb_la = _sb_get_all("livros_autores")
    la_inseridos = 0
    for la in sb_la:
        local_livro = sb_to_local_livro.get(la.get("livro_id"))
        local_autor = sb_to_local_autor.get(la.get("autor_id"))
        if not local_livro or not local_autor:
            continue
        try:
            cur.execute("""
                INSERT OR IGNORE INTO livros_autores (livro_id, autor_id)
                VALUES (?, ?)
            """, (local_livro, local_autor))
            if cur.rowcount:
                la_inseridos += 1
        except Exception:
            pass

    log(f"[RECOVER] livros_autores inseridos: {la_inseridos}")

    # ── Categorias ──────────────────────────────────────────
    log("[RECOVER] Buscando categorias no Supabase…")
    sb_cats = _sb_get_all("categorias")
    cats_inseridas = 0
    for c in sb_cats:
        local_id = str(uuid.uuid4())
        try:
            cur.execute("""
                INSERT OR IGNORE INTO categorias (
                    id, nome, slug, status_publish, supabase_id,
                    created_at, updated_at
                ) VALUES (?,?,?,1,?,?,?)
            """, (
                local_id,
                c.get("nome"),
                c.get("slug"),
                c["id"],
                c.get("created_at", now),
                c.get("created_at", now),
            ))
            if cur.rowcount:
                cats_inseridas += 1
        except Exception as e:
            log(f"[RECOVER] Erro ao inserir categoria {c.get('slug')}: {e}")

    log(f"[RECOVER] Categorias inseridas: {cats_inseridas} / {len(sb_cats)}")

    # ── Ofertas → atualiza livros locais ────────────────────
    log("[RECOVER] Buscando ofertas no Supabase…")
    sb_ofertas = _sb_get_all("ofertas")
    ofertas_ok = 0
    for o in sb_ofertas:
        local_livro = sb_to_local_livro.get(o.get("livro_id"))
        if not local_livro:
            continue
        try:
            cur.execute("""
                UPDATE livros
                SET offer_url             = ?,
                    marketplace           = ?,
                    preco                 = ?,
                    status_publish_oferta = 1
                WHERE id = ?
                  AND offer_url IS NULL
            """, (
                o.get("url_afiliada"),
                o.get("marketplace"),
                o.get("preco"),
                local_livro,
            ))
            if cur.rowcount:
                ofertas_ok += 1
        except Exception as e:
            log(f"[RECOVER] Erro ao atualizar oferta: {e}")

    log(f"[RECOVER] Ofertas aplicadas: {ofertas_ok} / {len(sb_ofertas)}")

    conn.commit()
    return set(sb_to_local_livro.keys())   # supabase_ids importados


# =========================
# FASE 2 — BACKUP LOCAL
# =========================

def _recuperar_backup(conn, sb_ids_importados: set):
    """
    Mescla livros do backup local que não estão no Supabase.
    Preserva o estado do pipeline (status_review, sinopse, etc.).
    """

    # Localiza o backup mais recente
    backups = sorted(BACKUP_DIR.glob("books_????????_??????.db"), reverse=True)
    backup  = backups[0] if backups else (BACKUP_DIR / "books.db" if BACKUP_DIR.joinpath("books.db").exists() else None)

    if not backup:
        log("[RECOVER] Nenhum backup encontrado para complementar.")
        return

    log(f"[RECOVER] Mesclando backup: {backup.name}")

    try:
        bk_conn = sqlite3.connect(str(backup))
        bk_conn.row_factory = sqlite3.Row
        bk_cur  = bk_conn.cursor()

        # Colunas disponíveis no backup
        bk_cur.execute("PRAGMA table_info(livros)")
        bk_cols = {row[1] for row in bk_cur.fetchall()}

        # Livros não publicados no backup (não chegaram ao Supabase)
        query = "SELECT * FROM livros WHERE (status_publish IS NULL OR status_publish = 0)"
        bk_cur.execute(query)
        nao_publicados = bk_cur.fetchall()

        cur          = conn.cursor()
        inseridos    = 0
        ignorados    = 0

        for bk in nao_publicados:
            bk_dict = dict(bk)

            # Se este livro já foi importado do Supabase, ignora
            if bk_dict.get("supabase_id") and bk_dict["supabase_id"] in sb_ids_importados:
                ignorados += 1
                continue

            # Garante um ID local
            local_id = bk_dict.get("id") or str(uuid.uuid4())

            def get(col, default=None):
                return bk_dict.get(col, default) if col in bk_cols else default

            try:
                cur.execute("""
                    INSERT OR IGNORE INTO livros (
                        id, titulo, slug, autor, descricao, sinopse,
                        isbn, ano_publicacao, imagem_url, idioma,
                        is_book, is_publishable,
                        status_slug, status_dedup, status_review,
                        status_synopsis, status_cover, status_publish,
                        supabase_id, created_at, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    local_id,
                    get("titulo"),
                    get("slug"),
                    get("autor"),
                    get("descricao"),
                    get("sinopse") or get("descricao"),
                    get("isbn"),
                    get("ano_publicacao"),
                    get("imagem_url"),
                    get("idioma"),
                    get("is_book", 1),
                    get("is_publishable", 0),
                    get("status_slug", 0),
                    get("status_dedup", 0),
                    get("status_review", 0),
                    get("status_synopsis", 0),
                    get("status_cover", 0),
                    0,                             # status_publish = 0 (não publicado)
                    get("supabase_id"),
                    get("created_at"),
                    get("updated_at"),
                ))
                if cur.rowcount:
                    inseridos += 1
            except Exception as e:
                log(f"[RECOVER] Erro ao mesclar livro do backup: {e}")

        bk_conn.close()
        conn.commit()
        log(f"[RECOVER] Backup mesclado: {inseridos} novos, {ignorados} já no Supabase.")

    except Exception as e:
        log(f"[RECOVER] Erro ao ler backup: {e}")


# =========================
# RUN
# =========================

def run():

    log("[RECOVER] Iniciando recuperação do banco local…")
    log("[RECOVER] Fase 1: Supabase (fonte primária)")

    if not SUPABASE_KEY:
        log("[RECOVER] ERRO: SUPABASE_SERVICE_ROLE_KEY não definida.")
        return

    # Backup de segurança antes de alterar qualquer coisa
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        ts     = datetime.now().strftime("%Y%m%d_%H%M%S")
        safety = BACKUP_DIR / f"books_pre_recover_{ts}.db"
        shutil.copy2(DB_PATH, safety)
        log(f"[RECOVER] Backup de segurança: {safety.name}")

    conn = get_conn()

    try:
        sb_ids = _recuperar_supabase(conn)

        log("[RECOVER] Fase 2: Backup local (livros não publicados)")
        _recuperar_backup(conn, sb_ids)

    finally:
        conn.close()

    # Relatório final
    conn2 = get_conn()
    cur2  = conn2.cursor()
    cur2.execute("SELECT COUNT(*) FROM livros")                          ; total = cur2.fetchone()[0]
    cur2.execute("SELECT COUNT(*) FROM livros WHERE status_publish=1")  ; pub   = cur2.fetchone()[0]
    cur2.execute("SELECT COUNT(*) FROM autores")                         ; aut   = cur2.fetchone()[0]
    cur2.execute("SELECT COUNT(*) FROM categorias")                      ; cats  = cur2.fetchone()[0]
    conn2.close()

    log("=" * 50)
    log("[RECOVER] Recuperacao concluida!")
    log(f"[RECOVER]   Livros    : {total} ({pub} publicados)")
    log(f"[RECOVER]   Autores   : {aut}")
    log(f"[RECOVER]   Categorias: {cats}")
    log("=" * 50)
