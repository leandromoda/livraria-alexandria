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
| **"Página com redirecionamento"** — todas as URLs `www.*` (e `http://www.*`) | É o 308 www→apex funcionando (config de 2026-07-10). O Google cataloga a origem do redirect aqui. Quanto mais ele recrawleia www, mais cresce. **Saudável.** |
| **"Página alternativa com tag canônica adequada"** | Estado **bom**: o Google achou e aceitou a canônica do apex. Subiu junto com o fix de `metadataBase` (#209). Não é problema. |
| **"Cópia sem página canônica selecionada pelo usuário"** — URLs `www.*` | Artefato transitório da migração www→apex: www crawleado antes do 308 virar efetivo. Resolve sozinho no recrawl. |
| 404 de `/livros/<slug>` cujo registro está com `status: "blacklisted"` no banco | Livro despublicado de propósito. Já foi indexado antes; 404 é o correto. **Conferir no banco antes de tratar 404 de livro como bug.** |

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
- **O relatório de indexação não cobre tudo — checar o Gmail.** Problemas de
  **dados estruturados** (rich results) só chegam por e-mail
  (`from:sc-noreply@google.com`), não aparecem em "Por que as páginas não foram
  indexadas". Foi assim que o bug do `Product` de Jogos apareceu (2026-07-17).
- **`Product` exige `offers`/`review`/`aggregateRating`** — sem um deles o Google
  marca erro **crítico** e o rich result não aparece. Padrão obrigatório em toda
  página que emite `Product`: **só renderizar o `<script ld+json>` quando houver
  `offers`**, nunca emitir o Product "pelado". Ver `livros/[slug]` e
  `jogos/[slug]`.
- **UI do GSC congela o renderer**: `screenshot` e `get_page_text` dão timeout
  (o GSC nunca dispara `document_idle`). Extrair com `javascript_tool`. Detalhes
  e snippets prontos na memória de usuário `feedback-chrome-extension-gsc`.

---

## Fixes aplicados (mais recentes no topo)

| Data | Área | Fix | PR |
|------|------|-----|----|
| 2026-07-19 | dados estruturados | `jogos/[slug]`: JSON-LD `Product` era renderizado **incondicionalmente** e saía sem `offers` (10 de 11 jogos com `preco_atual` nulo) → erro crítico "Especifique offers/review/aggregateRating". Guard no render, igual a `livros/[slug]` | #215 |
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
- **`preco_atual` nulo em 10 de 11 jogos** (banco, 2026-07-19) — `offer_status`
  é `"active"` e `url_afiliada` está preenchida, mas o preço não é gravado. É
  **lacuna do pipeline de jogos**, não do site. Enquanto durar, as páginas de
  jogo ficam sem rich result (o guard do #215 evita o erro crítico, mas o
  `Product` deixa de ser emitido). Corrigir o scraper de preço em `scripts/jogos.py`
  → o rich result volta sozinho. Não é tarefa de SEO.
- **5xx (23) é transiente, não regressão** — amostra de 2026-07-19: 4 de 5 livros
  voltaram 200; 1 era `blacklisted` (404). As respostas vieram lentas (>20s,
  cold start + Supabase), o que explica o timeout pontual sob crawl. Count
  estável vs. baseline. Só investigar se subir de forma sustentada.

---

## Linha de base dos números (para acompanhar tendência)

Uma coluna por seção de análise. Preencher no topo a cada `/analise_gsc`.

| Data | Bloq. robots | Canônica dup. | Não encontr. 404 | 5xx | Soft 404 | Rastreada ñ indexada | Detectada ñ indexada |
|------|-------------|---------------|------------------|-----|----------|----------------------|----------------------|
| 2026-07-19 | 1.726 | 759 | 294 | 23 | 1 | 192 | 31 |
| 2026-06-23 | 854 | 236 | 222 | 23 | 1 | 186 | 49 |

**Seção 2026-07-19** — indexadas **5,65 mil** / não indexadas **4,21 mil** (12 motivos).
Categorias fora da tabela acima: Página com redirecionamento **1.147**,
Excluída por `noindex` **18**, Cópia sem canônica do usuário **11**,
Erro de redirecionamento **1**, Cópia c/ canônica diferente **3**.

Leitura da variação: as altas de "Bloq. robots" (+872), "Canônica dup." (+523) e
o novo bloco "Página com redirecionamento" (1.147) são **todas** consequência
esperada do crescimento de ofertas + da migração www→apex — nenhuma é bug.
O único bug real da seção veio **por e-mail**, não pelo relatório: o `Product`
sem `offers` em Jogos (#215).
