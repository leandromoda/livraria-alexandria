# CLAUDE.md — Livraria Alexandria

## Estado do projeto

O arquivo `state/project_state.json` (na raiz do repositório) é a fonte de verdade do estado atual do projeto: métricas do pipeline, steps ativos, tasks abertas, bugs conhecidos e decisões de arquitetura. Consulte-o antes de iniciar qualquer tarefa de maior escopo.

---

## Manutenção do project_state.json

O `state/project_state.json` registra **arquitetura e decisões técnicas** — não execuções de pipeline.

### O que REGISTRAR
- Novas features, módulos ou steps criados
- Bugs corrigidos com impacto arquitetural
- Decisões de design (schema, padrões, providers)
- Tasks abertas com análise e plano definidos
- Métricas de estado do banco (livros publicados, ofertas, listas)

### O que NÃO registrar
- Execuções de steps do pipeline ("rodar step X")
- Ingestão de seeds (atividade recorrente — não rastrear quais seeds foram ingeridos)
- Tasks concluídas sem mudança arquitetural (ex: "rodar step 4 para livros pendentes")
- Progresso numérico de execuções (usar logs do pipeline para isso)

### Ao concluir uma task
- Se tem valor arquitetural (novo arquivo, bug fix, nova feature): manter em `open_tasks` com `status: "resolved"`
- Se é execução operacional (run step, ingest seeds): remover após conclusão

---

## Visão geral

Plataforma de descoberta de livros com monetização via links afiliados.

- **Frontend**: Next.js 16 (App Router) + TypeScript + Tailwind CSS v4
- **Banco**: Supabase (PostgreSQL) em produção; SQLite local para o pipeline
- **Pipeline**: Python CLI (`scripts/main.py`) — ingestão, enriquecimento, publicação
- **Deploy**: Vercel (frontend) + Supabase Cloud (banco)

---

## Comandos principais

### Frontend

```bash
npm run dev      # servidor local em http://localhost:3000
npm run build    # build de produção
npm run lint     # ESLint
```

### Pipeline Python

```bash
# Ativar virtualenv antes de rodar
source venv/Scripts/activate      # Windows (Git Bash)
# ou
venv\Scripts\activate.bat         # Windows (cmd)

python scripts/main.py            # menu interativo
```

Sequência padrão completa:

```
1 → Importar seeds
2 → Enriquecer descrições
3 → Resolver ofertas
4 → Marketplace scraper (capa + preço)
5 → Slugs
6 → Slugify autores
7 → Deduplicar
8 → Review editorial
9 → Categorias temáticas (LLM)
10 → Sinopses (LLM)
11 → Capas
12 → Quality gate
13 → Publicar livros
14 → Publicar autores
15 → Publicar ofertas
16 → Gerar listas SEO
```

---

## Fluxo de trabalho Git (obrigatório para alterações de código)

**Toda alteração em arquivo do repositório** (código, docs, config) segue este
ciclo, ponta a ponta, **sem usar o GitHub Desktop** — o assistente conduz tudo
via `git` + `gh` CLI.

> **⚠️ GitHub Desktop deve ficar FECHADO durante todo o trabalho.**
> Seu auto-commit/stash concorrente já causou múltiplos incidentes: conflito de
> stash, fragmentação de changeset e troca de branch sob os pés do assistente.
> Com ele fechado, o fluxo via CLI é seguro e o repo local fica sempre atualizado.

> **⚠️ Um PR por vez — sem trabalho paralelo em branches.**
> Antes de criar um novo branch, **fechar o ciclo completo** do anterior:
> merge + `git pull --ff-only` no main local. Trabalhar em duas seções
> simultaneamente causa PRs com conteúdo misturado e conflitos de base.

### Pré-condição obrigatória antes de criar qualquer branch

```bash
# 1. Verificar se há PRs abertos — não deve haver nenhum
gh pr list --state open

# 2. Verificar branch atual — deve estar em main, limpo
git status
git branch --show-current   # deve imprimir "main"
```

Se houver PR aberto: **fechar o ciclo dele primeiro** (merge + pull) antes de
continuar.

### Ciclo completo (10 passos)

1. **Sincronizar o main local** antes de começar:
   `git checkout main && git pull --ff-only`.
