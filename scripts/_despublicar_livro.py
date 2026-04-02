"""
Script temporário — despublica um livro específico.
Uso: python scripts/_despublicar_livro.py "A Cabana"

Ações:
  1. Encontra o livro pelo título no SQLite
  2. Deleta do Supabase (livros + ofertas)
  3. Marca is_publishable=0, status_publish=0 no SQLite
"""

import os
import sys
import sqlite3
import requests
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SCRIPTS_DIR  = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPTS_DIR)
DB_PATH      = os.path.join(SCRIPTS_DIR, "data", "books.db")

# Carrega .env.local e scripts/.env
try:
    from dotenv import load_dotenv
    for p in [os.path.join(PROJECT_ROOT, ".env.local"), os.path.join(SCRIPTS_DIR, ".env")]:
        if os.path.exists(p):
            load_dotenv(p)
except ImportError:
    pass

SUPABASE_URL = os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal",
}

TIMEOUT = 15

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def find_book(conn: sqlite3.Connection, titulo: str):
    cur = conn.cursor()
    cur.execute(
        "SELECT id, titulo, slug, supabase_id, status_publish FROM livros "
        "WHERE titulo LIKE ? COLLATE NOCASE",
        (f"%{titulo}%",)
    )
    return cur.fetchall()


def delete_from_supabase(slug: str) -> bool:
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("  [ERRO] Credenciais Supabase não encontradas.")
        return False

    # 1. Busca o id no Supabase pelo slug
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/livros?slug=eq.{slug}&select=id",
        headers=HEADERS, timeout=TIMEOUT
    )
    if r.status_code != 200 or not r.json():
        print(f"  [Supabase] Livro não encontrado no Supabase (slug={slug}) — status {r.status_code}")
        return False

    sb_id = r.json()[0]["id"]
    print(f"  [Supabase] Encontrado: id={sb_id}")

    # 2. Deleta ofertas vinculadas
    ro = requests.delete(
        f"{SUPABASE_URL}/rest/v1/ofertas?livro_id=eq.{sb_id}",
        headers=HEADERS, timeout=TIMEOUT
    )
    print(f"  [Supabase] DELETE ofertas: {ro.status_code}")

    # 3. Deleta o livro
    rl = requests.delete(
        f"{SUPABASE_URL}/rest/v1/livros?id=eq.{sb_id}",
        headers=HEADERS, timeout=TIMEOUT
    )
    ok = rl.status_code in (200, 204)
    print(f"  [Supabase] DELETE livro: {rl.status_code} {'OK' if ok else rl.text[:120]}")
    return ok


def update_sqlite(conn: sqlite3.Connection, livro_id: str, slug: str):
    conn.execute(
        """UPDATE livros
           SET is_publishable = 0,
               status_publish = 0,
               updated_at     = ?
           WHERE id = ?""",
        (datetime.now(timezone.utc).isoformat(), livro_id)
    )
    conn.commit()
    print(f"  [SQLite] is_publishable=0, status_publish=0 para slug={slug}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    titulo_busca = sys.argv[1] if len(sys.argv) > 1 else "A Cabana"

    conn = sqlite3.connect(DB_PATH)
    resultados = find_book(conn, titulo_busca)

    if not resultados:
        print(f"Nenhum livro encontrado com título contendo: '{titulo_busca}'")
        conn.close()
        sys.exit(1)

    if len(resultados) > 1:
        print(f"Múltiplos livros encontrados para '{titulo_busca}':")
        for r in resultados:
            print(f"  id={r[0]} | titulo='{r[1]}' | slug={r[2]} | status_publish={r[4]}")
        print("\nRefine a busca ou edite o script para selecionar o id correto.")
        conn.close()
        sys.exit(1)

    livro_id, titulo, slug, supabase_id, status_publish = resultados[0]
    print(f"\nLivro encontrado:")
    print(f"  titulo        : {titulo}")
    print(f"  slug          : {slug}")
    print(f"  status_publish: {status_publish}")
    print(f"  supabase_id   : {supabase_id}")
    print()

    confirm = input("Confirmar despublicação? (s/n): ").strip().lower()
    if confirm != "s":
        print("Cancelado.")
        conn.close()
        sys.exit(0)

    print("\n--- Executando ---")
    sb_ok = delete_from_supabase(slug)
    update_sqlite(conn, livro_id, slug)
    conn.close()

    print()
    if sb_ok:
        print("Concluído. Livro removido do Supabase e marcado como despublicado no SQLite.")
    else:
        print("SQLite atualizado. Supabase: verificar manualmente (livro pode não ter sido encontrado ou já estava ausente).")


if __name__ == "__main__":
    main()
