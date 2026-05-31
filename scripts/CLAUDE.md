# CLAUDE.md — Pipeline Local · Livraria Alexandria

> Este arquivo é exclusivo do pipeline de ingestão (`/scripts`).
> O CLAUDE.md da raiz cobre o site Next.js.

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

### Menu — numeração por grupos (WS9, 2026-05-30)

O topo roteia para submenus pelas teclas **1-6** (navegação) + letras de ação
(S/G/A/I/O/M/C/E). Dentro de cada submenu, as opções têm faixas sem colisão:

| Submenu | Faixa | Itens |
|---|---|---|
| Ingestão | 1-4 | seeds, enrich, resolver ofertas, scraper |
| Pré-processamento | 5-9 | slugs, slugify autores, dedup autores, dedup, review |
| Geração de Conteúdo | 10-19 | 10 categorizar, 10R reset, 11 sinopses, 12 capas, 13 bios |
| Publicação | 20-30 | 20 QG, 21 publicar, 22 autores, 23 categorias, 24 ofertas, 25 listas SEO, 26 publicar listas, 27 reparar ofertas, 28 fix URLs, 29 importar offer_list, 30 reparar relações |
| Auditoria/QA | 40-51 | 40 preços, 41 conectividade, 42 conteúdo, 43 reparar ruins, 44 reparo slug, 45 blacklist, 46 export auditoria, 47 integridade, 48 listas, 49 autores sem bio, 50 veracidade títulos, 51 consistência |
| Exports | 91-94 | transcripts/estado |
| Banco | 95-97 | backup, restore, recover |

> A geração LLM (10/11/13) e a auditoria de conteúdo usam o **claude CLI**
> (assinatura PRO) via agentes batch — Gemini foi aposentado. A faixa **40+**
> está reservada para o futuro `qa.py` (WS4). Fonte de verdade: `scripts/main.py`.

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
│   ├── cowork/               # Lotes de input/output dos agentes batch (runtime)
│   ├── seeds/                # NNN_offer_seeds.json aguardando ingestão
│   └── seeds/ingested_seeds/ # Seeds já processados (movidos pelo step 1)
└── agents/  (em ../agents/)  # Prompts markdown dos agentes
    ├── synopsis_cowork/prompt.md   # Geração de sinopse em LOTE (motor único)
    ├── classify_cowork/prompt.md   # Categorização em LOTE
    └── author_bio/                 # Bio de autor (MODE 1: identity/rules/task)
```

> **Motor LLM (WS2, 2026-05-30):** a geração usa o **claude CLI** (assinatura PRO)
> via **agentes batch** (`*_cowork`). O antigo FSM de sinopse (`agents/synopsis/*`,
> `markdown_executor` MODE 2) foi **removido**. `markdown_executor` mantém só o
> MODE 1 (agente de estágio único, ex: `author_bio`).

---

## Pipeline — Steps

| # | Nome | Módulo | LLM | Depende de | Status saída |
|---|------|--------|-----|------------|--------------|
| 1 | Importar Seeds | offer_seed.py | — | seeds/*.json | created |
| 2 | Enriquecer Desc *(fallback-only)* | enrich_descricao.py | — | — | descricao preenchida |
| 3 | Resolver Ofertas | offer_resolver.py | — | lookup_query | offer_url |
| 4 | Scraper Marketplace | marketplace_scraper.py | — | offer_url | imagem_url, descricao, preco |
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
| 18 | Auditoria Conectiv | auditor.py | — | — | connectivity_log |
| **19** | **Auditoria Conteúdo** | auditor.py | **Claude** | step 13 | audit_log |
| 91–94 | Exports | export_state_transcript.py | — | — | JSON/markdown |

### Fluxo recomendado para novos seeds

```
1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13 → 14 → 15 → 16
```

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
preco               REAL      semente
preco_atual         REAL      monitorado (step 19)
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
| **Batch** (canônico) | exporta lote JSON → `run_agent` sobre `agents/*_cowork/prompt.md` → importa | sinopse, categorização, bios (opção O, menu 10/11/13, ingestão guiada) |
| **MODE 1** (estágio único) | `execute_agent` sobre `agents/<n>/{identity,rules,task}.md` | author_bio, offer_finder |

### Controle de sessão (não tokens)

O limite relevante é a **janela rotativa de 5h** da sessão PRO, não RPM/RPD:

1. `core/claude_usage_tracker.py` rastreia `session_calls`, `session_started_at` e
   `session_window()` (in_cooldown, seconds_until_reset, reset_at).
2. `SESSION_RESET_MINUTES=300` (5h). Ao detectar limite, `claude_runner` aguarda o
   reset e faz **1 retry**; se persistir, o orquestrador cai no fallback não-LLM.
3. **Persistência:** `data/claude_usage.json`.
4. O painel de Status (opção S) e o relatório da opção G exibem a janela atual.

### Eficiência (WS3)

Geração em lote amortiza o overhead fixo da sessão. `BATCH_SIZE_*` é configurável
via env e calibrado por medição (`tools/measure_batch.py`):

| Tarefa | BATCH_SIZE | Medido |
|--------|-----------|--------|
| Sinopse | 15 (`BATCH_SIZE_SYNOPSIS`) | ~26 s/livro, 385 s/lote |
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

# Tamanhos de lote (opcional — sobrescreve defaults calibrados)
BATCH_SIZE_SYNOPSIS=15
BATCH_SIZE_CLASSIFY=25
BATCH_SIZE_AUTHOR_BIO=25

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
5. Se usar LLM, prefira o **motor batch** (export → `run_agent(<agente>_cowork)` →
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

---

## Estado Atual

As métricas de estado (totais, pendências por step, backlog do gargalo) mudam a
cada execução e **não são versionadas aqui**. Fontes de verdade:

- **Painel de Status** (opção **S** no menu) — visão ao vivo do pipeline + janela de sessão.
- **`state/project_state.json`** — arquitetura, decisões e métricas de estado do banco.
- Diagnóstico rápido: ver "Atalhos de diagnóstico" no topo deste arquivo.