2. **Criar branch** descritivo: `git checkout -b <tipo>/<slug>`
   (`feat/`, `fix/`, `docs/`, `refactor/`). **Nunca commitar direto no `main`.**
3. **Implementar** a mudança.
4. **Validar antes de commitar** (PR não pode quebrar o CI):
   - Pipeline Python: `python -m py_compile <arquivos>` (+ teste rápido se aplicável).
   - Site: `npm run lint` e `npm run build`.
5. **Commitar** com mensagem convencional + trailer
   `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
6. **Push**: `git push -u origin <branch>`.
7. **Abrir PR**: `gh pr create --base main --title … --body …`.
8. **Revisar**: conferir `gh pr checks <n>` (CI verde) + diff antes de mergear.
9. **Mergear**: `gh pr merge <n> --squash --delete-branch`
   (squash + remove o branch remoto).
10. **Fechar o ciclo local**:
    ```bash
    git checkout main && git pull --ff-only
    git branch -d <branch>   # apaga branch local se ainda existir
    ```

> Resumo: `verificar PRs abertos → main atualizado → branch → validar → commit →
> push → PR → revisar → merge (squash, delete) → pull main → apagar branch local`.

### Autorização permanente — não perguntar a cada vez

Concedida por Leandro em **2026-07-10** e reafirmada em **2026-08-02**. Uma vez
que a alteração de código foi pedida, **o ciclo inteiro roda sozinho**, sem
parar para confirmar cada etapa:

- commitar e fazer push em branch de feature (**nunca** direto no `main`);
- abrir PR (`gh pr create`);
- **mergear com `--squash --delete-branch` depois do CI verde**;
- fechar o ciclo local (`pull --ff-only` + apagar o branch).

Não pergunte "quer que eu abra o PR?" nem "posso mergear?" — execute e relate o
que foi feito. O acompanhamento é pelos eventos de CI e pelo resumo final.

**Continuam exigindo confirmação explícita:** `git push --force`, `reset --hard`,
`branch -D`, apagar dados, mergear com check falhando, mudanças de escopo maior
no produto, e o que as regras de segurança já proíbem (credenciais, pagamentos).

> Isto **substitui** a regra anterior ("commit/PR só acontecem quando o usuário
> pede"), que contradizia a autorização de 2026-07-10 e fazia o assistente parar
> a cada PR para pedir algo já concedido. O gatilho continua sendo o pedido de
> alteração; o que não se pede mais é permissão para **publicá-la**.

### ⚠️ Subprocesso trava a máquina — um comando por vez (medido em 2026-08-06)

> **Estado em 2026-08-08:** a causa principal foi removida (Avira desinstalado,
> ver o ✅ abaixo). As regras desta seção **continuam valendo** — a máquina tem
> 4 núcleos e o efeito do Defender sob carga ainda não foi medido. Reavaliar
> depois de um `npm run build` completo com a nova configuração.

Esta máquina **engasga com subprocessos concorrentes**. Em 2026-08-06 travou
**duas vezes** na mesma sessão — a segunda exigiu **reiniciar a máquina**.

**A causa é o antivírus varrendo os arquivos do projeto, e o gargalo é CPU —
não memória.** Medido em 2026-08-06 durante os travamentos: **CPU 100%,
memória 26–30%, disco 0–6%**. Os fatos:

- A máquina tem **4 núcleos lógicos** (`Win32_ComputerSystem`). É pouco.
- **O culpado é o antivírus.** Com o Gerenciador ordenado **por CPU**, durante
  um travamento: **Endpoint Protection Service (Avira) = 92,6%**, contra 3,7%
  do Claude (14 processos) e <2% de todo o resto.
- **Por que os comandos deste projeto disparam isso:** o Avira varre em tempo
  real **cada arquivo aberto**. `npm run build`, `npm run lint` e o `git`
  percorrem dezenas de milhares de arquivos (`node_modules/`, `.next/`,
  `.git/`) — cada um vira uma varredura. Não é o Node que come a CPU: é o
  antivírus reagindo ao Node.
- ⚠️ **Correção de um diagnóstico anterior desta mesma sessão:** chegou a ficar
  escrito aqui que "o Claude Code é o maior consumidor (~10%)". Aquilo foi
  medido com a **máquina ociosa** e não se sustenta sob carga. Medição em
  repouso não serve para achar culpado de travamento — tem que ser durante.
- ✅ **RESOLVIDO em 2026-08-08: o Avira foi desinstalado.** Medição logo após a
  remoção: **nenhum processo `avira`/`endpointprotection` vivo**, e o topo de
  CPU passou a ser o próprio Claude (~24% somados, 29,7% no total da máquina)
  — os 92,6% sumiram. O Microsoft Defender reassume sozinho quando o antivírus
  de terceiro sai.
- **O que ainda falta configurar** (é do Leandro, não do assistente — mexer em
  config de antivírus está fora do que o assistente faz): as **exclusões do
  Defender** em *Segurança do Windows → Proteção contra vírus e ameaças →
  Exclusões*, para `node_modules/`, `.next/`, `.git/` e `venv/` do projeto,
  mais o processo `node.exe`. O Defender **também** varre em tempo real; trocar
  de antivírus sem excluir essas pastas não garante o ganho.
  ⚠️ Custo real da exclusão, para decidir com o dado à vista: `node_modules/` é
  exatamente onde um ataque de supply chain em dependência npm apareceria. O
  mitigador é o conteúdo vir de `package-lock.json` e ser reinstalável. Excluir
  essas quatro pastas — nunca o repositório inteiro, o disco ou Downloads.
- **Ainda não medido:** o efeito do Defender sob carga real (`npm run build`)
  nesta máquina. Se o travamento voltar, o próximo suspeito é o **Componente de
  Segurança Bradesco** (Warsaw/Topaz, do internet banking), que continua
  residente — aparecia com uso baixo nos dois travamentos, mas não foi isolado.
- `next build` sobe **3 workers** (aparece no próprio log: "Generating static
  pages using 3 workers") — com 4 núcleos, isso mais o baseline ocupa a máquina
  inteira.
- `eslint` sem cache prende um núcleo por mais de 7 min sem terminar.

**Consequência que confunde o diagnóstico:** com a CPU saturada, `git` e `gh`
ficam sem fatia e estouram timeout. Isso *parece* hang de rede e **não é** — é
inanição de CPU. Foi o que aconteceu em 2026-08-06: `npm run lint` estourou
**5 min** e depois **7 min** (`npx eslint` em 2 arquivos); `git credential fill`
pendurou **2 min**; `git rev-list`/`git log`, **40–90 s**; `gh pr create`,
**4 min**; `curl` para `api.github.com`, **60 s** — todos com saída vazia,
enquanto `git status` (instantâneo) nunca falhou. A regra prática que sai daí:
**comando curto passa mesmo sob carga; comando longo só passa com a máquina
livre.**

Antes de rodar qualquer coisa pesada, vale **fechar as sessões do Claude Code
que não estão em uso** — cada uma carrega processos que somam no baseline.

⚠️ **`npm run lint` não roda nesta máquina.** Não é flake: falhou nas duas
tentativas e a segunda derrubou o sistema. **Não tentar de novo** — validar com
`npm run build` (que já faz o type-check) e deixar o ESLint para o CI da Vercel,
dizendo isso no relato e no corpo do PR.

Nota de fluxo: `git status --short`, `git add` e `git commit` são leves e
funcionaram o tempo todo, inclusive logo após o reboot (o índice sobrevive).
O que pendura é comando com **rede** (`push`, `gh`, `curl` externo) ou **pager**.

#### ⚠️ A regra abaixo é POR SESSÃO — ela não protege contra várias sessões

"Um comando por vez" governa o que **um** assistente dispara. Duas sessões do
Claude Code abertas ao mesmo tempo, cada uma obedecendo a regra, ainda colocam
**dois `next build` concorrentes** na máquina — que é exatamente o cenário que a
derruba. Nenhuma sessão enxerga a outra, então **isto não se resolve sozinho**:

- **`npm run build` é exclusivo da máquina inteira**, não da sessão. Se houver
  outra sessão do Claude Code (ou um `npm run dev`, ou o pipeline Python
  rodando), **não iniciar o build** — perguntar ao Leandro antes.
- **Trabalho de código em uma sessão por vez.** É a mesma razão do "um PR por
  vez" e do "GitHub Desktop fechado": sessões concorrentes compartilham um único
  working tree. Em 2026-08-06 isso foi **observado**: arquivos modificados em
  `scripts/` e `state/` sumiram do working tree no meio da sessão sem que o
  assistente os tocasse. Sessão paralela pode usar o repo em modo leitura
  (`Read`/`Grep`/análise), mas não deve editar, commitar nem buildar.
- Se o assistente suspeitar de sessão paralela — working tree mudando sozinho,
  branch trocando, arquivo que ele não editou aparecendo staged — **parar e
  avisar**, em vez de seguir e commitar por cima.

Regras (dentro de uma sessão):

- **Um comando de shell por vez.** Não disparar várias chamadas `Bash`/
  `PowerShell` no mesmo bloco de resposta, mesmo quando são independentes — a
  orientação geral de paralelizar chamadas **não vale para shell aqui**.
- **Não acumular `run_in_background`.** No máximo um de cada vez, e só para
  comando realmente longo (`npm run build`). Nunca deixar dois rodando juntos.
- **Agrupar leituras num único script** em vez de um comando por consulta
  (ex.: um `bash` que faz os N `curl` em sequência, não N chamadas da ferramenta).
- Preferir as ferramentas dedicadas (`Read`, `Grep`, `Glob`) a `cat`/`grep`/
  `find` via shell — não abrem subprocesso pesado.
- Hang é **intermitente**: repetir uma vez é aceitável, insistir não. Se um
  comando pendurou duas vezes, seguir sem ele e **dizer isso no relato**, em vez
  de continuar tentando.

### Armadilhas de shell no Windows (medidas em 2026-08-02)

- **O pager do `git` trava a sessão não-interativa.** `git show` / `git log` sem
  `--no-pager` penduram até o timeout de 2 min: o comando executa, mas o pager
  nunca devolve o terminal. Use `git --no-pager <cmd>` ou `$env:GIT_PAGER='cat'`.
  Cuidado ao diagnosticar: num caso o `git commit` funcionou e só o `git show`
  seguinte pendurou — parece falha do commit, e não é.
- **`git commit -m @'…'@` quebra com aspas duplas dentro.** A here-string do
  PowerShell é repassada de forma que o git lê pedaços da mensagem como
  *pathspec* (`error: pathspec '…' did not match any file(s)`). Escreva a
  mensagem num arquivo e use `git commit -F <arquivo>`.
- **O `gh` CLI é intermitente — não conte com ele.** Em 2026-08-02 rodou inteiro
  (`pr list`, `pr create`, `pr checks --watch`, `pr merge`), o que derrubou a
  afirmação de 2026-07-24 de que "qualquer comando `gh` pendura". Mas em
  **2026-08-06 pendurou de novo**: `gh pr create --body-file` estourou **4 min**
  e `gh pr list --json` estourou **75 s**, ambos sem saída, logo após um
  `git push` bem-sucedido no mesmo branch. Ou seja: as duas afirmações
  absolutas ("funciona" / "sempre trava") estão erradas — é intermitente.
  Tratamento: tentar **uma vez**; se pendurar, **não repetir** — abrir o PR pela
  URL que o próprio `git push` imprime, ou cair para a API REST.
- **`git push` sobre HTTPS funcionou** mesmo nas sessões em que `gh` pendurou
  (2026-08-06). Não presuma que a rede inteira está fora quando o `gh` trava.

### Pré-autorização de comandos fica em `.claude/settings.json`

`CLAUDE.md` é instrução para o assistente — o harness **não** o lê como política
de permissão. Quem libera comando sem prompt é `permissions.allow` em
`.claude/settings.json` (versionado, vale para o time) ou
`.claude/settings.local.json` (gitignored, só sua máquina). Comando novo que
aparecer com frequência e for de baixo risco deve ser acrescentado lá, não aqui.

> **⚠️ Comando composto anula o allowlist.** O padrão casa contra a **string
> inteira** do comando. Prefixar tudo com `$env:GIT_PAGER='cat'; cd "C:\…"; …`
> transforma cada chamada numa string única que **nenhuma regra alcança** — foi
> o que aconteceu em 2026-08-02: mesmo com `gh pr checks` liberado, o comando
> pedia autorização por causa do prefixo. Regras:
> - **Não prefixar com `cd`/`Set-Location`** — o diretório de trabalho da
>   ferramenta já é a raiz do projeto.
> - **Um comando por chamada** quando ele for do allowlist; encadear com `;` só
>   quando os passos realmente dependem um do outro e o prompt não importa.
> - Precisa de env var recorrente (ex.: `GIT_PAGER`)? Prefira `git --no-pager`
>   no próprio comando, ou ponha a variável em `env` no `settings.json`, em vez
>   de repeti-la inline a cada chamada.

---

## Estrutura de arquivos (site)

```
app/
├── layout.tsx                    # root layout — header, footer, metadata global
├── globals.css                   # design tokens (CSS vars + Tailwind)
├── _components/Header.tsx        # nav sticky, hamburger mobile, busca funcional
├── (public)/
│   ├── page.tsx                  # homepage
│   ├── livros/page.tsx           # índice de livros
│   ├── livros/[slug]/page.tsx    # detalhe do livro + ofertas + schema:Product
│   ├── ofertas/page.tsx          # lista de ofertas + schema:ItemList
│   ├── listas/[slug]/page.tsx    # lista editorial + schema:ItemList
│   ├── autores/[slug]/page.tsx   # perfil do autor
│   └── categorias/[slug]/page.tsx
└── (internal)/
    ├── admin/page.tsx            # dashboard interno
    └── api/click/[id]/route.ts  # edge function de click tracking → redirect afiliado

