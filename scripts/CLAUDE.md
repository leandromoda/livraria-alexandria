# CLAUDE.md — Pipeline Local · Livraria Alexandria

> Este arquivo é exclusivo do pipeline de ingestão (`/scripts`).
> O CLAUDE.md da raiz cobre o site Next.js.
>
> **Alterações de código seguem o "Fluxo de trabalho Git" do CLAUDE.md da raiz**
> (branch → validar → commit → push → PR → merge squash → pull main), via `git`/`gh`
> CLI, com o GitHub Desktop fechado.

## Estado do projeto

O arquivo `state/project_state.json` (na raiz do repositório) é a fonte de verdade do estado atual do projeto: métricas do pipeline, steps ativos, tasks abertas, bugs conhecidos e decisões de arquitetura. Consulte-o antes de iniciar qualquer tarefa de maior escopo.

---

## Execução

```bash
cd scripts
python main.py
```

O menu interativo pede idioma e tamanho do pacote. A geração LLM usa o **claude CLI**
(sem escolha de provider); só steps legados (author_bio, auditoria de conteúdo)
ainda exibem o menu de provider.

### Menu — numeração por grupos (WS9+WS10, 2026-06)

O topo roteia para submenus pelas teclas **1-6** (navegação) + letras de ação
(S/G/A/I/O/M/C/E/**W**). Dentro de cada submenu, as opções têm faixas sem colisão:

| Submenu | Faixa | Itens |
|---|---|---|
| Ingestão | 1-4 | seeds, enrich, resolver ofertas, scraper |
| Pré-processamento | 5-9 | slugs, slugify autores, dedup autores, dedup, review |
| Geração de Conteúdo | 10-19 | 10 categorizar, 10R reset, 11 sinopses, 12 capas, 13 bios |
| Publicação | 20-30 | 20 QG, 21 publicar, 22 autores, 23 categorias, 24 ofertas, 25 listas SEO, 26 publicar listas, 27 reparar ofertas, 28 fix URLs, 29 importar offer_list, 30 reparar relações |
| Auditoria/QA | 40-61 | 40 preços, 41 conectividade, 42 conteúdo, 43 reparar ruins, 44 reparo slug, 45 blacklist, 46 export auditoria, 47 integridade, 48 listas, 49 autores sem bio, 50 veracidade títulos, 51 consistência, 52 reprocessar blacklist, 53 QA remediação, 54 capas, 55 classificação, 56 QA auditoria completa do site, 57 QA passe completo, **58 remediação de capas, 59 reconcile sinopse, 60 marcar sinopses p/ regen, 61 ingerir relatórios de auditoria** |
| Exports | 91-94 | transcripts/estado |
| Banco | 95-97 | backup, restore, recover |

**Opção W** (topo, letra): aguarda o reset da sessão Claude PRO (cooldown) e roda o G
automaticamente ao reiniciar. Útil para deixar a máquina trabalhar sem supervisão.

**Opção G sem confirmações**: G assume plano e LLM como SIM — não pede confirmação
interativa. Inclui: regen sinopse (antes da fase LLM) → remediação mecânica
(ingest+capas+reconcile) → reparo de ofertas (**offer_price_monitor** +
fix_affiliate_urls + publish_ofertas.run_repair).

> **Monitor de preços no G (desde 2026-07-26).** Antes disso o step 17 só era
> alcançável manualmente (menu, letra M, `qa.run("prices")`) e, como o uso é
> autopilot por padrão, **nunca rodava**: última execução em 2026-04-20, com 2
> linhas em `offer_price_log` e 78 livros com `preco_updated_at` — o site ficou
> com 4.577 das 4.579 ofertas ativas sem preço. Agora roda a cada passe do G com
> cota fixa `PRECO_POR_CICLO` (padrão **50** livros, `0` desliga), **antes** do
> `run_repair` para o preço coletado sair republicado no mesmo ciclo. Falha do
> monitor é capturada em `try` próprio — bloqueio de marketplace é transitório e
> não pode derrubar o reparo de ofertas.

### ⚠ O monitor lia o preço da página de BUSCA — corrigido em 2026-08-23

O `offer_price_monitor` tinha `PRICE_SELECTORS` próprios, de **página de
produto**, e os aplicava direto sobre o `offer_url`. Só que o `offer_url` que o
`offer_resolver` produz é uma URL de **busca**: medido no `books.db` em
2026-08-23, **4.849 dos 4.856 livros publicados (99,9%)** têm URL de busca
(2.477 Amazon `/s?k=`, 2.372 ML `lista.`); só 7 são `/dp/` e nenhuma é `/MLB-`.
Então `select_one('.a-price .a-offscreen')` devolvia o preço do **primeiro card**
da busca, de qualquer item que estivesse lá.

Amostra do mesmo dia (n=3 buscas reais na Amazon, 2 utilizáveis — a terceira
esgotou os 3 retries em 503): a busca de *"O Guia do Mochileiro das Galáxias"*
devolveu **4 preços — R$ 45,83 / 76,97 / 33,45 / 19,00** — sendo dois de
**outros livros da série**. Não era só cobertura baixa: era preço possivelmente
de outro produto, com o link mandando o usuário para uma busca em vez do item
precificado.

Hoje a leitura é em **2 saltos** (busca → página do produto), reusando
`marketplace_scraper._resolve_produto`, e o `offer_url` é **promovido ao
deep-link** do produto. A republicação no Supabase é automática:
`publish_ofertas._payload_hash` já inclui `url_afiliada` e `preco`, então o
`run_repair` do mesmo passe detecta a mudança. Ver TASK-OFERTAS-004.

Três detalhes que os testes fixam (`tests/test_produto_2saltos.py`):

- **Regime `estrito` para livros.** O portão de jogos (≥60% dos tokens) aceita
  *"Praticamente Inofensiva — Volume 5. Série O Mochileiro das Galáxias"* para
  *"O Guia do Mochileiro das Galáxias"* (2 de 3 tokens = 0,67). Livro tem série,
  jogo não — por isso o regime frouxo nunca doeu em jogos. Com `estrito=True`
  exige-se **todos** os tokens significativos (ou similaridade ≥0,85) mais o
  sobrenome do autor no texto do card.
- **Escolhe o card de MAIOR pontuação**, não o primeiro compatível — na mesma
  busca, *"O guia definitivo do mochileiro das galáxias"* também passa o portão.
  O portão de jogos não mudou; só a escolha entre os aprovados.
- **Sem fallback de raspar a busca**, e sem gravar `preco_updated_at` quando a
  resolução falha. Antes o `UPDATE` de sucesso rodava mesmo sem preço, então o
  livro ia para o fim da fila como se tivesse sido resolvido.

A fila (`fetch_pending`) passou a pôr **quem nunca teve preço antes do
round-robin** por `preco_updated_at`: em 2026-08-23 só 553 dos 4.856 publicados
(11%) tinham sido visitados.

> **Medição de aproveitamento: o número mede o bot wall, não o mecanismo.**
> No dry-run de validação (**2026-08-24**, n=8) **8 de 8 deram `error`**: a
> Amazon respondeu 503 nas 3 tentativas e o ML devolveu a página *"Para
> continuar, acesse sua conta"* (40 KB, **zero** cards de resultado).
>
> ⚠️ *Correção de registro (2026-08-26): este dry-run estava datado aqui como
> 2026-08-23. Ele rodou em 24/08 — o log é `pipeline_2026-08-24_19-49-11`. As
> medições do GSC e do `books.db` citadas nesta seção são mesmo de 23/08.*
>
> **A primeira rodada real do G confirmou o quadro** (log
> `pipeline_2026-08-24_20-09-02`, ~23 h, commit `118574c`):
>
> | | Pré-fix (23/08) | Pós-fix (24/08) |
> |---|---|---|
> | `Ativos` / 50 | 28 | **4** |
> | `Erros` / 50 | 21 | **45** |
> | Duração do lote | 4m17s | **15m21s** |
> | HTTP 503 na janela | — | **82, todos `amazon.com.br`** |
>
> **A queda não é regressão, e a comparação não é válida como tal:** os 28
> "ativos" de antes vinham da página de busca e podiam ser de outro produto, e
> os 82 bloqueios caem todos dentro desta janela. O que a rodada **provou** é o
> mecanismo: os livros com deep link `/dp/` subiram de 7 para 14, e *Phantastes*
> saiu de URL de busca para `amazon.com.br/dp/6556891150?tag=livrariaalexa-20`.
> Com o muro aberto o aproveitamento continua sem medição. `PRECO_POR_CICLO`
> fica em 50 até lá: subir a cota junto com a troca de mecanismo confundiria as
> duas variáveis, e sob muro só multiplicaria 503.

### API de catálogo do Mercado Livre — a saída oficial do bot wall

Desde 2026-08-29 o preço e o deep link do ML saem da **API oficial**, com o
scraping como fallback (`core/ml_api.py`, TASK-OFERTAS-005). Motivo medido: num
passe real do G o scraping entregou **4 de 50** livros — Amazon com 503 nas 3
tentativas, ML pedindo login.

**A Amazon não tem saída equivalente.** A PA-API foi desligada em 15/05/2026 e a
Creators API que a substitui exige **≥10 vendas qualificadas em 30 dias** —
bloqueio circular enquanto o tráfego estiver no chão. São 51% do catálogo.

Portas sondadas (`tools/probe_ml_api.py`, `tools/probe_ml_endpoints.py`):

| Endpoint | |
|---|---|
| `/oauth/token` **client_credentials** | ✅ token de 6 h, sem login |
| `/sites/MLB/search` | ❌ 403 mesmo com token |
| `/items/{id}` | ❌ fechado |
| `/products/search` | ✅ **é a porta** — traz `BOOK_TITLE`, `AUTHOR`, `GTIN`, `domain_id` |
| `/products/{id}/items` | ✅ traz o `price` |

Deep link: `https://www.mercadolivre.com.br/p/{catalog_product_id}` — a API não
devolve `permalink`, mas essa forma é a canônica, confirmada em navegador
logado. Requisição automatizada cai em `account-verification`; isso é o muro
contra robô, **não** URL inválida.

> #### ⚠ O portão tem DUAS folhas, e cada uma custou uma medição
>
> **`/products/search` nunca responde "não achei"** — devolve o mais parecido.
> 97% "encontram" produto, e esse número sozinho engana.
>
> 1. **`AUTHOR`** — sem ele, *"Sob a Roda"* (Hermann Hesse) resolvia para
>    *"Sob a Selva"*.
> 2. **Título, com `_titulo_score(estrito=True)`** — só o autor não basta:
>    *"Mistério no Castelo de Chimneys"* passava apontando para *"Um mistério
>    no Caribe"*, **outro livro da mesma autora**. É a mesma classe do falso
>    positivo de série que o scraping já tratava, então a regra é reusada em
>    vez de reescrita.
>
> E a escolha é do **melhor** candidato aprovado, não do primeiro: com
> "primeiro que passa", *"Comunicação Não Violenta"* resolvia para o *"Kit
> Comunicação Não Violenta + Vive"* a R$ 151,43 — um combo. Sem desistir no
> primeiro sem preço, que custaria cobertura à toa.

**Aproveitamento medido (n=70 livros com oferta ML, 2026-08-29): 37%.**

**Confirmado em execução real** (passe do G de 2026-08-29): 50 livros em
**11m26s** renderam **12 preços — os 12 vindos da API do ML**. Contra 4 (24/08)
e 3 (27/08) das duas rodadas só-scraping: **6-8% → 24%**.

> ⚠️ **O 41% de 29/08 07:54 NÃO era tendência — o passe seguinte deu 20%.**
> Ficou escrito aqui, no mesmo dia, que o rendimento havia subido para 41% e que
> isso era "coerente com a fila servir o ML primeiro". O passe das 10:28 (log
> `pipeline_2026-08-29_10-28-52`, commit `410525a`) rendeu **`Ativos: 30 |
> Erros: 120 | Total: 150` = 20%**, metade. Quatro passes reais:
>
> | Passe | commit | cota | ativos | aproveitamento |
> |---|---|---|---|---|
> | 27/08 19:22 (só scraping) | `b94956f` | 50 | 3 | 6% |
> | 29/08 05:45 (API do ML) | `80a9d83` | 50 | 12 | 24% |
> | 29/08 07:54 (+ roteamento) | `8bbef41` | 150 | 62 | 41% |
> | 29/08 10:28 | `410525a` | 150 | 30 | **20%** |
> | **soma dos 3 passes com API** | — | **350** | **104** | **~30%** |
>
> **Use ~30% como expectativa**, não 41% nem os 58% da bancada antiga. A lição
> de método é a de sempre neste arquivo: um passe é n=1, e ler tendência em dois
> pontos com três variáveis mudando junto foi exatamente o erro.
>
> **O que o passe de 10:28 permitiu concluir**, cruzando o
> `0736_audit_prices.json` com o `books.db`: os **120 erros eram 120 URLs do
> Mercado Livre — nenhuma da Amazon**. Com `PRIORIZAR_ML=1` o passe inteiro é
> ML, então o teto do monitor hoje é a cobertura do catálogo do ML, não mais o
> bot wall da Amazon. Isso desloca o alvo: ganhar aqui é melhorar o casamento
> na `/products/search`, não driblar bloqueio.
>
> ⚠️ **Esse cruzamento teve de ser feito à mão porque o log não dizia.** A única
> saída era `Ativos: N | Erros: N`, e "a API rendeu menos" e "o scraping apanhou
> do bot wall" — correções opostas — eram indistinguíveis. Desde 2026-08-29 o
> monitor emite uma segunda linha agregada,
> `[MONITOR] Resolução: ml_api_ok=… | ml_api_miss=… | scrape_sem_pagina=…`
> (`marketplace_scraper._resolve_stats`, testes em `tests/test_resolve_stats.py`).
> Agregada, nunca por item — log por item foi o que inchou os logs de julho.

O mesmo passe expôs a assimetria que reordenou a fila:

| | ML (API) | Amazon (scraping) |
|---|---|---|
| custo por livro | ~1-2 s | **~13,7 s** |
| aproveitamento | 37% | **~0%** sob bot wall |

A fila antiga começava com **12 de 12 livros da Amazon** — metade do passe ia
para o lado que não entrega. Desde então `fetch_pending` põe o ML primeiro
(`PRIORIZAR_ML=0` reverte) e `PRECO_POR_CICLO` subiu de 50 para **150**.

⚠️ Uma medição anterior registrou **58%** e está **errada** — ela validava só o
autor, sobre `results[0]`, então contava como acerto casamentos que a segunda
folha do portão reprova. O 37% é do cliente real. Contra os ~0% que o ML entrega
sob bot wall hoje, ainda é a diferença entre parado e andando.

**Pré-voo no G:** `ml_api.status()` devolve `ok | sem_credencial | auth | erro`,
mesmo contrato do `claude_runner.session_status()`, e roda **antes** do monitor
de preços. Sem ele o passe tentaria a API livro a livro, falharia em todos e
cairia no scraping — que sob bot wall custa ~25 s de backoff por livro. Falha do
pré-voo **não** bloqueia: o scraping segue válido para a Amazon e como fallback.

Credenciais em `scripts/.env`: `ML_CLIENT_ID`, `ML_CLIENT_SECRET`.

#### O pré-voo ABRE a janela — avisar no log não resolve

Pedido do Leandro em 2026-08-29: *"não adianta o G só avisar, tem que abrir uma
janela para logar quando necessário"*. Está certo — o log de 2026-08-24 durou
**~23 h**, e um aviso em arquivo às 3 da manhã não conserta nada.

`core/auth_prompt.pedir()` abre a página onde a credencial se resolve e destaca
o pedido no console. Ligado nos **dois** pré-voos: API do ML (→ DevCenter) e
sessão do claude CLI (→ docs; o login de fato é `claude auth login`, no
terminal).

⚠ O caro é o do **claude CLI**: sinopse é o hard-block do Quality Gate, então
sessão expirada = **zero publicações** até alguém perceber.

Três propriedades que `tests/test_auth_prompt.py` fixa, porque quebrar qualquer
uma transforma a ajuda em problema:

- **NÃO bloqueia.** Nada de `input()` — o teste inclusive varre o fonte atrás de
  `input(`/`getpass`/`sys.stdin`. Parar o pipeline esperando digitação custaria
  a madrugada inteira.
- **Uma vez por processo, por serviço.** Sem essa guarda, 23 h de laço abririam
  dezenas de abas do mesmo endereço.
- **`ABRIR_LOGIN=0` desliga**, para headless/CI. E navegador que levanta exceção
  (servidor sem display) não derruba o passe.

#### O roteamento deixou de obedecer o seed (2026-08-29)

`offer_resolver.resolve_offer` ignorava a assimetria entre os marketplaces e
despachava pelo campo `marketplace` do seed — que é palpite de quem escreveu o
JSON, e a distribuição mostrava isso: **8.798 'amazon' contra 8.778
'mercado_livre'**, quase moeda ao ar.

Só que os dois lados não são equivalentes. Livro roteado para a Amazon hoje é
beco sem saída: fica com URL de busca e sem preço — o perfil de *thin affiliate*
que o spam update penaliza. Hoje o step 3 tem três degraus:

1. **API do ML confirma** → deep link da PÁGINA DO PRODUTO, **com preço já na
   mão**. O livro nasce com oferta de verdade, sem esperar o monitor.
2. **API não confirma** → URL de busca do ML ("não casou agora" ≠ "não existe").
3. **`FORCAR_ML=0`** → obedece o seed (comportamento antigo).

`update_offer` grava `marketplace` e `preco_atual` junto: sem isso o banco diria
'amazon' com URL do ML, e o `publish_ofertas` publicaria a contradição.
Corrigido de quebra um `'Amazon'` maiúsculo que não casava com nenhum ramo e
resolvia para `None`.

#### Indisponível na origem → RESGATE no ML antes de despublicar

"Sumiu da Amazon" não é "sumiu do mundo". `offer_price_monitor._resgatar_no_ml`
tenta o catálogo do ML **antes** da contagem de detecções: achando o produto, a
oferta é refeita ali e o livro **segue publicado**, agora com preço e deep link
— melhor do que estava antes de sumir.

A ordem importa: despublicar e republicar depois deixaria a página fora do ar no
intervalo, e num site sob rebaixamento de spam update é o que menos se quer.

### Gargalo de publicação — o autopilot é o único caminho

**Fato estrutural (medido):** publicar um livro exige, no Quality Gate, uma
**sinopse** — e sinopse **só** o LLM (claude CLI) gera. Todo livro que já tem
sinopse **já está publicado** (0 publicáveis represados); o backlog restante está
100 % preso em `status_synopsis=0`. Logo **a taxa de publicação = a taxa de geração
de sinopses = a quota da sessão PRO** (janela de 5h, ~1 janela de sinopses por
esgotamento). Nenhum step não-LLM aumenta publicações; rodar horas de não-LLM
depois da quota esgotar adiciona ~0 publicações. Isso **não** é step faltando — é
o teto de throughput do LLM.

**Como o autopilot ataca isso (G, opção padrão):** quando a fase LLM esgota a
sessão, o G entra em **loop multijanela** — drena/publica não-LLM → aguarda o
reset → retoma a fase LLM → publica — atravessando quantas janelas de 5h forem
necessárias, até o backlog de conteúdo (sinopse+categoria) zerar, uma janela não
progredir (guard anti-giro) ou o usuário dar Ctrl+C. Assim, **quanto mais longa a
seção, mais publicações**, sem re-execução manual. (`_run_gargalo` em `main.py`.)

> **A espera produtiva suspende o dreno quando o não-LLM seca (desde 2026-07-31).**
> `autopilot.run()` já roda até exaurir sozinho, mas a espera produtiva o
> re-invocava a cada ≤5 min durante todo o cooldown de ~5h — e **cada invocação
> nova zera os guards internos** (`step_sem_progresso`, `ciclos_sem_qg_avanco`),
> então eles nunca acumulavam entre chamadas. Medido nos 5 logs substanciais de
> 2026-07-23..07-30 (n=469.695 linhas; contagem por `List Composer finalizado` /
> `QUALITY GATE END` / `[AUTOPILOT] Ciclo 1`): **93 invocações do autopilot,
> 732 passes de `list_composer` para 21 listas criadas (97% sem saída)** e 320
> passes de `quality_gate`; só LISTAS+QUALITY somaram **430.072 linhas = 91,6%**
> de tudo que foi escrito. O caso mais limpo é
> `pipeline_2026-07-30_15-35-57` (3h50): 16 invocações, 168 passes de
> `list_composer`, **0 listas criadas e 0 livros aprovados**. Hoje o dreno só
> repete se a invocação anterior reduziu `count_pending`; seco, o G apenas dorme
> o cooldown e re-checa a cada 30 min (`DRENO_SAFETY_S`), mesma ideia do
> `REPAIR_SAFETY_EVERY`. Lógica em `core/drain_loop.py` (isolada de imports
> pesados para ser testável), testes em `tests/test_drain_loop.py`.

> ⚠ **Corrigindo a expectativa acima — o fix de 2026-07-31 funcionou, e mesmo
> assim o volume de log quase não caiu.** Medido em 2026-08-08 nos 3 logs
> substanciais seguintes (`pipeline_2026-08-04_21-21-31`, `…08-05_21-12-07`,
> `…08-06_21-17-39`; ~11h cada, n=93.827 / 91.714 / 94.695 linhas; mesma
> contagem por `List Composer iniciado` / `QUALITY GATE END | Aprovados=N
> Reprovados=N` / `Lista (temática )?criada`):
>
> | | 08-04 | 08-05 | 08-06 |
> |---|---|---|---|
> | LISTAS+QUALITY | 89,2% | 89,2% | **89,6%** |
> | passes de `list_composer` | 52 | 51 | 52 |
> | listas criadas | 2 | 5 | 5 |
> | passes de `quality_gate` | 59 | 57 | 59 |
> | livros aprovados (soma) | 15 | 28 | 37 |
>
> **O dreno de fato suspende** — no log de 08-04, depois que o não-LLM seca às
> 00:38, o autopilot passa à cadência de ~31 min (00:43:56 → 01:15:23 →
> 01:46:58), exatamente o `DRENO_SAFETY_S`. O que os 91,6% mediam não era só o
> giro da espera: `quality_gate` e `list_composer` estão na lista `STEPS` do
> `autopilot.run()` (`steps/autopilot.py`), executada inteira **a cada volta do
> laço de ciclos** — inclusive na fase produtiva, quando o dreno está
> legitimamente publicando. Por isso 91,6% → 89,2%.
>
> Atacado em duas frentes, sem mexer no `drain_loop`: (1) **verbosidade** — o
> log por item virou contador agregado em `list_composer` e `quality_gate`
> (reprovação só por falta de sinopse é o teto de quota, não informação nova);
> (2) **cadência** — guard para não re-rodar `list_composer` sem publicação
> nova. Ver os comentários no topo dos dois steps.

> **Regra ao diagnosticar gargalos operacionais:** o uso do pipeline é, por
> padrão, **autopilot (G, com fallbacks não-LLM)**. **Nunca** oriente o usuário a
> "rodar o step X" / "rodar a opção N" como solução — isso é atalho manual. Se um
> step realmente não estiver coberto pela execução automática, a ação correta é
> **incorporá-lo ao autopilot** (G/`llm_orchestrator`/`autopilot`), não delegar a
> execução ao usuário. Mensagens de auditoria que sugerem "rodar step N" são dicas
> legadas; trate-as como candidatas a incorporação, não como instrução ao usuário.

> A geração LLM (10/11/13) e a auditoria de conteúdo usam o **claude CLI**
> (assinatura PRO) via agentes batch — Gemini foi aposentado. O orquestrador de QA
> **`qa.py` já existe** (menu 53-61): `qa.run("audit")` é o passe único de
> auditoria do site todo (não-LLM) e `qa.run("full")` = auditoria + remediação.
> Modos disponíveis: `covers`, `classification`, `connectivity`, `prices`,
> `integrity`, `consistency`, `lists`, `audit`, `remediate`, `remediate_covers`,
> `reconcile_synopsis`, `flag_synopsis_regen`, `ingest_audit`, `remediate_mechanical`,
> `full`, `content`, `titles`. Todas as auditorias emitem
> `data/logs/NNNN_audit_<mode>.json` (escritor `core/audit_report.py`), consumido
> pelo comando **`/audit`**. Fonte de verdade: `scripts/main.py`.

### Atalhos de diagnóstico

```bash
# Estado do pipeline
python -c "
from core.db import get_conn
conn = get_conn()
cur = conn.cursor()
for q, label in [
    ('SELECT COUNT(*) FROM livros', 'Total'),
    ('SELECT COUNT(*) FROM livros WHERE status_review=1', 'Revisados'),
    ('SELECT COUNT(*) FROM livros WHERE status_synopsis=1', 'Com sinopse'),
    ('SELECT COUNT(*) FROM livros WHERE status_publish=1', 'Publicados'),
]:
    cur.execute(q); print(label + ':', cur.fetchone()[0])
conn.close()
"

# Uso da sessão Claude PRO (janela rotativa de 5h)
python -c "from core.claude_usage_tracker import status; import json; print(json.dumps(status(), indent=2))"

# Schema do banco
python -c "
from core.db import get_conn, ensure_schema
conn = get_conn()
ensure_schema(conn)
cur = conn.cursor()
cur.execute(\"SELECT name FROM sqlite_master WHERE type='table'\")
print([r[0] for r in cur.fetchall()])
"
```

---

## Arquitetura

```
scripts/
├── main.py                   # Menu interativo — ponto de entrada
├── .env                      # Chaves de API (nunca commitar)
├── core/
│   ├── db.py                 # Schema SQLite + conexão (WAL, timeout 60s)
│   ├── markdown_executor.py  # Executor de agente de estágio único (MODE 1) via _call_llm
│   ├── claude_runner.py      # Invoca o claude CLI (run_agent / run_prompt)
│   ├── claude_usage_tracker.py # Rastreia a janela de sessão Claude PRO (5h)
│   ├── gemini_limiter.py     # LEGADO — Gemini aposentado (mantido por compat.)
│   ├── markdown_memory.py    # Memória persistente de agentes (tabela pipeline_state)
│   ├── logger.py             # Log com timestamp [HH:MM:SS] + heartbeat daemon
│   ├── length_enforcer.py    # Utilitário de limite de caracteres
│   └── state.py              # state.json I/O
├── steps/                    # Um arquivo por step (ver tabela abaixo)
├── data/
│   ├── books.db              # SQLite principal
│   ├── taxonomy.json         # 100+ categorias temáticas
│   ├── claude_usage.json     # Contadores da sessão Claude PRO (auto-gerado)
│   ├── batch/               # Lotes de input/output dos agentes batch (runtime)
│   ├── seeds/                # NNN_offer_seeds.json aguardando ingestão
│   └── seeds/ingested_seeds/ # Seeds já processados (movidos pelo step 1)
└── agents/  (em ../agents/)  # Prompts markdown dos agentes
    ├── synopsis_batch/prompt.md   # Geração de sinopse em LOTE (motor único)
    ├── classify_batch/prompt.md   # Categorização em LOTE
    └── author_bio/                 # Bio de autor (MODE 1: identity/rules/task)
```

> **Motor LLM (WS2, 2026-05-30):** a geração usa o **claude CLI** (assinatura PRO)
> via **agentes batch** (`*_batch`). O antigo FSM de sinopse (`agents/synopsis/*`,
> `markdown_executor` MODE 2) foi **removido**. `markdown_executor` mantém só o
> MODE 1 (agente de estágio único, ex: `author_bio`).

---

## Pipeline — Steps

| # | Nome | Módulo | LLM | Depende de | Status saída |
|---|------|--------|-----|------------|--------------|
| 1 | Importar Seeds | offer_seed.py | — | seeds/*.json | created |
| 2 | Enriquecer Desc *(fallback-only)* | enrich_descricao.py | — | — | descricao preenchida |
| 3 | Resolver Ofertas | offer_resolver.py | — | lookup_query | offer_url |
| 4 | Scraper Marketplace | marketplace_scraper.py | — | offer_url | imagem_url, descricao, **preco** |
| 5 | Gerar Slugs | slugify.py | — | — | status_slug=1 |
| 6 | Slugify Autores | slugify_autores.py | — | — | autores.slug |
| 7 | Deduplicar | dedup.py | — | — | status_dedup=1 |
| 8 | Review | review.py | — | — | status_review=1 |
| **9** | **Categorizar** | categorize.py | **Claude (batch)** | review=1 | livros_categorias_tematicas |
| **10** | **Gerar Sinopses** | synopsis.py | **Claude (batch)** | review=1 | status_synopsis=1 |
| 11 | Gerar Capas | covers.py | — | — | status_cover=1/2 |
| 12 | Quality Gate | quality_gate.py | — | steps 5,8,10,11 | is_publishable=0/1 |
| 13 | Publicar Supabase | publish.py | — | is_publishable=1 | status_publish=1 |
| 14 | Publicar Autores | publish_autores.py | — | step 13 | autores.status_publish=1 |
| 15 | Publicar Ofertas | publish_ofertas.py | — | step 13 | status_publish_oferta=1 |
| 16 | Listas SEO | list_composer.py | — | step 13 | tabelas listas/listas_livros |
| 17 | Monitor Preços | offer_price_monitor.py | — | step 13 | offer_price_log |
| 18 | Auditoria Conectiv | auditor.py | — | — | connectivity_log + NNNN_audit_connectivity.json |
| **19** | **Auditoria Conteúdo** | auditor.py | **Claude** | step 13 | audit_log + NNNN_audit_content.json |
| 40–57 | Auditoria/QA (suite) | auditor.py (modes) + qa.py | parcial | step 13 | data/logs/NNNN_audit_<mode>.json |
| 91–94 | Exports | export_state_transcript.py | — | — | JSON/markdown |

### Fluxo recomendado para novos seeds

```
1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13 → 14 → 15 → 16
```

---

## Seções paralelas — visão geral

O site tem **três** pipelines independentes. O de livros é o principal; os
outros dois são isolados **por construção** (tabela, steps, seeds e agentes
próprios) para não arriscar o que já funciona.

| | Livros | Jogos | Livros Infantis |
|---|---|---|---|
| Entrada | `main.py` (G/A/O…) | `jogos.py` ou **J** | **I** no `main.py` |
| Tabela local | `livros` | `jogos` | `livros_infantis` |
| Seeds | `NNN_offer_seeds.json` | `NNN_jogos_seeds.json` | `NNN_infantis_seeds.json` |
| Tabela Supabase | `livros` (+ofertas…) | `jogos` | `livros_infantis` |
| Click | `/api/click/[id]` | `/api/click-jogo/[id]` | `/api/click-infantil/[id]` |
| Página | `/livros/[slug]` | `/jogos/[slug]` | `/infantis/[slug]` |

**Fallback do G:** ao esgotar o que o pipeline de livros podia fazer, o G
chama `_run_secoes_paralelas()` → autopilot **J** e depois **I**. O trabalho
não-LLM dessas seções (ofertas, enriquecimento, capas) não consome quota
nenhuma. Cada seção roda em `try` isolado: falha numa não compromete o G.

> ⚠ **A letra `I` mudou de dono.** Era "Ingestão Orientada", que passou para o
> **submenu Ingestão, opção 5**. No topo, `I` agora é a seção Livros Infantis.

---

## Pipeline de Livros Infantis (paralelo e independente)

Seção de livros para leitores de **até 12 anos**, segmentada por idade.

```bash
cd scripts
python main.py     # → opção I (autopilot multijanela)
```

**Por que tabela própria:** a seção precisa de `faixa_etaria`, `idade_min/max`
e `ilustrador` (em livro infantil o ilustrador é coautor de fato) — campos que
`livros` não tem e que não fazem sentido no catálogo geral. Acrescentá-los lá
mexeria no pipeline funcional, o mesmo motivo que isolou os jogos.

**Diferença importante vs. Jogos:** livro infantil **é livro** — Google Books e
OpenLibrary catalogam esses títulos. Por isso este pipeline tem um step de
**enriquecimento por ISBN/título (`enrich`, sem LLM)** antes do scraper, e a
maior parte do conteúdo entra de graça. O LLM é usado **só na sinopse**, o que
torna esta seção muito mais barata em quota que a de jogos (onde a descrição
só vinha pelo agente finder via WebSearch).

**Subcategorias por idade** (`FAIXAS` em `steps/infantis_pipeline.py`, espelhadas
no hub `/infantis`): `0-2-anos`, `3-5-anos`, `6-8-anos`, `9-12-anos`.

- **Steps:** seeds → ofertas → **enrich (Google Books/OpenLibrary)** → scraper
  → slugs → sinopse (agente `synopsis_infantis_batch`) → QG → publish.
- **Seeder (ChatGPT):** `agents/seeder_agent - infantis theme driven.txt` —
  theme-driven, faixa etária obrigatória com grafia fixa, e regras explícitas
  de **JSON puro** (sem markdown/cerca, sem JSONL, sem aspas curvas) para o
  arquivo ser ingerível. O import ainda assim tolera BOM e cerca de markdown.
- **Migração Supabase (1x):** `scripts/sql/2026-07-21_secao_infantis.sql`
  (`livros_infantis` + `livro_infantil_clicks`). Sem ela o site fica de pé
  (hub mostra "em breve") e só o publish falha, com mensagem orientando.

---

## Pipeline de Jogos (paralelo e independente)

A **Seção Jogos** do site (RPG de mesa, jogos de tabuleiro, jogos de cartas)
tem um pipeline **próprio e isolado** — decisão de arquitetura de 2026-07-14:
jogos não são análogos a livros (enrich/covers/dedup/review/listas/auditorias
de livros produziriam dados errados ou despublicação indevida), então o
isolamento é **por construção**, não por guards espalhados no código de livros.

```bash
cd scripts
python jogos.py        # menu próprio (1-7, A=passe único, J=multijanela, V=verify, S=status)
python jogos.py J      # autopilot multijanela direto
python main.py         # → letra J também roda o autopilot de jogos
```

**Opção J (modelo G):** passe não-LLM + fase LLM; se a quota da sessão PRO
esgotar com backlog de sinopse, entra em **loop multijanela** — espera
produtiva (drena não-LLM + publica) → aguarda o reset → nova janela LLM →
publica — até drenar, uma janela não progredir (guard anti-giro) ou Ctrl+C.
Acessível também pela letra **J** no menu do `main.py` (import lazy — nada do
domínio jogos carrega fora dessa opção).

**Opção V — contrato de publicação:** `verify_supabase()` compara as colunas
do payload (`SUPABASE_PAYLOAD_COLUMNS`) e da rota de click (`CLICK_COLUMNS`)
com o schema remoto real (OpenAPI do PostgREST). Detecta tabela ausente
(migração pendente) e drift de coluna (que causaria 400 PGRST204) ANTES do
publish. O J roda essa checagem automaticamente no início.

Mapeamento local → Supabase (fonte única em `SUPABASE_PAYLOAD_COLUMNS`):
`ano_lancamento→ano_publicacao`, `offer_url→url_afiliada`,
`sinopse→descricao` (convenção igual a livros), `preco_atual` com fallback
`preco`. Colunas só locais (nunca enviadas): `lookup_query, preco, sinopse,
status_*, publish_blockers, seed_id, idioma`. Tipos coeridos no payload
(`int/float/None` — string vazia em campo numérico = 400, bug da sessão 18).

| Aspecto | Livros | Jogos |
|---|---|---|
| Tabela local | `livros` (books.db) | `jogos` (mesmo books.db) |
| Seeds | `NNN_offer_seeds.json` | `NNN_jogos_seeds.json` |
| Seeder (ChatGPT) | `agents/seeder_agent - theme driven.txt` | `agents/seeder_agent - jogos theme driven.txt` |
| Sinopse (LLM) | `agents/synopsis_batch` (`*_synopsis_input.json`) | `agents/synopsis_jogos_batch` (`*_synopsis_jogos_input.json`) |
| Conteúdo qdo. scraper bloqueado | `agents/offer_finder` (MODE 1) | `agents/jogos_finder_batch` (`*_jogos_finder_*.json`) |
| Tabela Supabase | `livros` (+ ofertas/autores/categorias/listas) | `jogos` (oferta embutida; sem autores/listas de livros) |
| Click tracking | `/api/click/[id]` → `oferta_clicks` | `/api/click-jogo/[id]` → `jogo_clicks` |
| Página | `/livros/[slug]` | `/jogos/[slug]` |

- **Módulo:** `steps/jogos_pipeline.py` (seed → resolver → scraper → slug →
  sinopse LLM → QG → publish). Entrypoint: `scripts/jogos.py` — **não** passa
  pelo `main.py` nem pelo autopilot G.
- **Reuso apenas de funções puras** dos steps de livros (nada é modificado lá):
  `offer_resolver.resolve_offer` e `marketplace_scraper.scrape_marketplace`,
  além de `core.claude_runner` e `core.batch_numbering`.
- **Scrape em 2 saltos (busca → produto) com validação de título:** o
  `offer_url` do resolver é uma URL de BUSCA, e os SELECTORS do scraper são
  de página de PRODUTO — o scraper acha na busca o card cujo TÍTULO casa com
  o jogo (`_titulo_compativel`; pula patrocinados; sem card compatível =
  falha, NUNCA pegar o 1º resultado às cegas — medido: "Knave" retornava
  Blades in the Dark) e raspa a página do produto; o `offer_url` é promovido
  ao deep-link afiliado. Re-enfileiramento dos sem-descrição 1x por passe do
  J/A (`_requeue_scrape_sem_descricao`) — nunca na espera produtiva
  multijanela (não martelar o marketplace).
- **Finder (LLM) — fonte quando o scraper não alcança:** Amazon responde
  503/captcha e o ML redireciona para account-verification (bot walls
  medidos). O agente `jogos_finder_batch` (claude CLI + WebSearch/WebFetch,
  mesmo papel do offer_finder nos livros) localiza a página REAL do produto,
  valida o título e extrai descrição/imagem/preço; `finder_import` injeta a
  tag de afiliado e promove o `offer_url`. NOT_FOUND marca `finder_tried=1`
  (não re-exporta). No J, a fase LLM é finder → sinopses, e o guard de
  progresso da janela considera também descrições adquiridas.
- **Sem no pipeline de jogos (de propósito):** enrich via Google Books, capas
  via APIs de livro (fonte única = scraper do marketplace), dedup contra
  livros, review `is_book`, categorização LLM (categoria vem do seed),
  listas "Melhores livros de…", páginas de autor para designers,
  auditorias de veracidade de título (Google Books não cataloga jogos).
- **Migração Supabase (1x):** `scripts/sql/2026-07-14_secao_jogos.sql` no SQL
  Editor cria `jogos` + `jogo_clicks` (RLS read público em `jogos`). Sem ela,
  o publish (opção 7) falha com mensagem orientando a migração; o site fica
  de pé normalmente (hub `/jogos` mostra "em breve").

---

## Banco de Dados (SQLite)

**Arquivo:** `data/books.db`
**Conexão:** WAL mode, timeout 60s, busy_timeout 60000ms

### Tabela `livros` — colunas principais

```
id                  TEXT PK   hex(randomblob(12)) — 24 chars
titulo              TEXT
slug                TEXT      gerado no step 4
autor               TEXT
isbn                TEXT
descricao           TEXT      bruto (APIs/scraping)
sinopse             TEXT      gerado pelo LLM (step 8) — NÃO sobrescreve descricao
imagem_url          TEXT
idioma              TEXT      PT | EN | ES | IT | UNKNOWN
offer_url           TEXT
marketplace         TEXT      amazon | mercadolivre
preco               REAL      semente (só offer_seed/db_recover escrevem)
preco_atual         REAL      monitorado — scraper + offer_price_monitor
offer_status        TEXT      active | unavailable
editorial_score     INTEGER   >= 0 = publicável
is_book             INTEGER   0 | 1
is_publishable      INTEGER   0 | 1
supabase_id         TEXT

-- Flags de pipeline (0=pendente, 1=feito)
status_slug         INTEGER
status_dedup        INTEGER
status_review       INTEGER
status_synopsis     INTEGER
status_cover        INTEGER   2=skipped (sem imagem, OK)
status_publish      INTEGER
status_publish_oferta INTEGER
status_enrich       INTEGER   1=scraping, 2=fallback API
status_categorize   INTEGER

reactivation_pending INTEGER  step 19: 1=revisar manualmente
```

> **⚠️ Preço: publicar `COALESCE(preco_atual, preco)`, nunca `preco` sozinho.**
> `preco` é a coluna SEMENTE — só `offer_seed` e `db_recover` escrevem nela.
> Quem coleta preço de verdade (`marketplace_scraper.save_result` e
> `offer_price_monitor`) grava em **`preco_atual`**. Até 2026-07-26
> `publish_ofertas.fetch_pendentes` lia `preco`, e por isso publicava quase
> sempre NULL: medido no books.db, 2 livros tinham `preco` contra 58 com
> `preco_atual`, e dos 4.403 elegíveis à publicação **0** tinham `preco` e 57
> tinham `preco_atual`. O pipeline de jogos já usava a regra certa
> (`SUPABASE_PAYLOAD_COLUMNS`), só o de livros estava fora.

### Outras tabelas

| Tabela | Uso |
|--------|-----|
| `autores` | Autores com slug e supabase_id |
| `livros_autores` | N:M livros ↔ autores |
| `categorias` | Categorias editoriais |
| `livros_categorias` | N:M livros ↔ categorias editoriais |
| `livros_categorias_tematicas` | N:M via taxonomy.json (step 18, max 5/livro) |
| `listas` | Listas SEO geradas (step 14) |
| `listas_livros` | Membros das listas com posição |
| `seed_imports` | Rastreia seeds ingeridos (evita dupla importação) |
| `offer_price_log` | Histórico de variações de preço (step 19) |
| `audit_log` | Resultados de auditoria de conteúdo (step 16) |
| `connectivity_log` | Resultados de auditoria de conectividade (step 15) |
| `pipeline_state` | Memória persistente de agentes LLM |

### IDs e timestamps

```python
# ID local
id = hex(randomblob(12))   # ex: "a3f2c1d4e5b60789abcd1234"

# UUID Supabase (determinístico)
import uuid
NAMESPACE = uuid.UUID("11111111-2222-3333-4444-555555555555")
supabase_id = str(uuid.uuid5(NAMESPACE, local_id))

# Timestamp
from datetime import datetime
ts = datetime.utcnow().isoformat()   # "2026-03-17T18:15:30.123456"
```

---

## LLM — Motor e Controle de Sessão

### Motor único: Claude PRO via CLI

A geração LLM usa **exclusivamente a quota da assinatura Claude PRO** através do
`claude` CLI (`core/claude_runner.py`). **Sem API paga por token. Gemini/Ollama
aposentados** (o roteador legado em `markdown_executor._call_llm` permanece, mas
o provider padrão é `claude`).

| Caminho | Como funciona | Usado por |
|---------|---------------|-----------|
| **Batch** (canônico) | exporta lote JSON → `run_agent` sobre `agents/*_batch/prompt.md` → importa | sinopse, categorização, bios (opção O, menu 10/11/13, ingestão guiada) |
| **MODE 1** (estágio único) | `execute_agent` sobre `agents/<n>/{identity,rules,task}.md` | author_bio, offer_finder |

### Modelo por agente

> **⚠️ O padrão do CLI é Sonnet, não Opus.** Medido em 2026-07-25 (CLI 2.1.138)
> com teste discriminante: sem flag e `--model sonnet` retornam
> `claude-sonnet-4-6`; `--model opus` retorna `Claude Opus 4.7`. Não há `model`
> configurado em `.claude.json` nem em `settings.json`.
>
> **Não confunda "padrão" com "modelo forte".** Quem precisa de Opus tem de
> pedir explicitamente. (O PR #222 nasceu da premissa oposta — de que tudo
> rodava em Opus — e por isso não trouxe o ganho de throughput que prometia;
> ele apenas fixou o que já era o padrão.)

A política vive em `core/claude_runner.AGENT_MODELS` e é resolvida dentro de
`run_agent()` a partir do nome do diretório do agente (`agents/<nome>/prompt.md`)
— **todos** os call sites passam por lá, então não há flag espalhada pelos steps.

| Agente | Modelo | Por quê |
|---|---|---|
| `synopsis_batch`, `synopsis_jogos_batch`, `synopsis_infantis_batch` | `sonnet` | Transformação fechada: `descricao` ⇒ 90–160 palavras, proibido conhecimento externo. Pinado por **estabilidade** (não seguir mudança de padrão do CLI), não por economia |
| `classify_batch` | `sonnet` | Escolher 3–5 slugs de taxonomia fixa; todo o critério já está no prompt |
| `author_bio` | **`opus`** | Datas, movimentos e obras de **pessoas reais** — alucinação vira conteúdo errado publicado. Último da fila do orquestrador, então o volume (e o custo de quota) é baixo |
| `jogos_finder_batch`, `title_auditor`, `audit_batch`, `consistency_review`, `log_analysis_batch` | padrão do CLI (hoje Sonnet) | Decisão ainda não tomada — não confundir com "escolhido para ser forte" |

Override por agente via env: `CLAUDE_MODEL_<AGENTE_EM_MAIÚSCULAS>` (use
`default` para forçar o padrão do CLI). `CLAUDE_MODEL_FAST` e
`CLAUDE_MODEL_STRONG` trocam os dois grupos de uma vez.

Como reconferir o padrão do CLI depois de um upgrade:

```bash
cd scripts
python -c "import os; from core.claude_runner import _invoke; [print(m, '->', _invoke('Responda so com o nome do modelo que voce e.',90,{**os.environ},m)[1].strip()) for m in [None,'sonnet','opus']]"
```

> A sonda de quota (`_wait_and_probe`) usa o **mesmo** modelo da chamada real —
> as quotas são por modelo, e sondar com o padrão manteria a espera mesmo com o
> modelo rápido já liberado.

### Pré-voo de sessão (opção G)

`claude_available()` só confirma que o **executável** existe. Com o token
expirado ele devolve `True`, a fase LLM roda, e cada export marca livros como
`status_*=3` (em voo) **antes** de falhar com 401 — deixando lotes órfãos e
livros presos nesse estado. Aconteceu em 2026-07-25: 5 lotes órfãos de
categorização e 40 livros parados em `status_categorize=3`.

`claude_runner.session_status()` faz uma chamada trivial e classifica:

| Estado | Significado | Efeito no G |
|---|---|---|
| `ok` | sessão responde | roda a fase LLM |
| `limite` | quota esgotada | **roda mesmo assim** — o orquestrador já trata espera/fallback |
| `auth` | sessão inválida/expirada | **pula** a fase LLM e orienta `claude auth login` |
| `erro` | outra falha | **pula** a fase LLM, segue no não-LLM |
| `sem_cli` | executável ausente | pula a fase LLM |

Custo: segundos, contra um ciclo inteiro desperdiçado. Os padrões de erro de
autenticação vivem em `claude_runner._AUTH_PATTERNS` (fonte única — o
`llm_orchestrator` importa `is_auth_error` de lá, para os dois não divergirem).

### Controle de sessão (não tokens)

O limite relevante é a **janela rotativa de 5h** da sessão PRO, não RPM/RPD:

1. `core/claude_usage_tracker.py` rastreia `session_calls`, `session_started_at` e
   `session_window()` (in_cooldown, seconds_until_reset, reset_at).
2. `SESSION_RESET_MINUTES=300` (5h). Ao detectar limite, `claude_runner` aguarda o
   reset e faz **1 retry**; se persistir, o orquestrador cai no fallback não-LLM.
3. **Persistência:** `data/claude_usage.json`.
4. O painel de Status (opção S) e o relatório da opção G exibem a janela atual.

### O gargalo real é o enriquecimento, não a quota

**Medido em 2026-07-26.** Da fila de sinopse (11.028 livros):

| | Livros | |
|---|---|---|
| **Com** descrição | 987 | 9% — únicos exportáveis |
| **Sem** descrição | 10.041 | **91%** — rejeição garantida |

`synopsis_export.fetch_pending` não filtrava por descrição, e o prompt marca
`REJECTED` quando ela é vazia — então cada um desses era **uma chamada do
gargalo para nada**. Hoje o filtro existe (e em `_count_pending_synopsis`, para
o G não esperar quota por trabalho impossível). `_count_sem_descricao` mantém os
bloqueados visíveis, e o drain loga o motivo ao esvaziar.

> **Consequência esperada:** o backlog exportável cai de 11.028 para ~965 e o
> autopilot para bem mais cedo. Isso é o comportamento correto — expõe o gargalo
> em vez de mascará-lo queimando quota.

**Re-enriquecer esses 10 mil não resolve** (avaliado e descartado — TASK-ENRICH-002):
100% já estão com `status_descricao=2`, e **todos** falharam *depois* do PR #180
(fallback multi-idioma + match por autor, 2026-07-04T11:13Z) — as 9.643 do dia 04
são todas de 14h-18h UTC. Re-rodar aplica o mesmo código que já os rejeitou. Além
disso, a cota gratuita do Google Books é de **~1.000 consultas/dia** (confirmado
com `429 Quota exceeded ... Queries per day` após ~959 consultas), então 10.041
livros custariam ~10 dias.

> Isso **corrige** a expectativa registrada de que o #180 "destravaria ~8.300
> livros": o re-enrich já rodou em 04/07 e eles seguem sem descrição.

Sair daqui exige **outra fonte** de descrição — scraper de marketplace (0% de
mismatch, o melhor índice do banco), OpenLibrary ou o agente `offer_finder` via
WebSearch.

> **Passo dado em 2026-07-26:** o marketplace deixou de ser a ÚLTIMA tentativa
> do step 4 e passou a ser a PRIMEIRA — ver "Ordem das fontes no step 4" abaixo.
> Os "só 140 livros" eram consequência da ordem, não do bot wall.

### Ordem das fontes no step 4 — marketplace primeiro

Até 2026-07-26 `marketplace_scraper.run()` tentava **Open Library → Google Books
→ marketplace**, e o marketplace só rodava `if not result`, ou seja, quando as
duas APIs falhavam em devolver até capa. Para livro real isso quase nunca
acontece, então o marketplace era praticamente inalcançável: **140 de 17.861
livros (0,8%)** com `status_enrich=1`. Como as duas APIs retornam `preco: None`
**por construção** (está escrito no código), o efeito foi preço nunca coletado
no enriquecimento — e a `/ofertas` com ~100% de "Consulte o site".

Hoje a ordem é **marketplace → Open Library → Google Books**, pelos dois motivos
medidos: é a única fonte com preço, e a de melhor qualidade de descrição (0% de
`synopsis-title-mismatch` em 111 livros contra 24,8% do Google Books em 5.721).

**O circuit breaker é o que torna essa ordem viável.** Sob bot wall, cada livro
custaria até ~25 s só de backoff de 503 (`RETRY_MAX=3`, `RETRY_DELAY_503=[5,20]`)
— inviável em 17 mil livros. Após `MP_CIRCUIT_THRESHOLD` falhas **consecutivas**
(padrão 3, env) o marketplace é pulado pelo resto do lote e o step degrada
exatamente para o comportamento anterior. Qualquer sucesso fecha o circuit.

Dois detalhes que os testes fixam (`tests/test_marketplace_scraper_ordem.py`):

- **O preço raspado sobrevive ao fallback.** Se o produto devolve preço mas não
  devolve capa/descrição, a descrição vem da API e o preço do scrape é
  preservado. Antes esse preço era descartado junto com o resultado.
- **`status_enrich` reflete a origem da DESCRIÇÃO**, não do preço — é isso que
  a ordenação da fila de sinopse usa. Preço do marketplace + descrição da OL
  grava `status_enrich=2`, corretamente.

> **Bug corrigido junto:** os dois circuits (OL e marketplace) são **por lote**,
> mas nada os resetava entre chamadas de `run()`. Como o guard da Open Library
> retorna *antes* de qualquer request, o contador nunca voltava a zero — uma vez
> aberto, o circuit latchava para **todo o resto do processo**, e o autopilot
> chama `run()` muitas vezes no mesmo processo. Agora `run()` zera os dois no
> início.

### Confiança do enriquecimento — ordem da fila de sinopse

**Fato medido (2026-07-25).** ~25% das sinopses eram rejeitadas com
`synopsis-title-mismatch`: a `descricao` pertencia a outro livro. A origem é o
enriquecimento por API — não o modelo:

| Origem da descrição | Processados | Mismatch |
|---|---|---|
| `status_enrich=1` (scraping) | 111 | **0 (0%)** |
| `status_enrich=2` (Google Books) | 5.721 | 1.418 (**24,8%**) |

A taxa de acerto depende fortemente de quanto o título retornado casa com o
buscado:

| Similaridade do título | Taxa de sucesso |
|---|---|
| ~1.00 (exato) | **89%** |
| 0.70–0.85 | 78% |
| 0.50–0.70 | **56%** |

`livros.enrich_similaridade` (0..1) registra essa confiança, e
`synopsis_export.fetch_pending` ordena por ela — **casamento exato primeiro**.
Como sinopse é o gargalo, a mesma quota rende mais publicações por janela.

> **Não é filtro, é ordem.** Subir o `TITLE_SIMILARITY_THRESHOLD` (hoje `0.5`)
> parece a correção óbvia e foi **descartado por medição**: cortar a faixa
> 0.50–0.70 evitaria ~681 descrições ruins mas destruiria ~861 boas — a faixa é
> suja, porém ainda majoritariamente acerto. Nada é descartado; o de baixa
> confiança apenas vai para o fim da fila.

**Backfill (obrigatório para o backlog existente):** livros enriquecidos antes
da coluna ficam com `NULL` e empatam no fim — sem backfill, a ordenação não muda
nada. Sem LLM, só Google Books:

```bash
cd scripts
python tools/backfill_enrich_similaridade.py            # fila de sinopse (~65 min)
python tools/backfill_enrich_similaridade.py --limit 200
```

Retomável (pula quem já tem valor) e interrompível com Ctrl+C. Ele
**reconstrói** a decisão consultando de novo — o título do registro original não
foi persistido —, o que basta como proxy de confiança para ordenar.

> **Ele para sozinho ao esgotar a cota diária do Google Books (desde
> 2026-07-31).** Antes, `_similaridade_remota` colapsava todo status != 200 em
> `None`, indistinguível de "consulta feita, sem match" — então o 429 virava
> "falha" e o script seguia consultando à toa. Medido no
> `pipeline_2026-07-26_08-08-10` (959 livros): a taxa de falha ficou em ~5% até
> o item 800 e explodiu depois (68 falhas em 800, 102 em 850, 138 em 900, 171 em
> 950) — **~103 das 179 falhas vieram dos últimos 159 itens**, todas por cota.
> Hoje o 429 devolve a sentinela `QUOTA_ESGOTADA`, o loop encerra com o total
> restante no log e a fila fica preservada para o dia seguinte.

### ⚠ A janela da sessão PRO tem 5–6 chamadas — não centenas

**Medido em 2026-08-09** nos 3 logs substanciais de 2026-08-04/05/06 (contagem
dos pares `→ <agente>: invocando claude CLI` / `✓ <agente> concluído` até
`limite de uso persistente`):

| Janela | Chamadas | Tempo de LLM | bio / classify / synopsis |
|---|---|---|---|
| 08-04 | 5 | 20m19s | 1 / 1 / 3 |
| 08-05 | 6 | 25m51s | 1 / 1 / 4 |
| 08-06 | 6 | 26m32s | 1 / 1 / 4 |

O limite bate ~30 min depois do início, **no Ciclo 1 dos três logs** — ou seja,
1 ciclo ≈ 1 janela, e "cota por ciclo" é na prática "cota por janela".

Isto **corrige** a justificativa que estava escrita abaixo e no docstring de
`_rotacao_author_bio`: *"1 chamada por ciclo contra as centenas gastas em
sinopse"*. Não há centenas — são 3–4. As duas rotações fixas consumiam **2 das
5–6 chamadas, 33–40% de toda janela**, antes de a sinopse receber qualquer
coisa. A conta que autorizava as duas rotações nunca foi verificada.

### Slot secundário — UMA chamada por ciclo, disputada

Desde 2026-08-09, as duas rotações fixas deram lugar a **um slot só**
(`llm_orchestrator._slot_secundario`), decidido a cada ciclo:

```
1º  auditoria LLM VENCIDA  → content (>48h), senão title-verify (>168h)
2º  senão, rodízio         → author_bio ↔ classify, alternando
```

O **gate de staleness é o mecanismo**, não a cota: os limiares vivem em
`pipeline_status._AUDIT_STEPS` (fonte única, lida via `audit_stale`). Com ~4,8
janelas/dia a auditoria reivindica ~13,5% dos slots.

> **A auditoria virou batch em 2026-08-11 — e o motivo vale registrar.** Até
> essa data `run_content_audit` e `run_title_verify` chamavam o LLM **uma vez
> por livro**: eram os dois últimos consumidores fora do motor de lote, herdados
> do caminho MODE 1 do `markdown_executor`.
>
> **Medido rodando o G de verdade:** com `AUDIT_LLM_POR_CICLO=25`, o
> `claude_usage_tracker` foi de 5 para **30 chamadas** no dia — 25 chamadas em
> 13m45s, num único slot. Como a janela comporta 5–6 chamadas de lote, aquilo
> gastava **4–5 janelas** numa auditoria só.
>
> Hoje `AUDIT_BATCH_SIZE` (padrão **10** livros por chamada) faz `limit=N`
> custar `ceil(N / AUDIT_BATCH_SIZE)` chamadas. Com `AUDIT_LLM_POR_CICLO=10`, a
> auditoria custa **1 chamada** — o mesmo que qualquer outro ocupante do slot.
> Invariante fixado em `tests/test_auditor_batch.py`.
>
> Lição de método: a medição da janela (5–6 chamadas) estava certa e foi
> aplicada com a **unidade errada** ao caso novo — supus que auditoria custasse
> 1 chamada como as outras rotações. Número medido ao lado de número suposto,
> os dois escritos com a mesma confiança, e só a execução real separou os dois.

| | Antes | Depois |
|---|---|---|
| Chamadas secundárias/janela | 2 | **1** |
| `synopsis`/janela | 3–4 | **4–5** |
| Auditoria LLM | `nunca executado` | roda sob gate (ver aviso acima) |

Ganho esperado de ~15 livros publicados por janela **e** as auditorias LLM
passam a existir. Contrapartida: bio e classify drenam ~2× mais devagar — as
duas filas já eram inalcançáveis no ritmo anterior (13.571 classify a ~120/dia
= 113 dias), e a sinopse é o hard-block do Quality Gate.

> **O cursor do rodízio é persistido** em `pipeline_state` (via
> `core/kv_state.py`). Em memória ele reiniciaria a cada `python main.py` e,
> como o limite bate no Ciclo 1, `author_bio` ganharia o slot **sempre** e
> `classify` nunca rodaria — a mesma armadilha do seed de `repair_synced_ids` e
> dos guards zerados a cada re-invocação (`core/drain_loop.py`).

`SLOT_SECUNDARIO=0` restaura as duas rotações fixas; `AUDIT_LLM_POR_CICLO=0`
desliga só as auditorias. Testes em `tests/test_slot_secundario.py`.

### Rotações — cotas fixas por ciclo

> ⚠ Histórico: a partir de 2026-08-09 as duas rotações abaixo **não rodam mais
> as duas por ciclo** — elas alternam no slot único descrito acima. As cotas
> (`BIO_POR_CICLO`, `CLASSIFY_POR_CICLO`) continuam valendo como tamanho do
> lote de quem ocupa o slot.

Duas filas ficavam atrás da sinopse na Fase A e, como ela não zera numa janela
de 5h, **nunca eram alcançadas**. A correção é a mesma nas duas: uma cota fixa
executada **no início do ciclo, antes da sinopse**.

| Rotação | Env | Padrão | Unidade | Fila em 2026-07-25 |
|---|---|---|---|---|
| Bios | `BIO_POR_CICLO` | **25** | autores | 2.091 (fila útil, 2026-08-23) |
| Categorização | `CLASSIFY_POR_CICLO` | 25 | livros | 13.872 |

`0` desliga qualquer uma delas. As cotas recortam abaixo do `BATCH_SIZE_*` via
o parâmetro `limite` dos respectivos `_export_*`.

> **A ordem é o mecanismo.** Rodar as rotações *depois* da sinopse seria
> idêntico a não tê-las: a janela acaba na sinopse e o fluxo nunca chega lá.

> **⚠ As duas se comportam DIFERENTE frente ao guard anti-giro do G**, que
> compara `_content_backlog()` (= sinopse + categorização) entre janelas:
> - **Bios não entram** nessa conta — uma janela que só gerou bios continua
>   sendo corretamente detectada como "sem progresso" e encerra o loop.
> - **Categorização entra.** Uma janela em que só a rotação de classify
>   progrediu conta como progresso e o loop continua. Está correto (o backlog
>   caiu de verdade), mas com a sinopse travada o G segue rodando enquanto
>   houver categorização — até ~555 janelas no backlog atual. Para encerrar
>   antes: Ctrl+C ou `CLASSIFY_POR_CICLO=0`.

Os `_drain_*` ilimitados seguem no fim da Fase A: quando as filas realmente
zerarem, tudo drena de uma vez como antes.

#### ⚠ 40% de cada lote de classify eram 32 livros em laço — corrigido em 2026-08-29

`categorize_import` gravava `status_categorize = 0` ao rejeitar — a **mesma**
fila de `categorize_export.fetch_pending`, e na **mesma posição**, porque o
`ORDER BY priority_score DESC, created_at ASC` é determinístico e a rejeição não
mexe em nenhuma das duas colunas. O livro voltava no lote seguinte e era
rejeitado de novo, sem teto.

Medido nos 3 logs de 2026-08-27..29 (contagem de `Rejeitado pelo agente` contra
`→ classify: invocando claude CLI`):

| Log | chamadas | OK | rejeitados | % do lote |
|---|---|---|---|---|
| `2026-08-27_19-22-47` | 46 | 630 | 420 | 40,0% |
| `2026-08-29_05-45-10` | 10 | 145 | 105 | 42,0% |
| `2026-08-29_07-54-02` | 3 | 28 | 22 | 44,0% |
| **total** | **59** | **803** | **547** | **40,5%** |

As 547 rejeições eram de **32 livros distintos**, nove deles **54 vezes cada**
(`How to Brew`, `Homebrewing for Dummies`, `The Brew Manual`, `Extreme Brewing`,
`Bread Illustrated`, `Artisan Breads Every Day`, `The Essential Woodworker`,
`The Woodworker's Bible`, `Furniture Projects`). Lote de classify tem 25 livros;
~10 dos 25 eram sempre os mesmos.

**O custo não é cosmético:** com a sinopse em 0 exportáveis, o classify é hoje o
único ocupante da janela LLM — 5–6 chamadas por 5h. 40% do gargalo do projeto
girava em falso.

**E era catraca, não patamar.** Todo livro novo rejeitado passava a ocupar a
fila para sempre, somando aos que já estavam lá. No log de 27/08 a rejeição por
lote sai de 9–11 (lotes 1–6) para 10–15 (lotes 37–42), e o conjunto de títulos
presos cresce de 9 para **32** ao longo dos três logs — os nove primeiros com 54
aparições, `Basic Fantasy RPG` com 23, `Peru` com 9, e 22 títulos que entraram
perto do fim com 1 cada. Sem teto, o classify convergiria para 100% de
desperdício.

**A causa de fundo é a taxonomia, não o agente.** `data/taxonomy.json` tem 171
categorias em 23 grupos, **todos** de literatura e humanidades; nenhuma cobre
cervejaria (214 rejeições), marcenaria (164) ou culinária (144) — 95% do total.
O agente estava certo em rejeitar. Ampliar a taxonomia é TASK-TAX-001, e está
**bloqueada de propósito**: `taxonomy.json → publish_categorias →
app/sitemap.ts` faz de cada slug novo uma `/categorias/<slug>` indexável, e
`/categorias/*` é exatamente a superfície que reprovou a validação do bucket
"Excluída pela tag noindex" no GSC (603 `Pendente` / 1 `Falha`), sob um site já
rebaixado pelo spam update de agosto.

**O destino é `status_categorize = 2`, não um estado novo** — a máquina de retry
já existia e nunca tinha sido ligada. `MAX_CATEGORIZE_ATTEMPTS` e o guard de
`categorize_attempts` em `categorize.reset_failed()` liam um estado que **nada
no código escrevia**. Conferido no `books.db` em 2026-08-29, não só por grep:

```
status_categorize:  0 → 10.172 | 1 → 5.123 | 4 → 2.566 | 2 → NENHUM
categorize_attempts > 0: 0 livros
```

Mesma classe do `UNAVAIL_THRESHOLD = 2` que o #303 tirou do papel — e a segunda
vez em duas semanas que um guard escrito no módulo nunca chegou a rodar.

Três detalhes que `tests/test_categorize_rejeicao.py` fixa:

- **Rejeição SEM motivo mantém o livro na fila.** Sem motivo é falha transitória
  do agente, não veredito — mesma leitura de `synopsis_import`. Antes as duas
  eram tratadas igual.
- **Não seta `qa_quarantine`.** O `synopsis_import` seta porque sem sinopse o
  livro trava o Quality Gate; falta de categoria temática não bloqueia
  publicação, e `qa_quarantine` também tiraria o livro da fila de sinopse.
- **Blacklistado continua indo para `4`**, que é o que `reprocess_blacklist`
  seleciona.

Efeito colateral aceito: `publicados_sem_categoria`, na auditoria de
classificação, passa a contar esses livros de forma permanente. É relatório, não
ação — `run_classification_audit` não despublica nada, e `categorize_inconsistente`
exige `status_categorize = 1`, então eles não caem lá.

> ✅ **CONFIRMADO no primeiro passe do G pós-fix** (log
> `pipeline_2026-08-29_10-28-52`, commit `410525a` — o próprio merge do #307):
>
> | | antes (3 logs, 27-29/08) | depois (1 passe) |
> |---|---|---|
> | chamadas de classify | 59 | 7 |
> | OK | 803 | 140 |
> | rejeitados | **547** | **10** |
> | % do lote | **40,5%** | **6,7%** |
>
> **As 10 rejeições aconteceram todas no primeiro lote, às 10:38:28, e nenhuma
> se repetiu nos 6 lotes seguintes** — são exatamente os 9 do laço mais o
> `Basic Fantasy RPG`. Do 2º lote em diante o aproveitamento foi de **100%**.
>
> Conferido no `books.db` logo depois: `status_categorize = 2` em **10 livros**,
> com `categorize_attempts` somando **10** — ou seja, **uma tentativa cada**,
> nenhum reprocessado. `categorize_motivo` preenchido e legível nos 10.
> `status_categorize = 1` subiu de 5.123 para 5.263 (+140, batendo com os OK).

### Rotação de bios — detalhe

**Problema (medido em 2026-07-25):** a fase de bios do `llm_orchestrator` só é
alcançada depois de sinopse **e** categorização zerarem. Isso são ~1.300 lotes
(11.036 sinopses + 13.872 categorizações) contra uma janela de 5h que não chega
perto disso. Resultado prático: **8.034 autores sem bio e 0 gerada por janela** —
fome permanente, não lentidão.

**Mecanismo:** `_rotacao_author_bio(cota)` gera até `BIO_POR_CICLO` bios (padrão
**25** — autores, não lotes; a cota recorta abaixo do `BATCH_SIZE_AUTHOR_BIO`).
Desde 2026-08-09 ela roda **quando ganha o slot secundário** (a cada ~2 ciclos),
não em todo ciclo — ver "Slot secundário" acima.

#### ⚠ 73% das bios iam para páginas que respondem 404 — corrigido em 2026-08-23

A fila era `ORDER BY a.nome ASC`, alfabética, sem olhar se a página do autor
existe. Medido no `books.db` em 2026-08-23:

| | Autores |
|---|---|
| Sem bio (fila antiga) | 7.884 |
| **Sem bio E sem nenhum livro publicado** | **5.793 (73%)** |
| Com livro publicado | 2.215 — **2.091 sem bio (94%)** |

`app/(public)/autores/[slug]/page.tsx` faz `notFound()` para autor sem livro, ou
seja, essas 5.793 páginas respondem **404**. Nos 10 primeiros da fila antiga, 7
estavam nessa condição — a quota do gargalo escrevendo bio para página que o
Google nunca vê. O topo da fila era *"André Breton, André Carregal, André
Chouraqui…"*; hoje é *"Umberto Eco (43 livros publicados), Augusto Cury (38),
Stephen King (37), J.R.R. Tolkien (35)…"*.

Duas mudanças, **custo zero em quota**:

- **`_export_author_bio` ordena por livros publicados (desc)**, com `a.nome`
  como desempate estável. Não é filtro rígido de propósito: os autores sem
  página afundam sozinhos, e qualquer um que ganhe livro publicado depois sobe
  sem precisar de backfill.
- **`_count_pending_author_bio` conta só quem tem livro publicado**, senão o
  `_slot_secundario` gastaria o slot (1 chamada de uma janela que só tem 5–6)
  quando só sobram autores sem página. A fila útil caiu de 7.884 para **2.091**.

E a cota subiu de 10 para 25, igualando `BATCH_SIZE_AUTHOR_BIO`: o slot custa
**1 chamada com 10 ou com 25 autores**, então 10 desperdiçava 60% do lote sem
economizar nada. Não havia medição por trás do 10.

> ✅ **MEDIDO na primeira rodada real** (log `pipeline_2026-08-24_20-09-02`,
> ~23 h, commit `118574c`): **50 bios**, em 2 ocupações do slot secundário
> (20:11 e 12:37), **25 autores por lote** — lote cheio, uma chamada cada, no
> Opus. A fila reportada no log foi **2.091 → 2.065**, confirmando que a
> contagem passou a ser só de autores com livro publicado.
>
> A estimativa registrada no PR #297 era de ~50/dia, e bateu. O que **não**
> estava previsto e o log mostrou: em ~23 h houve só **4 slots secundários** (2
> de bio, 2 de classify) — o rodízio 1:1 com o `classify` é o que limita, não a
> cota. `CLASSIFY_POR_CICLO=0` dobra as bios enquanto a fila útil não zerar.
> Invariantes em `tests/test_author_bio_prioridade.py`. Ver TASK-AUTORES-005.

> **A ordem é o mecanismo.** Rodar a rotação *depois* da sinopse seria idêntico
> a não ter rotação: a janela acaba na sinopse e o fluxo nunca chega lá. Por isso
> ela vem primeiro, mesmo sendo a fila de menor prioridade.

⚠ **A frase que estava aqui — "o custo é 1 chamada por ciclo contra as centenas
gastas em sinopse" — é falsa** (medido 2026-08-09, n=3): a janela tem 5–6
chamadas no total, das quais 3–4 vão para sinopse. A chamada da rotação custava
~17–20% da janela, não uma fração desprezível. É por isso que ela deixou de
rodar em todo ciclo e passou a disputar o slot secundário. `BIO_POR_CICLO=0`
desliga; `SLOT_SECUNDARIO=0` restaura o comportamento de duas rotações fixas.

O `_drain_author_bio()` (ilimitado) segue no fim da Fase A: quando sinopse e
categorização realmente zerarem, as bios drenam de uma vez como antes.

> **Por que isso não engana o guard anti-giro do G:** o guard compara
> `_content_backlog()` antes/depois da janela, e essa função soma **apenas**
> sinopse + categorização. Bios não entram na conta — uma janela que só gerou
> bios continua sendo detectada como "sem progresso" e encerra o loop.

### Input resolvido pelo orquestrador

Os prompts batch descobrem o lote sozinhos (Glob → menor número → checar se já
existe output). São 3-5 turnos por lote para achar um arquivo que o pipeline
acabou de escrever. `core.batch_numbering.pending_batch_input()` resolve isso em
Python e `claude_runner.input_hint()` anexa o caminho ao prompt.

**A resolução replica a regra do prompt** — menor número ainda sem
`_output.json` correspondente — em vez de usar o path recém-exportado. A
diferença importa: o export não sabe de **lotes órfãos** de ciclos anteriores,
e injetar o arquivo novo faria o agente pular a fila. Com a regra replicada, os
órfãos continuam sendo drenados primeiro.

Degrada com segurança: o prompt mantém as instruções de Glob, então um agente
que ignore o bloco chega ao **mesmo** arquivo. Ligado via `batch_prefix` em
`_run_agent_step` (`synopsis`, `categorize`, `author_bio`).

### Numeração de lotes — sem teto de 3 dígitos

Os contadores (`NNN_synopsis_input.json`, `NNN_offer_seeds.json`…) usam
`\d+`, **nunca** `\d{3}`. Motivo medido em 2026-07-25: `offer_seeds` já estava
em **999** e `synopsis` em 764 com ~900 lotes ainda por gerar.

Com `\d{3}` as falhas eram todas **silenciosas** — sem erro, sem log:

| Ponto | Efeito ao passar de 999 |
|---|---|
| `batch_numbering.next_batch_number` | Retornava `"1000"` para sempre → cada export sobrescrevia o mesmo arquivo; os livros do lote perdido ficavam presos em `status_synopsis = 3` |
| `synopsis_import` / `categorize_import` (`OUTPUT_PAT`) | Output do agente nunca importado — quota gasta, sinopse descartada |
| `offer_seed.SEED_PATTERN` | `1000_offer_seeds.json` ignorado pela ingestão |
| `batch_numbering.pending_batch_input` | Não resolvia o lote → o hint de input sumia |

A ordenação de lotes é **numérica** (`int(num)`), não lexicográfica: com
larguras mistas, `"1000" < "999"` como string.

### Testes

Convenção: script de `assert` puro em `scripts/tests/`, sem pytest.

```bash
cd scripts
PYTHONPATH=. python tests/test_batch_numbering.py     # numeração + resolução de lotes
PYTHONPATH=. python tests/test_inject_ml_affiliate.py # tag de afiliado ML
PYTHONPATH=. python tests/test_project_state.py       # ids únicos no project_state
PYTHONPATH=. python tests/test_marketplace_scraper_ordem.py  # ordem das fontes + circuit
```

> ✅ **A lacuna de `paths` já foi fechada — conferido em 2026-08-29.** Estava
> escrito aqui que o workflow disparava só em `paths: scripts/**`, e que um PR
> tocando apenas o `state/project_state.json` não rodaria
> `test_project_state.py`. **Não é mais verdade:** `.github/workflows/tests.yml`
> lista `- 'state/**'` nas **duas** listas (`push` e `pull_request`). O mesmo
> aviso obsoleto estava na docstring de `tests/test_project_state.py` e foi
> corrigido junto.

**No CI:** `.github/workflows/tests.yml` roda `compileall` + todos os
`tests/test_*.py` a cada push/PR que toque em `scripts/**`. O workflow varre o
diretório por glob — **um arquivo novo em `tests/` já entra automaticamente**,
sem editar o YAML.

Não há `pip install` no workflow: os testes atuais dependem só da stdlib. Um
teste que precise de `requests`/`python-dotenv` exige adicionar o passo de
instalação.

> **Testar um step que importa `requests`/`dotenv` sem mexer no workflow.**
> Vários steps fazem `import requests` no topo e `enrich_descricao` também
> importa `dotenv`, então só importar o módulo já quebra no CI com
> `ModuleNotFoundError` (aconteceu duas vezes: `requests` no PR #242, `dotenv`
> no #244 — **confira a cadeia inteira de imports, não só o arquivo alvo**).
> Se o teste faz stub das funções que usariam rede, basta o **nome** existir:
> instale módulos falsos em `sys.modules` **antes** de importar o step — e só
> quando o real estiver ausente, para que localmente o import de verdade
> continue sendo exercitado. Exemplo em `tests/test_backfill_idioma.py`. O stub
> de `requests` define `get` como função que levanta `AssertionError`, então um
> teste que esqueça de trocar alguma fonte falha alto em vez de sair pela rede.

### Eficiência (WS3)

Geração em lote amortiza o overhead fixo da sessão. `BATCH_SIZE_*` é configurável
via env e calibrado por medição (`tools/measure_batch.py`):

> **Dois defeitos da ferramenta, corrigidos em 2026-07-26 — leia antes de confiar
> em medições antigas.** (1) Os exports fazem `min(pacote, BATCH_SIZE)`, então ela
> **nunca media acima do valor já configurado**: um sweep `15,25,35` devolvia
> `exported=15` nas três e parecia válido. Isso explica por que a calibração
> original parou em 15 — o sweep padrão (`5,10,15`) jamais testou nada maior.
> (2) Ela assumia que o agente processa o lote recém-exportado, mas o agente pega
> o de **menor número sem output**; com órfãos na fila, `done` vinha 0.
> Agora o alvo é resolvido por `pending_batch_input` e o resultado registra
> `medido`/`alvo`/`mediu_orfao`, com `s_per_item` sobre o tamanho **medido**.

| Tarefa | BATCH_SIZE | Medido |
|--------|-----------|--------|
| Sinopse | 15 (`BATCH_SIZE_SYNOPSIS`) | ~26 s/livro, 385 s/lote (reconfirmado em 2026-07-25: 387s, 415s, 387s) |
| Categorização | 25 (`BATCH_SIZE_CLASSIFY`) | ~6,5 s/livro, 161 s/lote |
| Bios de autor | 25 (`BATCH_SIZE_AUTHOR_BIO`) | — |

---

## Variáveis de Ambiente (`.env`)

```env
# LLM — Claude PRO via CLI (motor único). Sem chave de API:
# o claude CLI usa a sessão da assinatura. Opcional:
CLAUDE_BIN=                      # caminho explícito do claude.exe, se não estiver no PATH
CLAUDE_SESSION_RESET_MINUTES=300 # janela de sessão (5h)
LLM_PROVIDER=claude              # legado: ollama | gemini | auto (não recomendados)

# Modelo por agente (ver "Modelo por agente"). Opcionais:
CLAUDE_MODEL_FAST=sonnet         # tarefas fechadas (sinopse/categorização)
CLAUDE_MODEL_STRONG=opus         # tarefas com fato sobre entidade real (author_bio)
# CLAUDE_MODEL_AUTHOR_BIO=default       # força o padrão do CLI só nesse agente

# Tamanhos de lote (opcional — sobrescreve defaults calibrados)
BATCH_SIZE_SYNOPSIS=15
BATCH_SIZE_CLASSIFY=25
BATCH_SIZE_AUTHOR_BIO=25

# Rotações (ver "Rotações"). Cotas por ciclo, não lotes. 0 desliga.
BIO_POR_CICLO=25                 # autores por ciclo (= BATCH_SIZE_AUTHOR_BIO)
CLASSIFY_POR_CICLO=25            # livros por ciclo

# Cota não-LLM por passe do G (ver "Monitor de preços no G"). 0 desliga.
PRECO_POR_CICLO=150              # livros visitados pelo offer_price_monitor
PRIORIZAR_ML=1                   # fila do monitor poe livro do ML antes do da Amazon
FORCAR_ML=1                      # step 3 roteia sempre para o ML, ignorando o seed

# Circuit breaker do marketplace no step 4 (ver "Ordem das fontes no step 4").
MP_CIRCUIT_THRESHOLD=3           # falhas seguidas p/ pular o marketplace no lote

# API de catalogo do Mercado Livre (ver "API de catalogo do Mercado Livre").
# App criado no DevCenter; qualquer conta serve, sem requisito de vendas.
ML_CLIENT_ID=...
ML_CLIENT_SECRET=...

# Pre-voo abre o navegador quando falta credencial. 0 desliga (headless/CI).
ABRIR_LOGIN=1

# Google Books (step 2/auditoria de títulos — opcional, sem chave usa quota pública)
GOOGLE_BOOKS_API_KEY=...

# Gemini/Ollama — LEGADO (aposentados; só se reativar o roteador antigo)
# GEMINI_API_KEY=...
# OLLAMA_URL=http://localhost:11434
```

**Supabase** (hard-coded nos steps de publicação):
- URL: `https://ncnexkuiiuzwujqurtsa.supabase.co`
- Chave: service role (em publish.py, publish_autores.py, publish_ofertas.py)

---

## Convenções de Código

> **Afirmação quantitativa leva data e método** — regra do `CLAUDE.md` da raiz,
> e este arquivo é onde ela mais pesa: quase todo número aqui (s/livro, taxas de
> rejeição, tamanho de lote) veio de uma medição que pode ter expirado. Ao
> alterar um step, confira se os números que o descrevem continuam valendo.

### Status flags

Todos os campos `status_*` em `livros` são inteiros:
- `0` = pendente
- `1` = concluído
- `2` = pulado/skipped (apenas `status_cover`)

### Logging

```python
from core.logger import log
log("[STEP_NAME][NNN/TTT] → titulo do livro")
log("[STEP_NAME] OK → titulo")
log("[STEP_NAME] ERRO → titulo | mensagem de erro")
log("[STEP_NAME] Finalizado")
log("OK: X | Falhas: Y | Pulados: Z | Total: N")
```

Timestamp automático no formato `[HH:MM:SS]`. Heartbeat daemon a cada 30s.

### Queries padrão

```python
# Fetch pendentes (padrão de todos os steps)
cur.execute("""
    SELECT id, titulo, autor, idioma, ...
    FROM livros
    WHERE status_X = 0
      AND idioma = ?
    LIMIT ?
""", (idioma, pacote))

# Update após processamento
cur.execute("""
    UPDATE livros
    SET campo = ?,
        status_X = 1,
        updated_at = CURRENT_TIMESTAMP
    WHERE id = ?
""", (valor, livro_id))
conn.commit()
```

### HTTP

- Timeout padrão: 15s connect, scraping marketplace: 12s read
- Retry: 3 tentativas com backoff de 2–3s
- User-Agent realista para scraping
- Delay entre requisições: 0.3s (APIs) · 3s (scraping)

### Seeds

Formato de arquivo: `NNN_offer_seeds.json` (3 dígitos, plural).
Após ingestão: movidos para `data/seeds/ingested_seeds/`.
Campos obrigatórios: `titulo`, `lookup_query`.

---

## Adicionando um Novo Step

1. **Criar** `steps/meu_step.py` com função `run(idioma, pacote)` e padrão de log padrão
2. **Adicionar coluna** `status_meu_step INTEGER DEFAULT 0` em `ensure_schema()` no `core/db.py`
3. **Registrar no menu** em `main.py`: número na faixa do grupo (Geração 10-19,
   Publicação 20-30, Auditoria/QA 40-59 — ver "Menu — numeração por grupos")
4. **Importar** no topo de `main.py`: `from steps import meu_step`
5. Se usar LLM, prefira o **motor batch** (export → `run_agent(<agente>_batch)` →
   import), como `synopsis.py`/`categorize.py`. Evite o roteador legado `set_provider`.

### Template mínimo

```python
# steps/meu_step.py
from core.db import get_conn
from core.logger import log

def run(idioma: str, pacote: int):
    log("[MEU_STEP] Iniciando")
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, titulo FROM livros
        WHERE status_meu_step = 0 AND idioma = ?
        LIMIT ?
    """, (idioma, pacote))
    rows = cur.fetchall()

    ok = falhas = pulados = 0

    for i, (livro_id, titulo) in enumerate(rows, 1):
        log(f"[MEU_STEP][{i}/{len(rows)}] → {titulo}")
        try:
            # ... lógica ...
            cur.execute("""
                UPDATE livros SET status_meu_step = 1,
                updated_at = CURRENT_TIMESTAMP WHERE id = ?
            """, (livro_id,))
            conn.commit()
            ok += 1
        except Exception as e:
            log(f"[MEU_STEP] ERRO → {titulo} | {e}")
            falhas += 1

    conn.close()
    log(f"[MEU_STEP] Finalizado")
    log(f"OK: {ok} | Falhas: {falhas} | Pulados: {pulados} | Total: {len(rows)}")
```

---

## Supabase — Migrations Manuais

**TASK-SUPABASE-001 — APLICADA.** As colunas abaixo já existem na tabela
`livros` do Supabase (verificado em 2026-05-30 via OpenAPI do PostgREST):

```sql
-- JÁ APLICADO no SQL Editor do Supabase
ALTER TABLE livros ADD COLUMN IF NOT EXISTS preco_atual NUMERIC;
ALTER TABLE livros ADD COLUMN IF NOT EXISTS offer_status TEXT DEFAULT 'active';
ALTER TABLE livros ADD COLUMN IF NOT EXISTS preco_updated_at TIMESTAMPTZ;
```

> Compatibilidade SQLite↔Supabase verificada (2026-05-30): todos os campos
> enviados pelos steps de publicação existem no schema do Supabase. Colunas
> locais de pipeline (`sinopse`→publicada como `descricao`; `blacklist_reason`,
> `qa_retry`, `qa_quarantine`, `reactivation_pending`, `preco`, `marketplace`,
> `offer_url`, etc.) NÃO são enviadas ao Supabase — são apenas estado local.

> **⚠️ Gotcha — tabelas `autores` e `listas` NÃO têm `status_publish` no Supabase.**
> Colunas reais de `autores`: `id, nome, slug, nacionalidade, descricao, created_at`.
> `status_publish` existe só no SQLite local (flag de pipeline). Enviá-la no
> payload de upsert retorna **400 PGRST204** ("column not found") e trava a
> publicação. A **presença na tabela já significa "publicado"** (só publicados
> recebem upsert) — por isso o frontend também não filtra por `status_publish`
> nessas tabelas (usa inner join com a junction). Ver `publish_autores.upsert_autor`.

> **⚠️ Gotcha — publicação de autor é one-shot; a bio precisa de resync.**
> `fetch_autores_pendentes` filtra por `status_publish = 0`, então cada autor é
> enviado ao Supabase **uma única vez**. Como a bio (`author_bio`) só é gerada
> muito depois — a fase de bios no `llm_orchestrator` roda **após** sinopse e
> categorização zerarem, o que raramente acontece —, o autor entrava no Supabase
> com `descricao` NULL e nunca mais era reenviado. Medido em 2026-07-25:
> **0 de 8.399 autores no Supabase tinham bio**, embora 308 já tivessem bio no
> SQLite. Corrigido com a coluna local `autores.status_publish_bio` + o resync em
> `publish_autores._resync_bios`, que roda ao final de **todo** `run()` (inclusive
> quando não há autor novo). O payload do resync **não** inclui `created_at` — com
> `resolution=merge-duplicates` o PostgREST só sobrescreve as colunas enviadas, e
> mandá-la reescreveria a data de criação de cada autor re-sincronizado.

---

## Estado Atual

As métricas de estado (totais, pendências por step, backlog do gargalo) mudam a
cada execução e **não são versionadas aqui**. Fontes de verdade:

- **Painel de Status** (opção **S** no menu) — visão ao vivo do pipeline + janela de sessão.
- **`state/project_state.json`** — arquitetura, decisões e métricas de estado do banco.
- Diagnóstico rápido: ver "Atalhos de diagnóstico" no topo deste arquivo.
