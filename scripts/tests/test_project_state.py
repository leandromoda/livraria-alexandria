"""Testes de integridade do state/project_state.json.

Rodar da pasta scripts/:
    python tests/test_project_state.py

Motivo: `TASK-PIPE-010` ficou DUPLICADA de 2026-03-24 a 2026-07-26 — duas
tarefas distintas com o mesmo id. O modo natural de consultar o arquivo
(`[t for t in tasks if t["id"] == alvo][0]`) devolve só a primeira, então a
segunda ficou invisível por meses. O mesmo padrão quase engoliu um registro
novo na sessão 32: um script de atualização usava `if id not in existentes` e
pulou silenciosamente ids que já existiam.

Nada no fluxo impedia a colisão — ela só aparecia se alguém contasse os ids.

⚠ LACUNA CONHECIDA: `.github/workflows/tests.yml` dispara em `paths: scripts/**`,
não em `state/**`. Um PR que edite SÓ o project_state.json — justamente o que
introduz uma duplicata — não roda este teste. Falta adicionar `- 'state/**'` às
duas listas de `paths` do workflow. Alterar `.github/workflows/` exige o escopo
`workflow` no token, que o assistente não tem; ver TASK-CI-001.
"""

import json
import sys
from collections import Counter
from pathlib import Path

# O arquivo fica na RAIZ do repo, não em scripts/. Resolver por __file__ para
# funcionar tanto rodando de scripts/ quanto do CI (working-directory: scripts).
RAIZ = Path(__file__).resolve().parents[2]
ESTADO = RAIZ / "state" / "project_state.json"

assert ESTADO.is_file(), f"não encontrado: {ESTADO}"

try:
    dados = json.loads(ESTADO.read_text(encoding="utf-8"))
except json.JSONDecodeError as e:
    print(f"[FALHA] project_state.json não é JSON válido: {e}")
    sys.exit(1)

print(f"[OK] JSON válido ({len(dados)} chaves de topo)")

tarefas = dados.get("open_tasks")
assert isinstance(tarefas, list), "open_tasks deve ser uma lista"
print(f"[OK] open_tasks é lista ({len(tarefas)} tarefas)")

# ── Toda tarefa tem id não vazio ──────────────────────────────────────────
sem_id = [i for i, t in enumerate(tarefas) if not (t.get("id") or "").strip()]
assert not sem_id, f"tarefas sem id nos índices: {sem_id}"
print("[OK] toda tarefa tem id")

# ── Ids únicos — o teste que motivou este arquivo ─────────────────────────
ids = [t["id"] for t in tarefas]
duplicados = {i: n for i, n in Counter(ids).items() if n > 1}

if duplicados:
    print(f"[FALHA] id(s) duplicado(s): {duplicados}")
    for dup in duplicados:
        print(f"        '{dup}' aparece em:")
        for i, t in enumerate(tarefas):
            if t["id"] == dup:
                print(f"          índice {i}: {t.get('description', '(sem descrição)')[:70]}")
    print("        Escolha um id livre da MESMA faixa (ex: TASK-PIPE-023, não "
          "TASK-PIPE-001) e registre em 'nota' qual era o id anterior.")
    sys.exit(1)

print(f"[OK] {len(ids)} ids, todos únicos")

# ── status: informativo, NÃO normativo ────────────────────────────────────
# Uma versão anterior deste teste falhava aqui porque eu havia inventado o
# vocabulário {open, resolved, in_progress, blocked, wontfix} em vez de
# derivá-lo do arquivo. O uso real é mais largo — 'implemented', 'planned',
# 'reformulated', 'diagnosed', 'rejected' e ausente também aparecem, em
# entradas legítimas. Impor a lista seria criar uma regra que o projeto nunca
# adotou e quebrar o CI por dado histórico válido. Aqui só reportamos.
por_status = Counter(t.get("status") for t in tarefas)
print("[--] status em uso (informativo, sem regra):")
for s, n in por_status.most_common():
    print(f"       {str(s):14} {n}")

print("\nTodos os testes passaram.")
