# CLAUDE.md — Pipeline Local · Livraria Alexandria

> Este arquivo é exclusivo do pipeline de ingestão (`/scripts`).
> O CLAUDE.md da raiz cobre o site Next.js.

---

## Execução

```bash
cd scripts
python main.py
```

O menu interativo pede idioma, tamanho do pacote e (quando relevante) provider LLM.

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

# Uso do Gemini hoje
python -c "from core.gemini_limiter import status; import json; print(json.dumps(status(), indent=2))"

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
│   ├── markdown_executor.py  # Roteador LLM (Gemini / Ollama) + pipeline de agentes
│   ├── gemini_limiter.py     # Controle de tier Gemini (RPM + RPD)
│   ├── markdown_memory.py    # Memória persistente de agentes (tabela pipeline_state)
│   ├── logger.py             # Log com timestamp [HH:MM:SS] + heartbeat daemon
│   ├── length_enforcer.py    # Utilitário de limite de caracteres
│   └── state.py              # state.json I/O
├── steps/                    # Um arquivo por step (ver tabela abaixo)
├── data/
│   ├── books.db              # SQLite principal (~1.3 MB)
│   ├── taxonomy.json         # 100+ categorias temáticas
│   ├── gemini_usage.json     # Contadores de uso Gemini (auto-gerado)
│   ├── seeds/                # NNN_offer_seeds.json aguardando ingestão
│   └── seeds/ingested_seeds/ # Seeds já processados (movidos pelo step 1)
└── agents/  (em ../agents/)  # Prompts markdown por domínio/stage
    └── synopsis/
        ├── fact_extractor/   {identity,rules,task}.md
        └── synopsis_writer/  {identity,rules,task}.md
```

---

## Pipeline — Steps

| # | Nome | Módulo | LLM | Depende de | Status saída |
|---|------|--------|-----|------------|--------------|
| 1 | Importar Seeds | offer_seed.py | — | seeds/*.json | created |
| 2 | Enriquecer Desc | enrich_descricao.py | — | — | descricao preenchida |
| 3 | Resolver Ofertas | offer_resolver.py | — | lookup_query | offer_url |
| 4 | Scraper Marketplace | marketplace_scraper.py | — | offer_url | imagem_url, descricao, preco |
| 5 | Gerar Slugs | slugify.py | — | — | status_slug=1 |
| 6 | Slugify Autores | slugify_autores.py | — | — | autores.slug |
| 7 | Deduplicar | dedup.py | — | — | status_dedup=1 |
| 8 | Review | review.py | — | — | status_review=1 |
| **9** | **Categorizar** | categorize.py | **Gemini** | review=1 | livros_categorias_tematicas |
| **10** | **Gerar Sinopses** | synopsis.py | **Gemini** | review=1 | status_synopsis=1 |
| 11 | Gerar Capas | covers.py | — | — | status_cover=1/2 |
| 12 | Quality Gate | quality_gate.py | — | steps 5,8,10,11 | is_publishable=0/1 |
| 13 | Publicar Supabase | publish.py | — | is_publishable=1 | status_publish=1 |
| 14 | Publicar Autores | publish_autores.py | — | step 13 | autores.status_publish=1 |
| 15 | Publicar Ofertas | publish_ofertas.py | — | step 13 | status_publish_oferta=1 |
| 16 | Listas SEO | list_composer.py | — | step 13 | tabelas listas/listas_livros |
| 17 | Monitor Preços | offer_price_monitor.py | — | step 13 | offer_price_log |
| 18 | Auditoria Conectiv | auditor.py | — | — | connectivity_log |
| **19** | **Auditoria Conteúdo** | auditor.py | **Gemini** | step 13 | audit_log |
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

## LLM — Uso e Controle de Tier

### Providers disponíveis

| Provider | Velocidade | Custo | Quando usar |
|----------|-----------|-------|-------------|
| **Gemini** (padrão) | ~150 tok/s | Grátis (tier) | Sempre — padrão atual |
| Ollama local | ~2 tok/s (CPU) | Zero | Não viável nesta máquina (GT 720M, sem CUDA) |
| Auto | Gemini → Ollama | Grátis/Zero | Fallback se Gemini falhar |

**Hardware local:** NVIDIA GeForce GT 720M (~1 GB VRAM) sem driver CUDA.
Ollama roda em CPU a ~2 tok/s — inviável para o pipeline de sinopses (~10 min/livro).

### Tier Gratuito Gemini

| Modelo | RPM | RPD | TPM |
|--------|-----|-----|-----|
| gemini-2.0-flash | 15 | 1.500 | 1.000.000 |
| gemini-2.5-flash | 15 | 1.500 | 1.000.000 |

**Limites conservadores (padrão):** 12 RPM · 1.400 RPD
Sobrescrever no `.env`:
```env
GEMINI_RPM_LIMIT=12
GEMINI_RPD_LIMIT=1400
GEMINI_RPD_WARN=1200
```

### Como o limiter funciona

O módulo `core/gemini_limiter.py` é chamado automaticamente dentro de `_call_gemini()`:

1. **RPM:** Janela deslizante de 60s. Se >= RPM_LIMIT chamadas na janela, dorme até a mais antiga expirar.
2. **RPD:** Se >= RPD_LIMIT, levanta `RuntimeError("GEMINI_DAILY_LIMIT_REACHED")` — interrompe o step.
3. **Aviso:** Ao atingir RPD_WARN (padrão 1.200/dia), imprime alerta mas continua.
4. **Persistência:** `data/gemini_usage.json` — reset automático à meia-noite UTC.

### Steps que usam LLM

| Step | Chamadas LLM por livro | Tokens estimados |
|------|----------------------|-----------------|
| 8 — Sinopses | 2 (fact_extractor + synopsis_writer) | ~800–1.200 |
| 16 — Auditoria conteúdo | 1 | ~400–600 |
| 18 — Categorizar | 1 | ~200–400 |

Com 1.400 req/dia úteis: ~700 sinopses/dia ou ~1.400 categorizações/dia.

---

## Variáveis de Ambiente (`.env`)

```env
# LLM — Gemini (obrigatório para steps 8, 16, 18)
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.5-flash

