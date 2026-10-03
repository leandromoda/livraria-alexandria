"""
Testes da idempotência do apply_blacklist (assert puro, sem pytest, sem rede).

    PYTHONPATH=. python tests/test_apply_blacklist_idempotente.py

O que fica fixado (ver o docstring de steps/apply_blacklist.py):
  - entrada já aplicada é pulada: nem UPDATE local, nem PATCH;
  - um livro recuperado pelo reprocess_blacklist NÃO volta ao sentinela 4;
  - PATCH que falha deixa o marcador NULL e é retentado — sem regravar status;
  - forcar=True (demote_untitled_published) ignora o marcador.
"""

import json
import os
import sqlite3
import sys
import tempfile
import types

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SCRIPTS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, SCRIPTS_ROOT)

# apply_blacklist importa requests no topo e o CI não roda pip install. O PATCH
# é trocado por stub abaixo, então basta o nome existir.
try:
    import requests  # noqa: F401
except ImportError:
    _m = types.ModuleType("requests")

    def _boom(*_a, **_k):
        raise AssertionError("requests chamado — o teste deveria ter feito stub")

    _m.patch = _m.get = _boom
    sys.modules["requests"] = _m

from core.db import ensure_schema  # noqa: E402
from steps import apply_blacklist as ab  # noqa: E402


def _setup(tmp, slugs):
    db = os.path.join(tmp, "t.db")
    conn = sqlite3.connect(db)
    ensure_schema(conn)
    for s in slugs:
        conn.execute(
            "INSERT INTO livros (id, titulo, slug, status_publish, is_publishable,"
            " status_synopsis, status_categorize) VALUES (?, ?, ?, 1, 1, 1, 1)",
            (s, s, s),
        )
    conn.commit()
    conn.close()

    bl = os.path.join(tmp, "blacklist.json")
    with open(bl, "w", encoding="utf-8") as f:
        json.dump({"entries": [
            {"slug": s, "reason": "synopsis-incoherent", "severity": "high"}
            for s in slugs
        ]}, f)

    ab.BLACKLIST_PATH = bl
    ab.get_connection = lambda: sqlite3.connect(db)
    ab._load_env = lambda: ("http://supabase.test", "k")
    return db


class _Patch:
    def __init__(self, falhar=()):
        self.chamadas = []
        self.falhar = set(falhar)

    def __call__(self, slug, url, key, dry_run):
        self.chamadas.append(slug)
        return slug not in self.falhar


def _row(db, slug):
    c = sqlite3.connect(db)
    r = c.execute(
        "SELECT status_synopsis, status_categorize, blacklist_aplicada_em,"
        " status_publish FROM livros WHERE slug = ?", (slug,)
    ).fetchone()
    c.close()
    return r


def test_segundo_passe_nao_reaplica():
    with tempfile.TemporaryDirectory() as tmp:
        db = _setup(tmp, ["a", "b"])
        patch = _Patch()
        ab._despublish_supabase = patch

        ab.run()
        assert sorted(patch.chamadas) == ["a", "b"], patch.chamadas
        s, c, marcado, pub = _row(db, "a")
        assert (s, c, pub) == (4, 4, 0) and marcado

        patch.chamadas.clear()
        ab.run()
        assert patch.chamadas == [], f"reaplicou: {patch.chamadas}"


def test_recuperado_nao_volta_ao_sentinela():
    with tempfile.TemporaryDirectory() as tmp:
        db = _setup(tmp, ["a"])
        ab._despublish_supabase = _Patch()
        ab.run()

        # o que reprocess_blacklist._recover faz
        c = sqlite3.connect(db)
        c.execute("UPDATE livros SET status_synopsis = 0, status_categorize = 0,"
                  " qa_retry = 1 WHERE slug = 'a'")
        c.commit()
        c.close()

        ab.run()
        s, cat, _, _ = _row(db, "a")
        assert (s, cat) == (0, 0), f"recuperação desfeita: {(s, cat)}"


def test_patch_falho_e_retentado_sem_regravar_status():
    with tempfile.TemporaryDirectory() as tmp:
        db = _setup(tmp, ["a"])
        ab._despublish_supabase = _Patch(falhar={"a"})
        ab.run()
        assert _row(db, "a")[2] is None, "marcou aplicada com PATCH falho"

        c = sqlite3.connect(db)
        c.execute("UPDATE livros SET status_synopsis = 0 WHERE slug = 'a'")
        c.commit()
        c.close()

        patch = _Patch()
        ab._despublish_supabase = patch
        ab.run()
        assert patch.chamadas == ["a"], "PATCH não foi retentado"
        s, _, marcado, _ = _row(db, "a")
        assert marcado, "retentativa bem-sucedida não marcou"
        assert s == 0, "retentativa regravou o sentinela"


def test_forcar_ignora_marcador():
    with tempfile.TemporaryDirectory() as tmp:
        db = _setup(tmp, ["a"])
        ab._despublish_supabase = _Patch()
        ab.run()

        c = sqlite3.connect(db)
        c.execute("UPDATE livros SET status_publish = 1 WHERE slug = 'a'")
        c.commit()
        assert ab._despublish_sqlite(c, "a", False) == ab.JA_APLICADA
        assert ab._despublish_sqlite(c, "a", False, forcar=True) == "a"
        c.close()
        assert _row(db, "a")[3] == 0


def test_backfill_unico_na_criacao_da_coluna():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "t.db")
        c = sqlite3.connect(db)
        ensure_schema(c)
        c.execute("ALTER TABLE livros DROP COLUMN blacklist_aplicada_em")
        c.execute("INSERT INTO livros (id, slug, blacklist_reason) VALUES ('x', 'x', 'r')")
        c.execute("INSERT INTO livros (id, slug) VALUES ('y', 'y')")
        c.commit()
        ensure_schema(c)
        got = dict(c.execute("SELECT id, blacklist_aplicada_em IS NOT NULL FROM livros"))
        assert got == {"x": 1, "y": 0}, got

        # passes seguintes não marcam quem foi aplicado só localmente
        c.execute("UPDATE livros SET blacklist_reason = 'r' WHERE id = 'y'")
        c.commit()
        ensure_schema(c)
        assert c.execute("SELECT blacklist_aplicada_em FROM livros WHERE id='y'").fetchone()[0] is None
        c.close()


if __name__ == "__main__":
    for nome, fn in list(globals().items()):
        if nome.startswith("test_") and callable(fn):
            fn()
            print(f"OK  {nome}")
    print("todos os testes passaram")
