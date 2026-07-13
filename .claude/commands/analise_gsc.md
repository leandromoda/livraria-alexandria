---
description: Avalia os apontamentos do Google Search Console (indexação/SEO), diagnostica, aplica correções e atualiza a memória de insights
---

# Análise do Google Search Console

Executa **integralmente no Claude Code** o ciclo de avaliação dos apontamentos do
GSC da Livraria Alexandria: lê os relatórios, diagnostica cada categoria,
separa o que é bug real do que é esperado, aplica as correções e **atualiza
`agents/gsc/memory.md`** com os insights da seção.

O usuário concedeu **autorização permanente** para este fluxo (ver memória
`gsc-autonomia`): commit+push, abrir/mergear PRs com CI verde, mudar config de
domínio no Vercel pelo navegador, ler e-mails do GSC e navegar no Search Console
— **sem pedir confirmação a cada passo**.

---

## Etapa 0 — Carregar contexto (obrigatório antes de tudo)

1. Leia `agents/gsc/memory.md` **por completo**. Ele traz: a config de domínio
   correta, a lista de **conhecido-esperado (não é bug)**, decisões já tomadas,
   fixes aplicados, itens em aberto e a linha de base dos números.
2. Nunca re-analise nem "corrija" itens da tabela **conhecido-esperado**
   (ex: `/api/click/*` bloqueadas, 404 de listas removidas).

---

## Etapa 1 — Coletar os apontamentos

Fonte conforme o que o usuário trouxer (print, e-mail, ou pedido de abrir o
relatório). Ordem de preferência das ferramentas:

1. **Chrome** (`mcp__claude-in-chrome__*`) — abrir o relatório de indexação:
   `https://search.google.com/search-console/index?resource_id=sc-domain:livrariaalexandria.com.br`
   Ler a tabela de motivos e entrar nos drilldowns (`get_page_text` ou
   `javascript_tool` para extrair URLs de exemplo de cada categoria).
2. **Gmail** — quando o usuário citar e-mails do GSC, buscar
   `from:sc-noreply@google.com` no período indicado e ler o motivo.
3. Se o Chrome não estiver conectado: pedir para abrir o Chrome com a extensão
   Claude fixada; enquanto isso, trabalhar com o que o usuário forneceu.

Para cada categoria, capturar **URLs de exemplo** — o padrão das URLs é o que
revela a causa (ex: todas `/api/click/` → esperado; slugs acentuados → removidos).

---

## Etapa 2 — Diagnóstico

Classifique cada categoria em:

- **Esperado** (bater contra `memory.md`) → não age; registra que foi dispensado.
- **Bug real** → diagnostica a causa. Fontes comuns já mapeadas:
  - Canônica duplicada / soft-404 no `www` → **conferir direção do redirect no
    Vercel Domains** (apex=Production, www=308→apex). Ver `memory.md`.
  - 5xx em páginas reais (`/livros/*`) → geralmente timeout transiente do
    Supabase; `app/error.tsx` já trata o render. Investigar se persistente.
  - 404 de conteúdo que ainda deveria existir → checar slug no banco.

**Validar status com curl** antes de concluir:
`curl -sI -A "Mozilla/5.0" <url>` → olhar `HTTP`/`Location`. Googlebot envia URLs
percent-encoded — testar nesse formato.

---

## Etapa 3 — Correção

Aplique as correções dos **bugs reais**, seguindo o SOP de git
(ver memória `fluxo-de-deploy-e-git`): branch a partir de `origin/main` → commit
com trailer `Co-Authored-By` → push → `gh pr create` → checar CI verde →
`gh pr merge --squash --delete-branch`.

- Mudanças de **config de domínio no Vercel** são feitas pelo navegador (Chrome),
  não em código.
- **Um PR por vez**; fechar o ciclo antes de abrir outro.
- Não "corrigir" itens esperados nem forçar redirect para alvos inexistentes
  (404 de conteúdo removido é o comportamento correto).

---

## Etapa 4 — Atualizar a memória (obrigatório)

Atualize `agents/gsc/memory.md`:

1. **Linha de base dos números** — adicione uma linha no topo da tabela com a
   data da seção e as contagens de cada categoria (para acompanhar tendência).
2. **Fixes aplicados** — registre cada correção (data, área, fix, PR).
3. **Conhecido-esperado** — se descobriu um novo padrão que é esperado, adicione.
4. **Itens em aberto** — adicione/remova conforme resolveu ou descobriu.
5. **Insights** — qualquer aprendizado que evite re-análise futura.

Se `agents/gsc/memory.md` fizer parte de um PR de código, inclua a atualização no
mesmo PR; se a análise não gerou mudança de código, commite a atualização da
memória isoladamente.

---

## Encerramento

Reporte de forma sucinta:
- categorias avaliadas e a variação vs. a última linha de base;
- bugs reais corrigidos (com PR) — ou "nenhuma correção necessária";
- itens dispensados por serem esperados;
- confirmação de que `agents/gsc/memory.md` foi atualizado;
- próximos passos manuais no GSC (ex: submeter "Validar correção").
