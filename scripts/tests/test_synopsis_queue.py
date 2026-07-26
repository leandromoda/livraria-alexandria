"""Testes da fila de sinopse — filtro de descrição e ordem por confiança.

Rodar da pasta scripts/:
    PYTHONPATH=. python tests/test_synopsis_queue.py

Cobre as duas mudanças de comportamento mais recentes do gargalo, que até agora
só tinham validação manual:

  1. TASK-SYN-016 — livro SEM descrição não pode ser exportado. Exportá-lo é
     rejeição garantida pelo agente, gastando uma chamada do gargalo. Medido em
     2026-07-26: 10.041 dos 11.028 da fila (91%) estavam nesse estado.
  2. TASK-ENRICH-001 — ordem por `enrich_similaridade` (casamento exato
     primeiro, NULL por último). Medido: exato acerta 89%, faixa 0.50-0.70
     acerta 56%.

Usa SQLite em memória com o schema real (`ensure_schema`) — sem rede, sem LLM
e sem tocar em data/books.db.
"""

import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.db import ensure_schema
from steps.synopsis_export import fetch_pending


def _conn_memoria():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    return conn


def _inserir(conn, livro_id, titulo, descricao, similaridade):
    conn.execute(
        """INSERT INTO livros
               (id, titulo, descricao, enrich_similaridade, idioma,
                status_synopsis, status_review, is_book, qa_quarantine)
           VALUES (?, ?, ?, ?, 'PT', 0, 1, 1, 0)""",
        (livro_id, titulo, descricao, similaridade),
    )


conn = _conn_memoria()

# id, titulo, descricao, similaridade
_inserir(conn, "a1", "Exato",        "Descricao valida do livro.", 1.00)
_inserir(conn, "a2", "Alto",         "Descricao valida do livro.", 0.88)
_inserir(conn, "a3", "Baixo",        "Descricao valida do livro.", 0.55)
_inserir(conn, "a4", "SemSimilar",   "Descricao valida do livro.", None)
_inserir(conn, "b1", "SemDescNull",  None,                          1.00)
_inserir(conn, "b2", "SemDescVazia", "",                            1.00)
_inserir(conn, "b3", "SemDescEspaco", "   ",                        1.00)
conn.commit()

# ── 1. Filtro de descrição ────────────────────────────────────────────────
rows = fetch_pending(conn, "PT", 50)
ids = [r["id"] for r in rows]

for bloqueado in ("b1", "b2", "b3"):
    assert bloqueado not in ids, f"{bloqueado} sem descrição não podia ser exportado"
print("[OK] livro sem descrição (NULL, vazia e só espaços) não é exportado")

assert set(ids) == {"a1", "a2", "a3", "a4"}, ids
print(f"[OK] exporta só os com descrição ({len(ids)} de 7)")

# O filtro é por conteúdo, não por similaridade: a4 não tem similaridade e entra.
assert "a4" in ids, "similaridade NULL não deve excluir quem TEM descrição"
print("[OK] similaridade NULL não exclui — só ordena")

# ── 2. Ordem por confiança ────────────────────────────────────────────────
assert ids == ["a1", "a2", "a3", "a4"], f"ordem errada: {ids}"
print("[OK] ordem: exato (1.00) -> 0.88 -> 0.55 -> NULL por último")

# ── 3. O filtro vale também no caminho book_ids (ingestão guiada) ─────────
rows = fetch_pending(conn, "PT", 50, book_ids=["b1"])
assert rows == [] or [r["id"] for r in rows] == [], \
    "book_ids não pode furar o filtro de descrição"
print("[OK] caminho book_ids respeita o filtro")

rows = fetch_pending(conn, "PT", 50, book_ids=["a3", "a1"])
assert [r["id"] for r in rows] == ["a1", "a3"], [r["id"] for r in rows]
print("[OK] book_ids também ordena por confiança")

# ── 4. LIMIT respeita a ordem (não corta os melhores) ─────────────────────
rows = fetch_pending(conn, "PT", 2)
assert [r["id"] for r in rows] == ["a1", "a2"], [r["id"] for r in rows]
print("[OK] LIMIT pega os de maior confiança primeiro")

conn.close()
print("\nTodos os testes passaram.")