lib/
├── supabase.ts                   # cliente Supabase anon (uso em server components)
└── supabase-admin.ts             # cliente Supabase service role (uso restrito)

scripts/
├── main.py                       # CLI orquestrador
├── core/                         # db.py, logger.py, markdown_executor.py
├── steps/                        # 1 módulo por etapa do pipeline
├── data/seeds/                   # JSONs de importação (001_offer_seed.json …)
└── data/books.db                 # SQLite local (estado do pipeline)

agents/synopsis/                  # agentes LLM (fact_extractor → writer → validator)
public/                           # assets estáticos (logo, etc.)
```

---

## Convenções obrigatórias

### Afirmação quantitativa leva data e método — ou não se escreve

Vale para comentário de código, docstring, `CLAUDE.md`, corpo de PR e
`project_state.json`. Se um texto afirma **quanto**, **qual é mais rápido**,
**qual modelo**, **é seguro porque** ou **está calibrado** — precisa dizer
**quando** e **como** foi verificado.

```python
# ERRADO — plausível, não verificado, e envelhece em silêncio
# A camada 5/6 é segura porque o agente rejeita depois.
BATCH_SIZE = 15   # calibrado por medição

# CERTO — dá para reconferir e para saber quando expirou
# Medido em 2026-07-25 (n=5.721): a camada sem casar título produz 24,8% de
# rejeição contra 0% do scraping. É segura quanto a publicar errado, mas cara:
# cada rejeição gasta uma chamada do gargalo. Ver TASK-ENRICH-001.
BATCH_SIZE = 15   # medido 2026-07-25: ~26 s/livro (387s, 415s, 387s em 3 corridas)
```

**Por que a regra existe.** Na sessão 32, cinco premissas assim caíram quando
alguém finalmente mediu: o CLI usar Opus por padrão (era Sonnet), `claude auth
status` ser confiável (reporta `loggedIn` com token expirado), a camada fraca do
`_pick_descricao` explicar o mismatch (explicava 20%), subir o limiar de
similaridade ser a correção (destruiria mais acertos do que erros), e o
`measure_batch` medir o tamanho pedido (media sempre o já configurado). **Duas
delas estavam escritas no código como justificativa** e foram lidas por meses
como fato.

Regras práticas:

- Sem número medido, escreva a incerteza em vez de omiti-la: *"suposto, não
  medido"* é informação; uma afirmação seca é armadilha.
- Registre o **método** junto (`n=`, ferramenta, comando), para dar reconferir.
- Ao mudar o que uma medição descreve, **atualize ou remova** a afirmação — dado
  velho sem data é pior que ausência de dado.
- Se descobrir que uma afirmação existente é falsa, **corrija o texto no mesmo
  PR** em que age sobre ela, e diga o que era e o que é.

### Supabase — sempre usar o cliente compartilhado

```ts
// CERTO
import { supabase } from "@/lib/supabase";

