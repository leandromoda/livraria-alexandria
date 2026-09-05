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
| **"Cópia, o Google e o usuário selecionaram uma canônica diferente"** — URLs `www.*` | Mesma origem da linha acima de "Cópia sem canônica": o Google crawleou `www` e escolheu o apex. Em 2026-08-09 eram **265 de 270** (livros 197, autores 35, listas 27, categorias 6). Resolve no recrawl. |
| E-mail **"Os seus produtos não se encontram no separador Compras"** (2026-08-08, [WNC-20286279]) | Promocional, **não é apontamento**. Exige Google Merchant Center e, pelo próprio texto, "apenas suportado para Shopify e WooCommerce". O site é afiliado, não loja. **Não aplicável — não reabrir.** |

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
- **⚠️ CORRIGIDO 2026-08-09 — a população de "Excluída pela tag noindex" era
  `/autores/*`, NÃO `/infantis`.** Em 08-08 registrou-se aqui que a validação
  submetida era sobre `/infantis`, com base em conferir 3 URLs que respondiam
  200 sem `meta robots`. O drilldown de 08-09 mostrou a população real: **572
  das 580 URLs são `/autores/*`** (490 apex + 82 `www`), 4 são `/categorias/*`,
  1 é `/infantis` e 3 são `/api/click/*`. **Lição de método: conferir URL que a
  gente supõe não é amostrar a população — abrir o drilldown e agrupar por
  seção antes de concluir qual é a causa.**
- **"Excluída por noindex" pode ser dado obsoleto, não bug vivo.** As 572 URLs
  de autor foram rastreadas entre 2 e 4 de ago; o #263 (merge em 2026-08-08)
  trocou 200+`noindex` por **404** em autor sem livro publicável. Conferido por
  `curl` em 2026-08-09: `/autores/bo-mou`, `/balys-sruoga`,
  `/clark-ashton-smith`, `/bruno-bettelheim` → **404**. Elas migram sozinhas
  para o bucket 404 no recrawl. **Antes de diagnosticar, comparar a data do
  "último rastreamento" da coluna do GSC com a data do fix.**
- **⚠️ O `robots.txt` de produção NÃO é só o de `app/robots.ts`.** O Cloudflare
  injeta um bloco gerenciado ANTES do nosso (medido 2026-08-09 com
  `curl https://livrariaalexandria.com.br/robots.txt`), com `Content-Signal` e
  `Disallow: /` para ClaudeBot, GPTBot, Google-Extended, CCBot, Bytespider etc.
  Isso cria **dois grupos `User-agent: *`** no mesmo arquivo — não quebra o
  `Disallow: /api/` porque a REP manda mesclar grupos do mesmo user-agent, mas
  quem editar `robots.ts` precisa saber que não controla o arquivo inteiro.
  (Curiosidade que confunde: `curl -I` devolve `Content-Length: 112`, o tamanho
  do arquivo de origem; o corpo do `GET` vem bem maior, já com o bloco.)
- **Medido e DESCARTADO em 2026-08-09 — "o sitemap anuncia URLs que 404".**
  `app/sitemap.ts` escolhe autores/categorias por *inner join* no pivot (≥1
  vínculo) enquanto a página filtra por `is_publishable` — divergência da mesma
  classe do bug `status` vs `is_publishable` do #259, e plausível no papel.
  Amostra de **30 URLs** do sitemap (20 autores + 10 categorias) → **30× HTTP
  200, 0 falhas**; e as 4 URLs de exemplo do bucket `noindex` **não estão** no
  sitemap. É divergência teórica, não material. **Não abrir tarefa sem medir de
  novo.**
