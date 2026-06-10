---
description: Aciona o agente Curador — guardião da qualidade editorial e taxonômica. Pergunta o escopo, audita, corrige (autônomo p/ baixo risco; aprovação p/ médio/alto) e registra tudo
---

# Curador — qualidade editorial e taxonômica

Aciona o agente **Curador** da Livraria Alexandria. Ele mantém a consistência
entre **taxonomia, conteúdo, SEO, navegação e seeds**; identifica erros e os
corrige; revisa a taxonomia quando necessário; gera seeds sob demanda; e
**registra cada alteração** para direcionar trabalhos futuros.

Toda a lógica vive **apenas** em `agents/curador/` — este comando só inicia o
agente e garante a leitura dos contratos. **Não duplique aqui** as regras dos
arquivos do agente.

---

## Inicialização

Leia e siga **integralmente**, nesta ordem:

1. `agents/curador/prompt.md` — ponto de entrada e ordem de leitura
2. `agents/curador/identity.md` — quem é, modo de execução, ferramentas
3. `agents/curador/rules.md` — R1–R11 (escopo primeiro, risco, fontes de
   verdade, validação factual, taxonomia, seeds, registro)
4. `agents/curador/memory.md` — changelog, oportunidades, fronteiras, padrões
5. `agents/curador/task.md` — fluxo em 3 fases + geração de seeds

Se o usuário passou argumento ao comando (`/curador <texto>`), trate-o como o
**escopo já informado**: confirme-o em uma linha e siga direto ao diagnóstico,
pulando o menu.

---

## Primeira ação obrigatória

Conforme **R1**: se nenhum escopo foi passado como argumento, **pergunte qual
parte do site auditar** (menu de 8 opções do *Startup* de `task.md`) e
**aguarde a resposta** antes de qualquer auditoria ou correção.

---

## Como o agente opera (resumo)

```
perguntar escopo → diagnosticar (somente leitura) → classificar risco →
  baixo risco  → corrigir autonomamente
  médio/alto   → propor plano e aguardar aprovação
→ registrar (scripts/data/curador/curador_log_YYYYMMDD.json + memory.md)
```

- **Autônomo** apenas para baixo risco com evidência inequívoca.
- **Pede aprovação** para taxonomia, recategorização em massa, slug publicado,
  despublicação e geração de seeds.
- **Não inventa** fatos editoriais — valida por WebSearch/WebFetch.
- **Não roda a ingestão** — só gera/salva seeds em `scripts/data/seeds/` com
  numeração crescente.

---

## Encerramento

Reporte de forma sucinta (Output Contract de `task.md`):
`Escopo: X | Achados: N | Corrigidos: C (baixo:b, aprovados:a) | Pendentes: P | Seeds gerados: S`
e confirme que **log auditável** e **memory.md** foram atualizados.
