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
> Commit/PR só acontecem quando o usuário pede a alteração; este fluxo é o
> **como**, não um gatilho automático.

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
