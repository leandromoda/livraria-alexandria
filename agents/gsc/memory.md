# GSC — Memory

Memória operacional persistente da análise do **Google Search Console**, mantida
**pelo próprio comando `/analise_gsc`** entre execuções. Consolida os insights de
cada seção: config de domínio, o que é esperado (não é bug), fixes aplicados,
itens em aberto e a linha de base dos números para acompanhar tendência.

Não editar manualmente, exceto para corrigir entradas desatualizadas.

Relatório: https://search.google.com/search-console/index?resource_id=sc-domain:livrariaalexandria.com.br

---

## Config de domínio (Vercel) — verificar SEMPRE em problema de canônica

O app inteiro usa a versão **sem-www** (`livrariaalexandria.com.br`): canonical
tags, sitemap, `NEXT_PUBLIC_SITE_URL`. Config correta no Vercel → Domains
(ajustada 2026-07-10):

- `livrariaalexandria.com.br` (apex) = **Production**, serve direto
- `www.livrariaalexandria.com.br` = **308 Permanent Redirect → apex**
- Proxy Cloudflare na frente (`Server: cloudflare`) — o redirect do Vercel só age
  depois do tráfego chegar nele.

Se a direção estiver invertida (apex→www), reaparecem os alertas de canônica e
soft-404, e há risco de loop com o redirect do `next.config.ts`.

---

## Conhecido-esperado — NÃO é bug (não "corrigir")

| Item | Por quê é esperado |
|------|--------------------|
| `/api/click/[uuid]` bloqueadas pelo robots.txt (centenas, crescendo) | Rota de tracking; cresce com o nº de ofertas. Correto bloquear. |
| 404 de listas antigas com slug acentuado (`...-psicológico`) | Conteúdo removido pelo pipeline; versão sem-acento também não existe. 404 é o correto; Google descarta sozinho. |
| URLs malformadas indexadas (`/&`, `/$`) | Lixo de crawl antigo; 404 correto. |

---

## Insights / decisões (não repetir análise)

- **Middleware de normalização de slug: criado e REMOVIDO** (PR #197). Googlebot
  manda URL percent-encoded (`%C3%B3`), formato em que o regex de marcas
  combinantes não dispara → já cai em 404 limpo; com acento cru dava 500.
  Não readicionar.
- **Next.js 16**: chave `eslint` não existe mais em `NextConfig` (quebra build no
  `.ts`); `middleware.ts` está deprecado em favor de `proxy.ts`.
- **Teste de status**: `curl -sI -A "Mozilla/5.0" <url>` e olhar `HTTP`/`Location`.
  Googlebot sempre envia URLs percent-encoded — testar assim, não com acento cru.

---

## Fixes aplicados (mais recentes no topo)

| Data | Área | Fix | PR |
|------|------|-----|----|
| 2026-07-13 | canônica | `metadataBase` → apex sem-www (`app/layout.tsx`); canonical relativa não resolve mais para o domínio que redireciona | #209 |
| 2026-07-10 | domínio | Redirect www→apex 308 (Vercel Domains); apex vira Production | — (config) |
| 2026-07-10 | middleware | Removido middleware de normalização de slug | #197 |
| 2026-07-07 | build | Remover chave `eslint` inválida e `next.config.js` duplicado | #183 |
| 2026-07-05 | 5xx | `app/error.tsx` — error boundary p/ 5xx transientes do Supabase | #183 |
| 2026-07-05 | canônica | `alternates.canonical` em todas as páginas estáticas + homepage | #183 |
| 2026-07-05 | sitemap | Excluir autores/categorias com 0 livros; noindex dinâmico | #183 |
| 2026-06 | schema | schema:Product filtra ofertas `preco>0`, render condicional do JSON-LD | — |
| 2026-06 | soft404 | Deletado `app/teste/[id]/page.tsx` | — |

---

## Itens em aberto

- **`agents/audit/prompt.md` ainda referencia URLs `www`** — o agente de auditoria
  crawleia `https://www.livrariaalexandria.com.br` (segue o 308 p/ o apex, então
  funciona). Cleanup menor: apontar direto p/ o apex. Baixa prioridade.

---

## Linha de base dos números (para acompanhar tendência)

Uma coluna por seção de análise. Preencher no topo a cada `/analise_gsc`.

| Data | Bloq. robots | Canônica dup. | Não encontr. 404 | 5xx | Soft 404 | Rastreada ñ indexada | Detectada ñ indexada |
|------|-------------|---------------|------------------|-----|----------|----------------------|----------------------|
| 2026-06-23 | 854 | 236 | 222 | 23 | 1 | 186 | 49 |
