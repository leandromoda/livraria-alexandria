---
description: Lê UM relatório de auditoria do site e aplica as correções — fluxo integral no Claude Code, em 2 etapas (diagnóstico + correção)
---

# Correção de auditoria do site

Executa **integralmente no Claude Code** o ciclo de correção a partir de **um**
relatório de auditoria do `auditor.py` (`scripts/data/logs/NNNN_audit_MODE.json`).

> **1 relatório por invocação.** Sempre o de menor `NNNN` (mais antigo) ainda não
> processado. Rode `/audit` de novo para o próximo.

Toda a lógica (seleção do relatório, mapeamento por modo, regras de correção e
movimentação) vive **apenas** em `agents/audit_batch/prompt.md` — este comando só
orquestra as duas etapas, sem duplicar aquela lógica.

---

## Etapa 1 — Diagnóstico (apenas leitura; NÃO edita código)

Siga **integralmente** as instruções de `agents/audit_batch/prompt.md`:

1. Detecte a raiz do repo e liste `scripts/data/logs/NNNN_audit_*.json`.
2. Se não houver relatórios → responda "Nenhum relatório de auditoria para
   processar." e **pare** (não há Etapa 2).
3. Selecione o de **menor `NNNN`**, leia-o por completo e classifique cada falha
   por `mode` (tabela de referência do prompt), separando **correções reais** de
   **lacunas operacionais**.

> ⚠️ Nesta etapa você é **só analista**: não edite nenhum arquivo. Toda correção é
> apenas *diagnosticada* aqui.

---

## Etapa 2 — Correção + arquivamento

1. Aplique no código/dado real **apenas** as **correções reais** identificadas na
   Etapa 1 (priorize as que quebram páginas / maior severidade).
2. **Não** corrija lacunas operacionais (capa/bio/lista/conteúdo pendentes que
   exigem rodar um step) nem resultados `ok: true`. Registre que foram dispensados
   — não invente fix.
3. **Somente após ler e aplicar/avaliar as correções**, mova o relatório para
   `scripts/data/log_analysis/processed_logs/` (PASSO de movimentação do prompt).

---

## Regras (atenção à movimentação de arquivos)

- **Separação rígida das etapas:** Etapa 1 = diagnóstico **sem editar**;
  Etapa 2 = correção + arquivamento. Não misture.
- **Movimentação — ponto crítico:** o JSON só sai de `scripts/data/logs/`
  **depois** das correções aplicadas. Destino:
  `scripts/data/log_analysis/processed_logs/` (mesmo nome; sufixo timestamp
  `__YYYYMMDDTHHMMSSz` adicionado automaticamente em caso de colisão).
- **Sem redundância:** o relatório já é o dado estruturado — não gere outro JSON.
  Este comando apenas encadeia as duas etapas do prompt.

---

## Encerramento

Reporte de forma sucinta:
- relatório processado e nº de falhas;
- arquivos de código/dado corrigidos — ou "nenhuma correção necessária";
- lacunas operacionais dispensadas;
- confirmação de que o relatório foi movido para `processed_logs/`.