- **⚠️ Uma unica URL ainda quebrada reprova a validacao do bucket inteiro.**
  Em 2026-08-20 a validacao de "Excluida pela tag noindex" voltou **Falha** com
  604 URLs. Das 604, **594 eram `/autores/*` obsoletas** — nenhuma rastreada
  depois de **08/08** (o #263 mergeou em 08/08), logo o Google nem tinha
  reconferido. O **unico** exemplo rastreado apos o fix era
  `www.../categorias/mentalidade-financeira` (**14/08**), ainda 200 + `noindex`
  — e foi ele que reprovou tudo. **Confirmado pelo proprio GSC**, na pagina
  `index/validation?...&item_key=<key>` (link "ver detalhes" ao lado do estado
  da validacao): ela quebra o total em **`Pendente` 603 / `Falha` 1**. Ou seja,
  o Google reconferiu **uma** URL e ela reprovou; as outras 603 nem foram
  revisitadas. **Sempre abrir "ver detalhes" antes de diagnosticar uma validacao
  reprovada** — o numero grande do bucket nao diz quantas URLs de fato falharam.
  **Lição:** ao ver "Falha", nao presumir que a causa antiga voltou; filtrar os
  exemplos por `ultimo rastreamento > data do fix` e olhar so o que sobrou.
- **O drilldown carrega TODAS as URLs de exemplo no DOM de uma vez — a
  paginacao e so visual.** Nao precisa clicar "proxima pagina" N vezes (o que
  estoura o timeout de 45s do `javascript_tool`): `document.querySelectorAll('tr')`
  ja devolve as 604/410/426 linhas. Snippet que resolve a seção inteira:
  ```js
  const rows=[...document.querySelectorAll('tr')].map(r=>r.innerText)
    .filter(t=>/livrariaalexandria\.com\.br\//.test(t));
  const grp={}; rows.forEach(t=>{const u=(t.match(/https?:\/\/[^\s]*?livrariaalexandria\.com\.br\/[^\s]*?(?=\d{1,2} de |$)/)||[''])[0];
    const w=u.includes('//www.')?'www':'apex';
    const seg=u.replace(/^https?:\/\/(www\.)?livrariaalexandria\.com\.br/,'').split('/')[1]||'(root)';
    grp[seg+'|'+w]=(grp[seg+'|'+w]||0)+1;}); grp
  ```
  ⚠️ **Recarregar a pagina entre drilldowns** (`location.reload()`): o Angular
  **nao remove** as linhas do drilldown anterior do DOM, e a contagem sai somada
  (foi assim que "410" virou 1.014 e "426" virou 536 nesta seção). Conferir
  sempre o `n` extraido contra o numero do bucket antes de concluir qualquer
  coisa.
- **A UI do GSC ignora clique sintetico em `[role="option"]`** (o seletor
  "Linhas por pagina"), mesmo com `mousedown`/`mouseup`/`click` despachados.
  Nao insistir — usar o DOM completo do item acima.
- **Livro que 404 quase sempre e `blacklisted`, mas confirme no banco.** Amostra
  de 8 URLs `/livros/*` do bucket 404 em 2026-08-20: **7 `blacklisted`** e 1
  (`lacos-de-familia`) com `status="publish"` mas `is_publishable=false` — a
  divergencia conhecida das duas colunas. Nos dois casos o 404 e o correto e o
  sitemap (pos-#259, filtra por `is_publishable`) nao anuncia a URL.
- **⚠️ "Listagens do comerciante" tem DOIS avisos diferentes — não confundir.**
  (a) *"nenhum identificador global (GTIN, marca)"* = identificador **ausente**,
  e-mails de 30–31/07 → **lacuna de dado do pipeline**, não age no site.
  (b) *"Valor ISBN13 inválido para `isbn`"* = identificador **presente e
  inválido**, e-mail de 21/08 (`[WNC-10030322]`) → **bug do site**, corrigido no
  #289. O título do e-mail é quase idêntico nos dois casos; **ler a linha do
  problema antes de dispensar como "já conhecido"**.
- **Contar dígitos não é validar ISBN.** O `gtin13` do #259 usava
  `isbnDigitos.length === 13`, o que deixa passar checksum errado, e o `isbn`
  saía cru, sem checagem nenhuma. Medido em 2026-08-21 (PostgREST,
  `is_publishable=true` + `isbn` não nulo, **n=9**): 7 ISBN-13 válidos, 1 com 13
  dígitos e **checksum errado** (`pai-rico-pai-pobre` → `9788576849943`) e 1
  **ISBN-10** (`industrial-economics-and-management-principles`). Hoje
  `lib/isbn.ts` (`toIsbn13`) valida o dígito verificador e converte ISBN-10 →
  ISBN-13. **Qualquer identificador novo no JSON-LD passa por validação de
  formato antes de sair.**
- **Livro sem oferta não emite JSON-LD nenhum — isso limita a verificação.** O
  guard do #216 só renderiza o `Product` quando há `offers`. Ao conferir
  mudanças de schema por `curl`, escolher livro **com oferta**: em 2026-08-21,
  2 dos 4 livros da amostra (`esquadrao-7`,
  `industrial-economics-and-management-principles`) responderam **200 sem
  nenhum bloco `ld+json`** — parece que o fix não aplicou, e não é isso.
  Alternativa quando não há caso com oferta: compilar o helper
  (`npx tsc lib/isbn.ts --outDir … --module commonjs`) e exercitar a função no
  node.
- **UI do GSC congela o renderer**: `screenshot` e `get_page_text` dão timeout
  (o GSC nunca dispara `document_idle`). Extrair com `javascript_tool`. Detalhes
  e snippets prontos na memória de usuário `feedback-chrome-extension-gsc`.

---

## Fixes aplicados (mais recentes no topo)

| Data | Área | Fix | PR |
|------|------|-----|----|
| 2026-08-30 | tracking | **Cliques de oferta não eram gravados desde 18/03**: o `INSERT` em `oferta_clicks` mandava `utm_medium`, coluna inexistente → 400 PGRST204, erro não conferido, redirect 302 normal. Payload alinhado ao schema, erro logado na Vercel, e a auditoria passou a verificar se a linha ENTROU (não só o status do redirect). Migração opcional de paridade em `scripts/sql/2026-08-30_oferta_clicks_utm_medium.sql` | #312 |
| 2026-08-21 | dados estruturados | **"Valor ISBN13 invalido para `isbn`"** (Listagens do comerciante, `[WNC-10030322]`): `livros/[slug]` e `ofertas` emitiam `livro.isbn` cru no JSON-LD, e o `gtin13` so contava digitos. Novo `lib/isbn.ts` valida o digito verificador e converte ISBN-10 → ISBN-13 (prefixo 978 + checksum); `isbn`/`gtin13` so saem quando o ISBN e valido, `sku` segue o valor do banco. Afetava 2 dos 9 livros publicados com ISBN | #289 |
| 2026-08-20 | noindex/404 | **`/categorias/[slug]` sem livro publicavel: 200 + `noindex` → 404** (espelha o #263, que fez o mesmo para autor). Era o que reprovava a validacao do bucket "Excluida pela tag noindex" (604): das 604 URLs, 594 sao `/autores/*` obsoletas (nenhuma rastreada apos 08/08) e o unico exemplo pos-fix era `/categorias/mentalidade-financeira` (14/08), ainda 200 + `noindex`. Sao **6 de 170** categorias afetadas (medido 2026-08-20 via PostgREST), ja fora do sitemap e do indice. Inclui o guard `livrosQueryFailed` para nao transformar falha transitoria do Supabase em 404 cacheado por 24h | #286 |
| 2026-08-09 | robots/links | **"Indexada, mas bloqueada pelo robots.txt" (107 URLs, 100% `/api/click/*`)**: bloquear o crawl não impede a indexação quando a URL é descoberta por link interno seguível. Os 3 links de `/api/click/` (`livros/[slug]` ×2, `ofertas`) tinham só `noopener noreferrer`, enquanto `jogos` e `infantis` já usavam `nofollow sponsored` — daí só `/api/click/` aparecer no bucket. Agora os 5 links de oferta usam `nofollow sponsored`. Também fecha uma não conformidade com a política de links afiliados do Google | #272 |
| 2026-08-08 | sitemap | **Cobertura: 1.144 → 7.762 URLs — confirmado pelo próprio GSC** ("Páginas encontradas" 1.145 → 7.762, processado no mesmo dia). Paginação `.range()` em todas as seções (teto de 1.000 do PostgREST cortava livros em 1.000 de 4.727); `autores` e `listas` restaurados trocando o filtro por coluna inexistente `status_publish` por inner join (0 → 2.152 e 0 → 703); livros passam a filtrar por `is_publishable` (mesmo critério do `notFound()`); `/jogos` e `/infantis` só entram quando a seção tem ≥1 item; erro de query agora vai para `console.error` em vez de virar seção vazia | #259 |
| 2026-08-08 | dados estruturados | `livros/[slug]`: emitir `gtin13` quando o ISBN tem 13 dígitos e parar de emitir `"sku": null`. Atende parcialmente o aviso não crítico de Listagens do comerciante | #259 |
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
  ✅ **ATACADO em 2026-08-21 (#293) — e a causa não era a que estava escrita
  aqui.** Isto dizia "lacuna de dados do pipeline", sugerindo que o dado não
  existia. Existia: o `marketplace_scraper` já recebia o ISBN do Google Books
  na mesma resposta de onde tirava capa e descrição, e **descartava**. A prova
  está no banco — os 4.852 publicados sem ISBN **têm descrição**, ou seja, a
  API achou o livro. Agora o step 4 grava o ISBN, e o novo `isbn_backfill`
  drena o passivo pelo autopilot (~1.000/dia de quota do Google Books).
  ⏳ Acompanhar: o aviso "nenhum identificador global" deve **cair sozinho**
  conforme a cobertura sobe. Reconferir a contagem na próxima seção antes de
  concluir qualquer coisa.
  ➕ **2026-08-21: além de ausente, há ISBN _errado_.** `pai-rico-pai-pobre`
  tem `9788576849943` no banco — 13 dígitos com **dígito verificador inválido**,
  ou seja, não é um ISBN de verdade.
  ✅ **Fechado nas duas pontas:** #289 (site para de propagar) e **#291
  (ingestão para de gravar)** — `scripts/core/isbn.py` valida o checksum e
  converte ISBN-10 → ISBN-13; inválido vira `NULL` **e sai no log**. As duas
  implementações (`lib/isbn.ts` e `core/isbn.py`) foram conferidas uma contra a
  outra em 18 entradas, zero divergências — **ao mexer numa, mexer na outra**.
  ⏳ Resta só **limpar o registro antigo em produção** (TASK-PIPE-034): sem
  impacto de SEO, é higiene de dado.
  ⚠️ Achado de tabela: **`detect_lang_by_isbn` é cego para ISBN-13**
  (TASK-PIPE-033) — casa prefixo de grupo de ISBN-10 com `startswith`, então
  `8532305547` → `PT` mas `9788532305541` → `None`. Não corrigido de propósito:
  mexer nisso reclassifica idioma e mexe no filtro da sinopse.
- **"Detectada, mas não indexada": 15 → 1.444** (2026-08-09 → 2026-08-20).
  Era a previsão registrada em 08-09 e **se confirmou**: as 6,6 mil URLs que o
  #259 pôs no sitemap entraram na fila de crawl de uma vez. É **esperado e
  temporário** — não tratar como regressão. O contrapeso está no lado bom:
  indexadas **5,65 mil (07-19) → 8,97 mil**. Acompanhar a drenagem; só virar
  tarefa se o número **não cair** nas próximas 2–3 seções.
- **Validação de "Excluída pela tag noindex" REPROVOU em 2026-08-20 — a
  premissa de 08-09 estava errada.** Ficou escrito aqui que "a validação deve
  passar" porque o #263 já 404ava autor sem livro. Ela voltou **Falha**, e o
  motivo não era o autor: das 604 URLs do bucket, **nenhuma `/autores/*` foi
  rastreada depois de 08/08**, e o único exemplo pós-fix era
  `/categorias/mentalidade-financeira` (14/08), ainda 200 + `noindex`.
  Corrigido pelo **#286** (categoria sem livro publicável → 404).
  A pagina de detalhes da validação confirma: **`Pendente` 603 / `Falha` 1**.
  ✅ **Validação RESUBMETIDA por Leandro em 2026-08-20**, com o #286 já em
  produção (conferido por `curl` no mesmo dia — as 6 categorias respondem
  **404**, e `folclore-brasileiro` / `true-crime` seguem **200**).
  **NÃO resubmeter na próxima seção** — só conferir o estado em
  `search.google.com/search-console/index/validation?resource_id=sc-domain:livrariaalexandria.com.br&item_key=CAMYCCAC`.
  Resubmeter reinicia o relógio e o Google recomeça a fila de reconferência. Aí sim as ~594 URLs de autor migram para
  **"Não encontrado (404)"** — comportamento correto, não regressão (o bucket
  404 já subiu 278 → 410 por causa disso).
- **"Indexada, mas bloqueada pelo robots.txt": 107 → 108 — não submeter
  validação.** O fix #272 está **em produção e conferido em 2026-08-20**:
  `curl` em `/ofertas` e `/livros/o-hobbit` mostra
  `rel="noopener noreferrer nofollow sponsored"` em todos os `/api/click/*`.
  O bucket drena sozinho no recrawl; 11 dias depois ainda não drenou, o que é
  normal para URL já indexada. Só reconferir a contagem.
- ✅ **RESOLVIDO em 2026-08-20 (#286) — "categoria sem livro devolve 200 +
  `noindex`".** Estava aqui como *baixa prioridade* (4 URLs em 08-09); virou
  prioridade quando se descobriu que era ela que reprovava a validação do
  bucket de 604 URLs. Agora 404a, com o guard `livrosQueryFailed` que a nota
  antiga pedia (erro de query ≠ lista vazia, senão falha transitória do Supabase
  vira 404 cacheado por 24h). **Lição: "poucas URLs" não é o mesmo que "pouco
  impacto" — 5 URLs seguravam a validação de 604.**
- **"Cópia c/ canônica diferente" no apex: 5 → 14** (2026-08-09 → 2026-08-20).
  O bucket todo é 426, dos quais **412 (96,7%) são `www.*`** — esperado. Os 14
  do apex já não são só livros: entraram **`/listas/*`** (4) e `/autores/*` (4),
  rastreados em 18/08. Continua sendo **lacuna do dedup do pipeline, não bug de
  site** (14 em ~9.000 indexadas), mas o número dobrou e a composição mudou —
  **reconferir na próxima seção**; se as listas SEO seguirem crescendo aqui, é
  sinal de sobreposição de conteúdo entre listas, não de duplicata de catálogo.
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

| Data | Bloq. robots | Canônica dup. | Não encontr. 404 | 5xx | Soft 404 | Rastreada ñ indexada | Detectada ñ indexada | Excluída noindex | Indexada mas bloq. |
|------|-------------|---------------|------------------|-----|----------|----------------------|----------------------|------------------|--------------------|
| 2026-08-30 | — | — | — | — | — | — | — | — | — |  ← seção de DESEMPENHO, não de indexação
| 2026-08-20 | 4.235 | 1.277 | 410 | 22 | 2 | 110 | 1.444 | 604 ⚠️ | 108 |
| 2026-08-09 | 3.926 | 1.260 | 278 | 23 | 2 | 74 | 15 | 580 | 107 |
| 2026-08-08 | — | — | — | — | — | — | — | — | — |
| 2026-07-19 | 1.726 | 759 | 294 | 23 | 1 | 192 | 31 | 18 | — |
| 2026-06-23 | 854 | 236 | 222 | 23 | 1 | 186 | 49 | — | — |

### Seção 2026-09-05 — a pegada indexável, medida por espessura

Pedido do Leandro: *"vamos atuar na resolução do mergulho"*. Antes de propor
corte, medi **o que o sitemap de produção realmente anuncia** e quão fina é cada
faixa. Método: `sitemap.xml` de produção cruzado com o Supabase (`livros`,
`autores`, `listas`, `lista_livros`, `livros_autores`, `ofertas`).

**Sitemap: 8.273 URLs.**

| seção | URLs | espessura |
|---|---|---|
| `/livros` | 5.095 | **densas** — 5.031 de 5.186 (97%) com descrição ≥600 caracteres; só 9 sem descrição |
| `/autores` | 2.291 | **2.063 (90%) SEM BIO**; 1.418 (62%) com apenas 1 livro |
| `/listas` | 743 | **437 (59%) com <5 membros**; **as 743** com introdução <200 caracteres |
| `/categorias` | 127 | saudáveis — 129 das 174 com 20+ livros |

> 🔴 **As páginas de livro NÃO são o problema.** Isso contraria a leitura
> intuitiva de "scaled content abuse" num catálogo de 5 mil livros: o conteúdo
> delas é denso. O fino está em **autores e listas**.
>
> E bate com o sinal que o próprio GSC deu em agosto, registrado na seção de
> 2026-08-26: `/listas/` caiu de **21% para 6,7%** da fatia de impressões
> depois do spam update. **O Google já começou a rebaixar exatamente a faixa
> que a medição agora mostra ser fina.**

**Faixa fina somada: 1.855 URLs = 22,4% do sitemap** (437 listas com <5 membros
+ 1.418 autores com ≤1 livro).

Uma página de autor sem bio é, literalmente, um nome e uma lista de um livro.
Uma "lista dos melhores X" com 2 itens e um parágrafo de 150 caracteres não é
uma lista.

**Do lado do *thin affiliate*** (a outra metade do diagnóstico): apenas
**861 de 5.186 livros (17%) têm preço** — 4.325 páginas ainda oferecem link sem
preço. O step 31 (TASK-OFERTAS-009) ataca isso, mas devagar.

#### ✅ GSC LIDO em 2026-09-05 — não houve recuperação

| janela | cliques | impressões | CTR | **posição** |
|---|---|---|---|---|
| **7 dias** (28/08–03/09) — limpa, toda pós-update | **3** | 631 (~90/dia) | 0,5% | **58,1** |
| 28 dias (07/08–03/09) — atravessa o update | 179 | 12,2 mil | 1,5% | 21,9 |
| 3 meses (04/06–03/09) | 466 | 30,1 mil | 1,5% | 19,9 |

⚠️ **Use a janela de 7 dias.** A de 28 dias dá 21,9 só porque metade dela é
anterior ao update; a média é puxada pelo período bom.

**Contra os 56,1 de 26/08, a posição está em 58,1** — piorou marginalmente.
Três semanas de piso estável: não é queda contínua, mas **não há recuperação
espontânea**. O dado que faltava para decidir o corte agora existe, e ele
sustenta agir.

**Sinal lateral que reforça o diagnóstico:** as consultas do topo seguem fora de
intenção comercial — `rule 34 unidade` (89 impressões), `blindsight` (145),
`livraria de alexandria` (141, a biblioteca histórica). Isso pressiona o CTR
para baixo e é coerente com o perfil de conteúdo em escala.

Método: relatório de Desempenho, alternando o intervalo pelo próprio seletor da
UI via `javascript_tool` (o `get_page_text` não atualiza ao trocar de aba, e o
clique no seletor sozinho não basta — ver `feedback_chrome_extension_gsc`).

#### Decisão original: ESPERAR o dado atual do GSC antes de cortar

Proposta apresentada: `noindex` + fora do sitemap para a faixa fina, **sem
404** — a página segue navegável e volta ao índice sozinha quando ganhar corpo
(autor que receber bio, lista que chegar a 5 membros).

**Leandro escolheu não mexer ainda**, e sim medir o GSC primeiro: a última
leitura de posição média é **56,1, de 2026-08-26**. Se houve recuperação
espontânea desde então, o corte pode ser menor ou desnecessário. Mexer em 20%
do sitemap sem dado atual é caro para desfazer.

⚠️ **Bloqueio operacional da seção:** a extensão do Chrome não conectou
(`list_connected_browsers` → `[]`, três tentativas). Pela nota de
`feedback_chrome_extension_gsc`, ela só conecta depois de **abrir o painel
lateral do Claude** — instalar e fixar não basta. Sem isso não dá para ler o
Desempenho atual nem aplicar a migração do `is_bot` pelo SQL Editor.

**Próximo passo, quando o Chrome conectar:** ler posição média e impressões dos
últimos 28 dias e comparar com 56,1 / 52-110 impressões-dia de 26/08. Só então
decidir o critério de corte.

### Seção 2026-08-30 — desempenho (tráfego), não indexação

Pergunta do Leandro: *"e todo o tráfego registrado no GSC?"*, depois de se
descobrir que o site praticamente não registra clique de afiliado.

**Relatório de Desempenho, 26/03/2026 – 29/08/2026:**

| Cliques | Impressões | CTR média | Posição média |
|---|---|---|---|
| **518** | 34,8 mil | 1,5% | 20,4 |

Top consultas: `livraria alexandria` (29 cliques / 153 impr.),
`livraria de alexandria` (5/323 — intenção histórica, não a loja),
`homem aranha de volta ao preto` (3/6), `rule 34 unidade` (2/89),
`blindsight livro` (2/74). Ou seja: o topo é **navegacional de marca** ou
**intenção trocada**, não busca comercial por livro.

> 🔴 **O achado da seção — o rastreamento de cliques de oferta está morto desde
> 2026-03-18.** O `INSERT` em `oferta_clicks` manda `utm_medium`, coluna que
> **não existe** na tabela; o PostgREST devolve **400 PGRST204** e o handler
> **não confere o erro**, seguindo para o redirect 302. Falha silenciosa.
>
> Como foi provado sem adivinhar: a auditoria de conectividade bateu em
> `/api/click/25568c3b-…` às **14:00 de 2026-08-30** e recebeu **302**
> (`0739_audit_connectivity.json`) — e a tabela continuou com **4 linhas**, a
> mais nova de **fevereiro**. Redirect OK, gravação não.
>
> **Controle natural:** `jogo_clicks` e `livro_infantil_clicks` **têm**
> `utm_medium` — e são justamente as duas que seguiram registrando (42 e 4).
>
> Culpado datado: commit **`2e1b104` (2026-03-18)**, intitulado
> *"feat(admin): status do catálogo, origens de tráfego e fix UTM tracking"*.
> Quebrou o que se propunha a consertar.
>
> **Consequência para a leitura de tudo:** os **518 cliques** do período caem
> quase inteiramente dentro da janela cega. Não sabemos quantos visitantes
> clicaram numa oferta — **não há dado**, o que é diferente de haver zero.
> Qualquer conclusão anterior de "ninguém clica nas ofertas" está **suspensa**.

> ✅ **Verificado em produção após o deploy do #312:** batida no
> `/api/click/<id>` devolveu **302** e a tabela foi de **4 para 5 linhas**.
>
> ⚠️ **A linha 5 é sintética** — `user_agent = AlexandriaVerify/1.0 (verificacao
> do fix #312)`, gerada nesta verificação. **Não contar como clique real** em
> análise futura. O primeiro clique genuíno será o 6º.
>
> Detalhe que apareceu de brinde: o `Location` do redirect foi
> `amazon.com.br/s?k=Admirável+Mundo+Novo+Aldous+Huxley` — **URL de busca**, o
> perfil de *thin affiliate* que o step 31 está drenando. Exemplo ao vivo.

Mesma classe do gotcha já registrado para `status_publish` em `autores`/`listas`
(coluna ausente → PGRST204 → operação trava). **Ao mexer em payload de escrita
no Supabase, conferir o schema remoto pelo OpenAPI do PostgREST** — é o que o
`jogos.py` opção V já faz com `verify_supabase()`.

⚠️ **Lição de método, e ela vale além do GSC:** a auditoria de conectividade
cobria essa rota desde sempre e dava **✓** o tempo todo, porque conferia o
**status do redirect** e não o **efeito**. Status é intenção; contagem é efeito.
O novo check `Click API grava o clique` compara o total de `oferta_clicks`
antes e depois da batida.

Colunas fora da tabela em 2026-08-20: Página com redirecionamento **1.809**,
Cópia sem canônica do usuário **38**, Cópia c/ canônica diferente **426**,
Erro de redirecionamento **1**. Indexadas **8,97 mil** / não indexadas
**10,4 mil** (12 motivos). Dados do GSC até **16/08/2026**.
⚠️ O `580` de 08-09 e o `604` de hoje têm a marca **"Validação: Falha"** —
única categoria com validação em curso; todas as outras estão em
"Não foi iniciado".

**Leitura da variação 08-09 → 08-20.** Um bug real, um efeito colateral
esperado e o resto é ruído de crescimento:
- **Bug real — "Excluída por noindex" 580 → 604 e validação REPROVADA.** Causa:
  5 categorias sem livro ainda em 200 + `noindex`. Corrigido no **#286**.
- **"Não encontrado (404)" 278 → 410 (+132)** — é a migração prevista do #263:
  o bucket 404 tem **276 `/autores/*`**. **Esperado, é o destino certo.**
- **"Detectada, mas não indexada" 15 → 1.444** — fila de crawl das 6,6 mil URLs
  do #259. Esperado; ver "Itens em aberto".
- **Bloq. robots +309, Redirecionamento +155, Canônica dup. +156** — crescimento
  de ofertas (`/api/click/*`) e recrawl de `www`. Esperado, sem ação.
- **5xx 23 → 22, soft 404 estável em 2, erro de redirecionamento em 1** — sem
  movimento; dispensados.
- **"Rastreada, mas não indexada" 74 → 110** — população mista (livros 38,
  autores 49, listas 7, resto asset/raiz), nenhum padrão de seção. Decisão do
  Google sobre conteúdo fino, não bug de site.

Colunas fora da tabela em 2026-08-09: Página com redirecionamento **1.654**,
Cópia sem canônica do usuário **35**, Cópia c/ canônica diferente **270**,
Erro de redirecionamento **1**. Método: `javascript_tool` no drilldown de cada
categoria (a UI congela `screenshot`/`get_page_text`), agrupando as URLs de
exemplo por seção.

**Seção 2026-08-08 — sem números do relatório.** A extensão do Chrome não estava
conectada (`list_connected_browsers` → `[]`), então o relatório de indexação não
foi aberto. A seção rodou a partir do Gmail + auditoria do `sitemap.xml` contra
o banco. **Reposto em 2026-08-09.**

**Leitura da variação 07-19 → 08-09.** As altas de "Bloq. robots" (+2.200),
"Página com redirecionamento" (+507) e "Canônica dup." (+501) seguem sendo
consequência esperada do crescimento de ofertas + recrawl de `www`. As três
novidades reais foram: **"Indexada, mas bloqueada" (107)** — bug real, corrigido
nesta seção; **"Excluída por noindex" (580)** — dado obsoleto, ver abaixo; e
**"Cópia c/ canônica diferente" (270)** — 265 são `www.*`, esperado.

**Cobertura do sitemap — confirmada pelo GSC, não só medida localmente:**
"Páginas encontradas" saiu de **1.145 para 7.762**, com o sitemap reenviado e
processado **no mesmo dia** (o prazo previsto de "dias" estava errado; foram
~30 min). Detalhe por seção: livros 1.000 → 4.765, autores 0 → 2.152,
listas 0 → 703, categorias 125 e jogos 11 (inalterados), infantis 0 → 1.

⚠️ **Registrar sempre a URL do sitemap no apex.** O registro antigo apontava
para `https://www.livrariaalexandria.com.br/sitemap.xml` (funciona, mas via
308). E em propriedade de **domínio** (`sc-domain:`) o GSC **recusa caminho
relativo** — digitar `sitemap.xml` dá "Endereço do sitemap inválido"; tem que
ser a URL completa `https://livrariaalexandria.com.br/sitemap.xml`.

**Seção 2026-07-19** — indexadas **5,65 mil** / não indexadas **4,21 mil** (12 motivos).
Categorias fora da tabela acima: Página com redirecionamento **1.147**,
Excluída por `noindex` **18**, Cópia sem canônica do usuário **11**,
Erro de redirecionamento **1**, Cópia c/ canônica diferente **3**.

Leitura da variação: as altas de "Bloq. robots" (+872), "Canônica dup." (+523) e
o novo bloco "Página com redirecionamento" (1.147) são **todas** consequência
esperada do crescimento de ofertas + da migração www→apex — nenhuma é bug.
O único bug real da seção veio **por e-mail**, não pelo relatório: o `Product`
sem `offers` em Jogos (#216).
