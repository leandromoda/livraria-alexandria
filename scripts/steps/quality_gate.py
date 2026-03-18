# ============================================================
# STEP 9 — QUALITY GATE
# Livraria Alexandria
#
# Valida sinopse (não descricao) para publicação.
# ============================================================

import os
import sqlite3
from core.db import get_conn
from core.logger import log


# =========================
# CONFIG
# =========================

MIN_SYNOPSIS_LEN = 400


# =========================
# FETCH
# =========================

def fetch_candidates(conn, limit):

    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            titulo,
            sinopse,
            imagem_url,
            idioma,
            is_book,
            editorial_score,
            status_slug,
            status_synopsis,
            status_review,
            status_cover
        FROM livros
        WHERE status_publish = 0
        LIMIT ?
    """, (limit,))

    return cur.fetchall()


# =========================
# CHECKS
# =========================

def check_synopsis_len(texto):
    if not texto:
        return False
    return len(texto) >= MIN_SYNOPSIS_LEN


def check_language(idioma_detectado, idioma_base):
    if not idioma_detectado:
        return False, "Idioma vazio"
    i = idioma_detectado.upper()
    if i == "UNKNOWN":
        return False, "Idioma UNKNOWN"
    if i != idioma_base.upper():
        return False, f"Idioma divergente ({i})"
    return True, "OK"


def check_editorial(is_book):
    if is_book is None:
        return False, "Editorial indefinido"
    if is_book == 0:
        return False, "Não é livro"
    return True, "OK"


def check_editorial_score(score):
    if score is None:
        return False, "Score ausente"
    if score < 0:
        return False, f"Score negativo ({score})"
    return True, "OK"


# =========================
# UPDATE
# =========================

def set_publishable(conn, book_id, value):

    cur = conn.cursor()

    cur.execute("""
        UPDATE livros
        SET is_publishable = ?,
            updated_at     = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (value, book_id))

    conn.commit()


# =========================
# RUN
# =========================

def run(idioma_base="PT", pacote=20):

    idioma_base = idioma_base.upper()

    conn = get_conn()

    rows = fetch_candidates(conn, pacote)

    if not rows:
        log("QUALITY GATE — Nada para validar.")
        conn.close()
        return

    aprovados  = 0
    reprovados = 0
    total      = len(rows)

    log("QUALITY GATE START")

    for i, row in enumerate(rows, start=1):

        (
            book_id, titulo, sinopse, imagem_url,
            idioma, is_book, editorial_score,
            status_slug, status_synopsis,
            status_review, status_cover
        ) = row

        motivos = []

        if status_slug != 1:
            motivos.append("Slug pendente")

        if status_synopsis != 1:
            motivos.append("Sinopse pendente")

        if status_review != 1:
            motivos.append("Review pendente")

        if status_cover not in (1, 2):
            motivos.append("Capa pendente")

        if not check_synopsis_len(sinopse):
            motivos.append("Sinopse curta ou ausente")

        lang_ok, lang_msg = check_language(idioma, idioma_base)
        if not lang_ok:
            motivos.append(lang_msg)

        ed_ok, ed_msg = check_editorial(is_book)
        if not ed_ok:
            motivos.append(ed_msg)

        score_ok, score_msg = check_editorial_score(editorial_score)
        if not score_ok:
            motivos.append(score_msg)

        if motivos:
            set_publishable(conn, book_id, 0)
            reprovados += 1
            log(f"[QUALITY][{i:03d}/{total:03d}] REPROVADO → {titulo} | " + " | ".join(motivos))
        else:
            set_publishable(conn, book_id, 1)
            aprovados += 1
            log(f"[QUALITY][{i:03d}/{total:03d}] APROVADO → {titulo}")

    conn.close()

    log(f"QUALITY GATE END | Aprovados={aprovados} Reprovados={reprovados}")


# =========================
# COMPATIBILITY LAYER
# =========================

def evaluate_quality(idioma_base="PT", pacote=20):
    return run(idioma_base, pacote)
