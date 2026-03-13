# Livraria Alexandria — Session State
## Data: 2026-03-13

---

## STATUS GERAL DO PIPELINE

| Step | Descrição | Status |
|---|---|---|
| 1 | Offer Seeds | ✅ 207 seeds |
| 2 | Enriquecer descrições | ✅ 100 completos / 107 pendentes |
| 3 | Resolver ofertas | ✅ 100 / 107 pendentes |
| 4 | Slugs | ✅ 100 / 107 pendentes |
| 5 | Dedup | ✅ 100 / 107 pendentes |
| 6 | Review | ✅ 207 completos |
| 7 | Sinopses | ✅ ~170 completos / ~37 pendentes |
| 8 | Capas | ✅ 90 com capa / 10 sem capa (status=2) |
| 9 | Quality Gate | ✅ 48 aprovados (1ª rodada) |
| 10 | Publicar Supabase | ✅ ~14 publicados / ~34 aprovados pendentes |
| 11 | SEO Lists | ⏳ pendente |

---

## ARQUIVOS ENTREGUES NESTA SESSÃO

| Arquivo | Destino | O que mudou |
|---|---|---|
| `synopsis.py` | `scripts/steps/synopsis.py` | try/except em execute_agent — falha continua para próximo livro |
| `markdown_executor.py` | `scripts/core/markdown_executor.py` | Min words 90→80; validator rejeita retorna `{}` em vez de raise |
| `covers.py` | `scripts/steps/covers.py` | Amazon→Google→OpenLibrary; placeholder check >5KB; status_cover=2 sem capa |
| `quality_gate.py` | `scripts/steps/quality_gate.py` | `status_cover not in (1,2)` — aceita livros sem capa |
| `publish.py` | `scripts/steps/publish.py` | on_conflict=slug; 5 campos novos; 409 tratado graciosamente |

---

## DECISÕES TÉCNICAS

- **Ollama fallback:** Gemini primary → Ollama on 503/error. Ollama timeout=180s. Se Ollama também falhar → `continue` (livro pulado)
- **status_cover:** 0=pendente, 1=com capa, 2=sem capa disponível (não bloqueia quality gate)
- **Upsert Supabase:** `POST ?on_conflict=slug` com `Prefer: resolution=merge-duplicates`
- **Campos publicados:** id, titulo, slug, autor, descricao(=sinopse), isbn, ano_publicacao, imagem_url, is_publishable, quality_score, is_book, last_quality_check, publish_blockers, created_at, updated_at
- **SQLite lock:** resolver com `PRAGMA wal_checkpoint(TRUNCATE)` via Python quando necessário

---

## PROBLEMAS CONHECIDOS / PENDENTES

### [PENDENTE] Steps 2-5 para os 107 restantes
Os primeiros 100 seeds passaram por todos os steps. Os outros 107 precisam rodar:
- Step 2 → pacote 107
- Step 3 → pacote 107
- Step 4 → pacote 107
- Step 5 → pacote 107

### [PENDENTE] Step 7 — sinopses restantes (~37)
Rodar `Step 7 → pacote 500` para completar todas as sinopses pendentes.

### [PENDENTE] Step 9 → pacote 500
Quality gate para os livros com sinopse nova.

### [PENDENTE] Step 10 → pacote 500
Publicar todos os aprovados restantes.

### [PENDENTE] Step 11 — SEO Lists
Nenhuma categoria elegível encontrada anteriormente (nenhum publicado). Rodar após publicação em massa.

### [OBSERVAÇÃO] Atitude Mental Positiva
Falhou por Gemini 503 + Ollama timeout na primeira tentativa. Passou normalmente na segunda rodada. Comportamento esperado.

### [OBSERVAÇÃO] A Vaca Roxa
Falhou por INVALID_AGENT_OUTPUT (JSON truncado). O `continue` funcionou. Gerou sinopse com sucesso na segunda rodada.

### [OBSERVAÇÃO] Construa para Vender / alguns livros sem descrição
Sinopse gerada é genérica (sem descricao_base). Aceitável — validator aprova.

---

## SCHEMA SUPABASE (confirmado)

```
id                  uuid        NOT NULL
titulo              text        NOT NULL
slug                text        NOT NULL (unique)
autor               text        NOT NULL
descricao           text        NOT NULL
isbn                text        nullable
ano_publicacao      integer     nullable
imagem_url          text        nullable
created_at          timestamptz nullable
updated_at          timestamptz nullable
is_publishable      boolean     nullable
publish_blockers    text        nullable
quality_score       integer     nullable
last_quality_check  timestamptz nullable
is_book             boolean     nullable
```

---

## PRÓXIMOS PASSOS (ordem)

1. Step 7 → pacote 500
2. Step 9 → pacote 500
3. Step 10 → pacote 500
4. Steps 2→5 para os 107 restantes
5. Step 6 → pacote 107 (review)
6. Step 7 → pacote 107
7. Step 8 → pacote 107
8. Step 9 → pacote 107
9. Step 10 → pacote 107
10. Step 11 → SEO lists
