# Logs do Curador

Esta pasta guarda os **logs auditáveis** do agente Curador
(`agents/curador/`).

- `curador_log_YYYYMMDD.json` — um arquivo por dia de atividade. Objeto com
  `data` e um array `entries`, uma entrada por alteração aplicada (autônoma ou
  aprovada). Schema em `agents/curador/task.md` → Fase 3a.

A visão legível e sintética desse histórico fica em
`agents/curador/memory.md`.
