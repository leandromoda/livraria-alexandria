# ============================================
# LIVRARIA ALEXANDRIA — QUALITY GATE
# HARD LANGUAGE + EDITORIAL + SCORE VALIDATION
# ============================================

from core.db import get_conn
from core.logger import log


# ============================================
# CONFIG
# ============================================

MIN_SYNOPSIS_LEN = 400


# ============================================
# FETCH
# ============================================

def fetch_candidates(limit):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            titulo,
            descricao,
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

    rows = cur.fetchall()
    conn.close()

    return rows


# ============================================
# CHECKS — PIPELINE
# ============================================

def check_slug(v): return v == 1
def check_synopsis(v): return v == 1
def check_review(v): return v == 1
def check_cover(v): return v == 1


def check_synopsis_len(texto):

    if not texto:
        return False

    return len(texto) >= MIN_SYNOPSIS_LEN


# ============================================
# LANGUAGE HARD GATE
# ============================================

def check_language(idioma_detectado, idioma_base):

    if not idioma_detectado:
        return False, "Idioma vazio"

    idioma_detectado = idioma_detectado.upper()
    idioma_base = idioma_base.upper()

    if idioma_detectado == "UNKNOWN":
        return False, "Idioma UNKNOWN"

    if idioma_detectado != idioma_base:
        return False, f"Idioma divergente ({idioma_detectado})"

    return True, "OK"


# ============================================
# EDITORIAL HARD GATE
# ============================================

def check_editorial(is_book):

    if is_book is None:
        return False, "Editorial indefinido"

    if is_book == 0:
        return False, "Publicação não é livro"

    return True, "OK"


# ============================================
# EDITORIAL SCORE GATE
# ============================================

def check_editorial_score(score):

    if score is None:
        return False, "Editorial score ausente"

    if score < 0:
        return False, f"Score editorial negativo ({score})"

    return True, "OK"


# ============================================
# UPDATE
# ============================================

def mark_publish(book_id):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        UPDATE livros
        SET status_publish = 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (book_id,))

    conn.commit()
    conn.close()


# ============================================
# RUN
# ============================================

def run(idioma_base="PT", pacote=20):

    idioma_base = idioma_base.upper()

    log("QUALITY GATE START")

    rows = fetch_candidates(pacote)

    if not rows:
        log("Nada para validar.")
        return

    aprovados = 0
    reprovados = 0

    for row in rows:

        (
            book_id,
            titulo,
            descricao,
            imagem_url,
            idioma,
            is_book,
            editorial_score,
            status_slug,
            status_synopsis,
            status_review,
            status_cover
        ) = row

        log(f"VALIDANDO → {titulo}")

        motivos = []

        # =========================
        # PIPELINE CHECKS
        # =========================

        if not check_slug(status_slug):
            motivos.append("Slug pendente")

        if not check_synopsis(status_synopsis):
            motivos.append("Sinopse pendente")

        if not check_review(status_review):
            motivos.append("Review pendente")

        if not check_cover(status_cover):
            motivos.append("Capa pendente")

        if not check_synopsis_len(descricao):
            motivos.append("Sinopse curta")

        # =========================
        # LANGUAGE GATE
        # =========================

        lang_ok, lang_msg = check_language(
            idioma,
            idioma_base
        )

        if not lang_ok:
            motivos.append(lang_msg)

        # =========================
        # EDITORIAL GATE
        # =========================

        ed_ok, ed_msg = check_editorial(
            is_book
        )

        if not ed_ok:
            motivos.append(ed_msg)

        # =========================
        # SCORE GATE
        # =========================

        score_ok, score_msg = check_editorial_score(
            editorial_score
        )

        if not score_ok:
            motivos.append(score_msg)

        # =========================
        # DECISÃO
        # =========================

        if motivos:

            reprovados += 1

            log(
                f"REPROVADO → {titulo} | "
                + " | ".join(motivos)
            )

            continue

        # =========================
        # APROVA
        # =========================

        mark_publish(book_id)

        aprovados += 1

        log(
            f"APROVADO → {titulo} "
            f"(idioma={idioma} | score={editorial_score})"
        )

    log(
        f"QUALITY GATE END | "
        f"Aprovados={aprovados} "
        f"Reprovados={reprovados}"
    )