// ERRADO — não criar cliente inline nas páginas
import { createClient } from "@supabase/supabase-js";
const supabase = createClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, ...);
```

### SEO — generateMetadata em toda página dinâmica

Toda rota com parâmetro (`[slug]`) deve exportar `generateMetadata`:

```ts
import type { Metadata } from "next";

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { slug } = await params;
  const { data } = await supabase.from("livros").select("titulo, descricao").eq("slug", slug).single();
  if (!data) return {};
  return {
    title: data.titulo,
    description: data.descricao?.slice(0, 160),
  };
}
```

### Segurança — target="_blank" sempre com rel

```tsx
// CERTO
<a href={url} target="_blank" rel="noopener noreferrer">

// ERRADO
<a href={url} target="_blank">
```

### Formatação de preço (pt-BR)

```ts
function formatPrice(value: unknown): string {
  return Number(value).toLocaleString("pt-BR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}
// Uso: R$ {formatPrice(o.preco)}
// Resultado: R$ 49,90  (não R$ 49.9)
```

### Navegação interna — Link do Next.js

```tsx
// CERTO — no layout.tsx e componentes React
import Link from "next/link";
<Link href="/sobre">Sobre</Link>

// Aceitável — em Server Components que renderizam HTML puro
<a href="/sobre">Sobre</a>
```

### Design system — paleta e tipografia

Usar sempre as cores do design system. Não usar classes `gray-*`, `blue-*` ou qualquer cor Tailwind fora da paleta abaixo.

| Token | Hex | Uso |
|---|---|---|
| `brand-primary` | `#4A1628` | Burgundy — backgrounds, badges, avatares |
| `brand-accent` | `#C9A84C` | Gold — CTAs, links ativos, destaques |
| `brand-surface` | `#F5F0E8` | Off-white — background geral |
| `brand-text` | `#0D1B2A` | Navy escuro — texto principal |
| `brand-muted` | `#4A4A4A` | Cinza — texto secundário |
| `brand-warm` | `#7B5E3A` | Marrom — metadados, contadores |
| `brand-border` | `#E6DED3` | Bege — bordas de cards |

Tipografia:
- **Título/sinopse**: `font-serif` (Lora)
- **UI/corpo**: `font-sans` (Inter, padrão do body)

### Padrão de card

```tsx
<a
  href={`/livros/${l.slug}`}
  className="group flex items-center gap-4 bg-white border border-[#E6DED3] rounded-xl px-5 py-4 hover:border-[#C9A84C] hover:shadow-sm transition-all"
>
  {/* capa 40×56 px */}
  {/* título font-medium text-[#0D1B2A] group-hover:text-[#4A1628] */}
  {/* subtítulo text-xs text-[#7B5E3A] */}
</a>
```

---

## Schema do banco (principais tabelas)

```
livros          id, titulo, slug, autor, descricao, isbn, ano_publicacao,
                imagem_url, idioma, cluster
                status: slug | dedup | synopsis | review | cover | publish

ofertas         id, livro_id, preco, marketplace, url_afiliada, ativa

oferta_clicks   id, oferta_id, livro_id, user_agent, referer, ip_hash,
                utm_source, utm_medium, session_id, created_at

autores         id, nome, slug, nacionalidade, status_publish
categorias      id, nome, slug, status_publish
listas          id, titulo, slug, introducao, status_publish

-- junction
livros_autores          livro_id, autor_id
livros_categorias       livro_id, categoria_id
lista_livros            lista_id, livro_id, posicao
livros_categorias_tematicas  livro_id, categoria_id, confianca
```

---

## Variáveis de ambiente

```
# Frontend (.env.local)
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=
NEXT_PUBLIC_SITE_URL=https://livrariaalexandria.com.br
VERCEL_ACCESS_TOKEN=          # analytics do admin dashboard

# Pipeline Python (scripts/.env ou sistema)
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
GOOGLE_BOOKS_API_KEY=
GEMINI_API_KEY=               # opcional — LLM cloud
OLLAMA_BASE_URL=http://localhost:11434  # opcional — LLM local
```

---

## Click tracking (edge function)

`GET /api/click/[id]` — roda em Vercel Edge Runtime

1. Busca `ofertas` pelo `id`
2. Faz hash SHA-256 do IP (`x-forwarded-for`)
3. Insere em `oferta_clicks` (oferta_id, livro_id, user_agent, referer, ip_hash)
4. Retorna `302` para `url_afiliada`

Não adicionar auth a essa rota — precisa ser pública para os redirecionamentos funcionarem.

---

## LLM / agentes

- Agentes definidos em `agents/synopsis/` via arquivos markdown (`identity.md`, `rules.md`, `task.md`, `critic.md`)
- Executor: `scripts/core/markdown_executor.py`
- Providers: `gemini` (padrão), `ollama` (local), `auto` (gemini → fallback ollama)
- Pipeline de sinopse: `fact_extractor → abstract_structurer → synopsis_writer → synopsis_validator`

---

## Vercel Plugin (instalado)

O plugin Vercel está ativo e injeta contexto Next.js/Vercel automaticamente nas sessões deste projeto.

### Comandos úteis

- `/vercel-plugin:status` — visão geral do projeto e deployments recentes
- `/vercel-plugin:env` — gerenciar variáveis de ambiente (listar, pull, diff)

### Comandos NÃO usar neste projeto

- `/vercel-plugin:deploy` e `vercel deploy --prod` — o deploy acontece **automaticamente** via merge no `main` (Vercel CI integrado ao GitHub). Usar o fluxo de PR obrigatório descrito acima.
- `/vercel-plugin:bootstrap` — projeto já está configurado e vinculado ao Vercel.

### Defaults do plugin que NÃO se aplicam aqui

| Default do plugin | Convenção deste projeto |
|---|---|
| shadcn/ui + Geist como UI padrão | Design system próprio — Lora + Inter + paleta `brand-*` |
| Dark mode para dashboards e AI UIs | Tema editorial **light** em todo o site, incluindo o admin |
| Tokens zinc/slate/neutral | Paleta `brand-*` exclusiva — nenhuma cor Tailwind genérica |
| Neon Postgres / Upstash Redis | **Supabase** (PostgreSQL) — não migrar |
| `vercel deploy` CLI como fluxo de CI/CD | PR → squash merge → Vercel auto-deploys a partir do `main` |
| `proxy.ts` (renomeado de `middleware.ts` no Next.js 16) | Não temos middleware — se necessário no futuro, usar `proxy.ts` |

---

## O que NÃO fazer

- Não escrever afirmação quantitativa (quanto, qual é mais rápido, "é seguro
  porque", "calibrado") sem data e método — ver "Afirmação quantitativa leva
  data e método"
- Não criar `createClient(...)` inline nas páginas — usar `lib/supabase.ts`
- Não usar cores Tailwind fora da paleta (`gray-*`, `blue-*`, etc.)
- Não omitir `rel="noopener noreferrer"` em links externos com `target="_blank"`
- Não omitir `generateMetadata` em rotas dinâmicas
- Não exibir termos internos ao usuário público (ex: "Monetização", "Pipeline")
- Não formatar preços com `.toFixed(2)` — usar `toLocaleString("pt-BR", ...)`
- Não usar `<a>` para navegação interna em componentes React — usar `<Link>`
- Não usar `vercel deploy --prod` diretamente — o deploy é automático via merge no `main`
- Não usar shadcn/ui, Geist, nem tokens zinc/slate — usar o design system da livraria
- Não migrar banco para Neon/Upstash — o projeto usa Supabase
- Não sugerir ao usuário "rodar o step X" / "rodar a opção N" para resolver
  gargalos do pipeline — o uso é, por padrão, **autopilot (opção G)**. Step não
  coberto deve ser **incorporado** ao autopilot, não delegado ao usuário. Ver
  "Gargalo de publicação" em [scripts/CLAUDE.md](scripts/CLAUDE.md).
