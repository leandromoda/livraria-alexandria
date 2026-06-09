---
description: Analisa UM log do pipeline e aplica as correções sugeridas — fluxo integral no Claude Code, em 2 etapas (diagnóstico + correção)
---

# Análise + correção de logs do pipeline

Executa **integralmente no Claude Code** o ciclo completo de diagnóstico e correção
de **um** log do pipeline. Substitui o fluxo antigo que rodava parcialmente via
Claude Batch — agora as duas etapas acontecem aqui, em sequência.

> **1 log por invocação.** Sempre o mais antigo ainda não processado.
> Rode `/analise-logs` de novo para o próximo log.

A lógica de parsing e o schema do relatório vivem **apenas** em
`agents/log_analysis_batch/prompt.md` — este comando só orquestra as duas etapas
(sem duplicar aquela lógica).

---

## Etapa 1 — Diagnóstico (apenas análise; NÃO edita código)

Siga **integralmente** as instruções de `agents/log_analysis_batch/prompt.md`:

1. Detecte a raiz do repo e liste `scripts/data/logs/pipeline_*.log`.
2. Se não houver logs → responda "Nenhum log para processar." e **pare**
   (não há Etapa 2 a executar).
3. Selecione o **mais antigo**, leia-o por completo e gere o relatório JSON em
   `scripts/data/log_analysis/log_analysis_TIMESTAMP.json` → **PASSO A** do prompt.
4. Verifique que o JSON existe → **PASSO B** do prompt.
5. Mova o **`.log` fonte** para `scripts/data/log_analysis/processed_logs/`
   → **PASSO C** do prompt (só após o PASSO B confirmar o JSON).

> ⚠️ Nesta etapa você é **só analista**: não edite nenhum `.py` nem arquivo de
> dados. Toda correção é apenas *descrita* em `failures` / `actionable_insights`.

Ao final, registre o caminho do relatório recém-criado — ele é o input da Etapa 2.

---

## Etapa 2 — Correção (aplica as soluções e arquiva o relatório)

1. Leia o relatório JSON produzido na Etapa 1
   (`scripts/data/log_analysis/log_analysis_TIMESTAMP.json`).
2. Para cada `actionable_insights` (priorize `critical` → `high` → `medium` → `low`)
   e cada `failure` / `exception`:
   - Abra o `source_file` / `suggested_investigation` indicado.
   - Aplique a `suggested_fix` no código real em `scripts/...`.
   - Corrija também os `affected_data_files`, se listados.
3. **Não** gere correção de código para `rejections` (comportamento esperado do
   pipeline) nem para insights sem ação real (`empty_log`, rate limit externo,
   capa/sinopse pendente). Registre que foram avaliados e dispensados — não invente fix.
4. **Somente após ler e aplicar as correções**, mova o relatório JSON para
   `scripts/data/log_analysis/processed_logs/` (mesmo destino do `.log` da Etapa 1).

---

## Regras (atenção à movimentação de arquivos)

- **Separação rígida das etapas:** Etapa 1 = diagnóstico **sem editar código**;
  Etapa 2 = implementação das correções. Não misture.
- **Ordem de movimentação — ponto crítico:**
  - O **`.log`** só sai de `logs/` **depois** que o JSON existe (Etapa 1, PASSO C).
  - O **`.json`** só sai de `log_analysis/` (raiz) **depois** das correções aplicadas
    (Etapa 2, passo 4).
  - Destino de ambos: `scripts/data/log_analysis/processed_logs/`.
  - Nunca grave o JSON direto em `processed_logs/` — ele nasce na raiz de
    `log_analysis/` e só é movido no fim.
- **Sem redundância:** não copie aqui o parsing/schema do log — está no
  `prompt.md`. Este comando apenas encadeia as duas etapas.

---

## Encerramento

Reporte de forma sucinta:
- log analisado e nº de falhas / rejeições / insights;
- arquivos de código corrigidos (lista) — ou "nenhuma correção necessária";
- confirmação de que **`.log`** e **`.json`** foram para `processed_logs/`.
