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

- **⚠️ Filtro por coluna inexistente no Supabase NÃO quebra o build — vira seção
  vazia em silêncio.** Foi assim que o sitemap chegou a 2026-08-06 anunciando
  0 autores e 0 listas (duração do defeito não apurada):
  `.eq("status_publish", true)` em `autores`/`listas` (colunas que não
  existem) devolve erro 400, e o `?? []` do `sitemap.ts` transformava o erro numa
  lista vazia. Build verde, deploy verde, seção sumida.
  **Ao auditar SEO, conferir a _contagem por seção_ do `sitemap.xml` contra o
  banco — não basta o arquivo existir e o build passar.** Comando:
  ```bash
  curl -s https://livrariaalexandria.com.br/sitemap.xml | grep -o "<loc>[^<]*</loc>" \
    | sed 's|<loc>https://livrariaalexandria.com.br||;s|</loc>||' \
    | awk -F/ '{print ($2==""?"(home)":$2)}' | sort | uniq -c | sort -rn
  ```
- **Teto de 1.000 linhas do PostgREST vale para o sitemap também.** Toda query de
  sitemap precisa de `.range()` paginado — as páginas de índice já faziam isso
  (`autores/page.tsx`, `listas/page.tsx`), só o sitemap tinha ficado para trás.
- **Sitemap e `noindex` não podem se contradizer.** `/jogos` e `/infantis` emitem
  `robots: noindex` quando a seção está vazia; enquanto vazias, não podem entrar
  no sitemap. Origem do alerta de 2026-07-28. Hoje entram condicionalmente.
- **Critério de publicação do livro é `is_publishable`, não `status="publish"`.**
  A página usa `is_publishable` para o `notFound()`; o sitemap usava `status`.
  As duas colunas divergem em alguns registros (4.691 vs 4.686 em 2026-08-06) —
  e a diferença virava 404 anunciado no sitemap.
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
| 2026-08-06 | sitemap | **Cobertura: 1.144 → 7.708 URLs.** Paginação `.range()` em todas as seções (teto de 1.000 do PostgREST cortava livros em 1.000 de 4.727); `autores` e `listas` restaurados trocando o filtro por coluna inexistente `status_publish` por inner join (0 → 2.139 e 0 → 697); livros passam a filtrar por `is_publishable` (mesmo critério do `notFound()`); `/jogos` e `/infantis` só entram quando a seção tem ≥1 item; erro de query agora vai para `console.error` em vez de virar seção vazia | #PR |
| 2026-08-06 | dados estruturados | `livros/[slug]`: emitir `gtin13` quando o ISBN tem 13 dígitos e parar de emitir `"sku": null`. Atende parcialmente o aviso não crítico de Listagens do comerciante | #PR |
| 2026-07-19 | dados estruturados | `jogos/[slug]`: JSON-LD `Product` era renderizado **incondicionalmente** e saía sem `offers` (10 de 11 jogos com `preco_atual` nulo) → erro crítico "Especifique offers/review/aggregateRating". Guard no render, igual a `livros/[slug]` | #216 |
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

- **ISBN ausente em ~99% dos livros** (amostra de 300 publicados em 2026-08-06:
  297 sem `isbn`; só 3 com ISBN de 13 dígitos). É a causa raiz do aviso
  **"Listagens do comerciante: nenhum identificador global (GTIN, marca)"**
  (e-mails de 2026-07-30 e 31). O fix de código já emite `gtin13` quando há
  ISBN — o aviso só some de verdade quando o pipeline preencher a coluna.
  **Lacuna de dados do pipeline, não tarefa de SEO** — mesmo padrão do
  `preco_atual` de jogos. Não reabrir como bug do site.
- **Validar no GSC após o deploy do #PR**: submeter "Validar correção" em
  *Excluída pela tag "noindex"* e reenviar o `sitemap.xml`. Acompanhar se
  "Detectada, mas não indexada" sobe (esperado e temporário: 6,5 mil URLs novas
  entraram na fila de crawl de uma vez).
- **`agents/audit/prompt.md` ainda referencia URLs `www`** — o agente de auditoria
  crawleia `https://www.livrariaalexandria.com.br` (segue o 308 p/ o apex, então
  funciona). Cleanup menor: apontar direto p/ o apex. Baixa prioridade.
- **`preco_atual` nulo em 10 de 11 jogos** (banco, 2026-07-19) — `offer_status`
  é `"active"` e `url_afiliada` está preenchida, mas o preço não é gravado. É
  **lacuna do pipeline de jogos**, não do site. Enquanto durar, as páginas de
  jogo ficam sem rich result (o guard do #216 evita o erro crítico, mas o
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
| 2026-08-06 | — | — | — | — | — | — | — |
| 2026-07-19 | 1.726 | 759 | 294 | 23 | 1 | 192 | 31 |
| 2026-06-23 | 854 | 236 | 222 | 23 | 1 | 186 | 49 |

**Seção 2026-08-06 — sem números do relatório.** A extensão do Chrome não estava
conectada (`list_connected_browsers` → `[]`), então o relatório de indexação não
foi aberto e **as contagens por categoria não foram coletadas**. A seção rodou a
partir do Gmail (`from:sc-noreply@google.com`) + auditoria direta do
`sitemap.xml` contra o banco. Repor os números na próxima seção com o Chrome
conectado — sem isso não dá para ler tendência de 07-19 para cá.

Cobertura do sitemap medida nesta seção (por contagem do XML vs. `count=exact`
no PostgREST): **antes 1.144 URLs → depois 7.708**. Detalhe: livros 1.000 →
4.727, autores 0 → 2.139, listas 0 → 697, categorias 125 (inalterado),
jogos 11 (inalterado), infantis 0 → 1.

**Seção 2026-07-19** — indexadas **5,65 mil** / não indexadas **4,21 mil** (12 motivos).
Categorias fora da tabela acima: Página com redirecionamento **1.147**,
Excluída por `noindex` **18**, Cópia sem canônica do usuário **11**,
Erro de redirecionamento **1**, Cópia c/ canônica diferente **3**.

Leitura da variação: as altas de "Bloq. robots" (+872), "Canônica dup." (+523) e
o novo bloco "Página com redirecionamento" (1.147) são **todas** consequência
esperada do crescimento de ofertas + da migração www→apex — nenhuma é bug.
O único bug real da seção veio **por e-mail**, não pelo relatório: o `Product`
sem `offers` em Jogos (#216).
