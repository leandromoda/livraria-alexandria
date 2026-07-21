---
description: Analisa TODA a fila de logs do pipeline em lote — inventário + triagem + autorização única, depois diagnóstico e correção
---

# Análise + correção de logs do pipeline (modo lote)

Executa **integralmente no Claude Code**. **Uma invocação processa a fila inteira**:
inventaria todos os logs pendentes, triagem automática, pede autorização **uma única
vez** e então executa tudo.

> **Não é mais "1 log por invocação".** Peça autorização de forma agregada, no
> Passo 1, e depois **não volte a perguntar** item a item.

A lógica de parsing e o schema do relatório vivem **apenas** em
`agents/log_analysis_batch/prompt.md` — este comando orquestra o lote.

---

## Passo 0 — Inventário + triagem (UMA chamada)

Rode **um único script** que lista todos os `scripts/data/logs/pipeline_*.log`
pendentes e classifica cada um. Qualquer arquivo em `logs/` é, por definição, não
processado (ao processar, ele vai para `log_analysis/processed_logs/`).

Para cada log, colete: tamanho, nº de linhas, faixa de horário e sinais:

- **hard**: `Traceback (most recent call last)`, `Exception`, `ERRO`, `ERROR`
- **soft**: `FALHA`, `Falhas: [1-9]`, `Bloqueados: [1-9]`, `Reprovad`

Classifique:

| Classe | Critério | Tratamento |
|---|---|---|
| `VAZIO` | 0 bytes | report `empty_log`, varrer em lote |
| `TRIVIAL` | < 250 KB **e** sem sinal hard/soft | report mínimo, varrer em lote |
| `REVISAR` | < 250 KB **com** sinal hard ou soft | **ler inteiro** e classificar individualmente antes de varrer |
| `SUBSTANCIAL` | ≥ 250 KB | análise individual completa (Etapas 1 e 2) |

> ⚠️ **Nunca varra um fragmento sem checar sinal de erro.** Um log pequeno pode
> conter um traceback real — é exatamente o que o comando existe para achar.

Se não houver logs → responda "Nenhum log para processar." e **pare**.

---

## Passo 1 — Plano + autorização única

Apresente ao usuário, **de uma vez só**:

1. A tabela do inventário (nome, tamanho, classe, sinais encontrados).
2. O que será feito com cada classe.
3. A lista completa das operações que serão executadas:
   - ler os logs (`scripts/data/logs/*.log`),
   - escrever os reports (`scripts/data/log_analysis/log_analysis_*.json`),
   - mover `.log` **e** `.json` para `scripts/data/log_analysis/processed_logs/`,
   - editar código em `scripts/**` **apenas** se houver correção real a aplicar.

Peça **uma autorização** cobrindo todo o lote e siga sem novas perguntas. Só volte
a consultar o usuário se aparecer uma decisão de design real (ex.: escolher entre
duas estratégias de correção com impacto diferente).

---

## Passo 2 — Execução

### 2a. Varredura em lote (`VAZIO` + `TRIVIAL` + os `REVISAR` já triados)

Um único script gera o report mínimo de cada um e arquiva `.log` + `.json`.
Cada log continua tendo **seu próprio** `log_analysis_TIMESTAMP.json` (marque
`meta.batch_swept: true`).

### 2b. Análise individual (`SUBSTANCIAL`)

Para cada log, na ordem do mais antigo para o mais novo:

**Etapa 1 — Diagnóstico (NÃO edita código)**
1. Gere o relatório em `scripts/data/log_analysis/log_analysis_TIMESTAMP.json` (PASSO A).
2. Verifique que o JSON existe e é válido (PASSO B).
3. Mova o `.log` fonte para `processed_logs/` (PASSO C) — só após o PASSO B.

> Nesta etapa você é **só analista**: não edite `.py` nem arquivos de dados.
> Toda correção é apenas *descrita* em `failures` / `actionable_insights`.

**Etapa 2 — Correção**
1. Leia o relatório da Etapa 1.
2. Para cada `actionable_insights` (`critical` → `high` → `medium` → `low`) e cada
   `failure` / `exception`: abra o `source_file` indicado e aplique a `suggested_fix`
   em `scripts/...` (e nos `affected_data_files`, se listados).
3. **Não** gere correção para `rejections` nem para insights sem ação real. Registre
   que foram avaliados e dispensados — **não invente fix**.
4. **Só depois de aplicar as correções**, mova o `.json` para `processed_logs/`.

---

## Gotchas de execução (medidos)

- **Logs gigantes** (já houve de 40 MB / 220 k linhas): **nunca** use `Read` no
  arquivo inteiro — ele estoura. Parseie programaticamente (script Python) e leia
  só os trechos relevantes.
- **`python` não resolve na ferramenta Bash** desta máquina (`command not found`
  intermitente). Use a ferramenta **PowerShell** para rodar Python, ou scripts
  salvos no scratchpad.
- **Encoding**: o console é cp1252 e quebra com `→`/emoji dos logs. No topo de todo
  script: `sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')` e
  leia os logs com `errors='replace'`.
- **Pipeline de jogos**: linhas `JOGOS_*` são do pipeline paralelo. Falhas de
  `JOGOS_SCRAPE` são **esperadas** (bot walls Amazon 503 / ML) — o fallback é o
  finder LLM, por design. Não gere fix.

## Comportamento esperado — sempre dispensar (não é bug)

- `REPROVADO` no Quality Gate por "Sinopse pendente" → teto da quota LLM.
- `limite de sessão atingido` (LLM_ORCH) → quota da assinatura PRO; o loop
  multijanela já trata.
- `[BLACKLIST][WARN] Slug não encontrado no SQLite … pulando` → skip defensivo.
- Auditoria "publicados sem categoria temática" → depende do step LLM 9.

---

## Regras de movimentação (ponto crítico)

- O **`.log`** só sai de `logs/` **depois** que o JSON existe.
- O **`.json`** só sai da raiz de `log_analysis/` **depois** das correções aplicadas.
- Destino de ambos: `scripts/data/log_analysis/processed_logs/`.
- **Nunca** grave o JSON direto em `processed_logs/` — ele nasce na raiz.

---

## Encerramento

Reporte de forma sucinta e agregada:

- **Fila**: quantos logs processados, por classe (vazios / triviais / substanciais).
- **Por log substancial**: falhas / rejeições / insights.
- **Correções**: arquivos de código corrigidos — ou "nenhuma correção necessária".
- **Dispensados**: o que foi avaliado e descartado (e por quê), em uma linha.
- Confirmação de que **todos** os `.log` e `.json` foram para `processed_logs/`.