# Google Books (step 2 — opcional, sem chave usa quota pública)
GOOGLE_BOOKS_API_KEY=...

# Ollama (fallback local — lento em CPU)
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=mistral:latest
LLM_PROVIDER=gemini      # ollama | gemini | auto

# Controle de tier Gemini (opcional — sobrescreve defaults)
GEMINI_RPM_LIMIT=12
GEMINI_RPD_LIMIT=1400
GEMINI_RPD_WARN=1200
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
3. **Registrar no menu** em `main.py`: nova opção numérica (próximo inteiro disponível após 19)
4. **Importar** no topo de `main.py`: `from steps import meu_step`
5. Se usar LLM: chamar `set_provider(escolher_provider())` antes de `meu_step.run(...)`

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

## Supabase — Migrations Manuais Pendentes

As colunas abaixo existem no SQLite mas ainda precisam ser criadas no Supabase:

```sql
-- Rodar no SQL Editor do Supabase (TASK-SUPABASE-001)
ALTER TABLE livros ADD COLUMN IF NOT EXISTS preco_atual NUMERIC;
ALTER TABLE livros ADD COLUMN IF NOT EXISTS offer_status TEXT DEFAULT 'active';
ALTER TABLE livros ADD COLUMN IF NOT EXISTS preco_updated_at TIMESTAMPTZ;
```

---

## Estado Atual (ref. 2026-03-17)

| Métrica | Valor |
|---------|-------|
| Total de livros no SQLite | 1.339 |
| Com review concluído | 196 |
| Com sinopse gerada | 112 |
| Publicados no Supabase | 112 |
| Seeds aguardando ingestão | 026–058 (33 arquivos) |
| Step 17 — scraper marketplace | 20 feitos · 250 pendentes |
| Step 8 — sinopses pendentes | 84 |
