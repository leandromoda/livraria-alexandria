# Audit Fixer — Livraria Alexandria (Claude Code)

## Identidade

Você corrige o site da Livraria Alexandria a partir dos **relatórios de auditoria**
gerados pelo `auditor.py` (steps 18/19 e modos QA). Cada relatório é um JSON em
`scripts/data/logs/NNNN_audit_MODE.json` que **já vem estruturado** — não há log de
texto para parsear. Seu trabalho é **ler um relatório, implementar as correções
reais** e **arquivar o relatório processado**.

> **1 relatório por invocação.** Sempre o de menor `NNNN` (o mais antigo).
> Rode `/audit` de novo para o próximo.

A execução tem **duas etapas estritamente separadas**:
**Etapa 1 = diagnóstico (só leitura, NÃO edita código)** ·
**Etapa 2 = correção + arquivamento**.

---

## Input — localizar e selecionar o relatório

Execute **este único comando** — detecta a raiz do repo a partir de qualquer CWD e
lista os relatórios de auditoria ainda não processados:

```bash
python -c "
from pathlib import Path
import sys

def find_repo_root():
    for p in [Path.cwd()] + list(Path.cwd().parents):
        if (p / 'scripts' / 'main.py').exists():
            return p
    return None

repo = find_repo_root()
if not repo:
    print('REPO_NAO_ENCONTRADO', file=sys.stderr); sys.exit(1)

logs_dir = repo / 'scripts' / 'data' / 'logs'
files = sorted(logs_dir.glob('[0-9][0-9][0-9][0-9]_audit_*.json')) if logs_dir.exists() else []
if files:
    print(f'REPO_ROOT={repo}')
    for f in files:
        print(f)
else:
    print('SEM_RELATORIOS')
"
```

**Regra crítica:** qualquer arquivo em `scripts/data/logs/` ainda **não foi
processado**. Ao processar, ele é movido para
`scripts/data/log_analysis/processed_logs/` e some daqui. Não infira o status por
outros meios.

- Se imprimir `SEM_RELATORIOS` → responda "Nenhum relatório de auditoria para
  processar." e **pare** (não há Etapa 2).
- Caso contrário: selecione o **primeiro da lista** (menor `NNNN` = mais antigo),
  leia-o **por completo** com a ferramenta Read usando o **caminho absoluto**.
  Anote o nome do arquivo — será o que você moverá no fim.

---

## Etapa 1 — Diagnóstico (apenas leitura; NÃO edita nada)

Identifique o `mode` no topo do JSON e classifique cada falha. **Nesta etapa você é
só analista**: não edite nenhum `.py`, `.tsx` nem dado. Apenas diagnostique e,
para cada falha, decida se é **correção real** (bug de código/dado a aplicar na
Etapa 2) ou **lacuna operacional** (precisa rodar um step do pipeline — fora de
escopo, apenas registrar).

### Referência por modo de auditoria

| `mode` | O que é falha | Onde investigar | Natureza da correção |
|--------|---------------|-----------------|----------------------|
| `connectivity` · `supabase_table` | `status_code != 200` (ex.: 401) | A própria checagem em `scripts/steps/auditor.py` (envia `apikey`/`Authorization`?); senão `.env` (`NEXT_PUBLIC_SUPABASE_ANON_KEY`) e `lib/supabase.ts`. **401 sem header de apikey costuma ser falso-positivo da checagem** — corrija a checagem, não invente quebra de infra. | código/config |
| `connectivity` · `site_route` | `status_code` não-2xx | Rota estática em `app/(public)/<rota>/page.tsx` (ou `(internal)` p/ `/admin`) | código |
| `connectivity` · `site_route_livro` | não-200 | `app/(public)/livros/[slug]/page.tsx` + integridade do dado do livro | código/dado |
| `connectivity` · `site_route_autor` | não-200 | `app/(public)/autores/[slug]/page.tsx` + dado do autor | código/dado |
| `connectivity` · `api_click` | fora de `{301,302,307,308}` | `app/(internal)/api/click/[id]/route.ts` | código |
| `connectivity` · `image_url` | não-2xx/3xx (capa morta) | Dado: `livros.imagem_url` quebrado → re-capa (step 11) | operacional/dado |
| `content` | `results[].issues` por livro; `severity`; `action` | Regenerar conteúdo (sinopse/categoria) ou validar despublicação; ver `scripts/steps/synopsis.py`, `categorize.py`, `publish.py` | dado/operacional |
| `author_bio` | `slugs_sem_bio[]` | Gerar bios é **operacional** (step 13). **Mas se `without_bio == total_published` (100% sem bio)**, investigue bug real: `scripts/steps/publish_autores.py` (envia `bio`?) e geração de bio | operacional / código se 100% |
| `title_verify` | `results[]` com títulos suspeitos | Corrigir título/blacklist do dado; ver `scripts/steps/auditor.py` (regras) e `apply_blacklist.py` | dado/operacional |
| `list` | listas `needs_refresh`/0 membros | Re-gerar listas (step 16) é operacional; despublicação já é registrada | operacional |
| `integrity` | `results[]` com `count>0` e `acao_recomendada` | Checks SQL de consistência do pipeline local. A `acao_recomendada` normalmente é "rodar step N" → **operacional**. Só vire correção de código se um check revelar bug (ex.: `status_cover=1` com `imagem_url` vazia em massa → lógica de `covers.py`/`publish.py`) | operacional / código se bug |
| `consistency` | `livros_sem_oferta`, `ofertas_inativas`, `ofertas_sem_url_afiliada`, `sinopses_suspeitas` | `ofertas_sem_url_afiliada` → bug de tag/afiliado em `offer_resolver.py`/`publish_ofertas.py` (**código**). Demais: republicar/regenerar (**operacional**) | dado/código/operacional |
| `prices` | `results[]` com `status` `unavailable`/`error` | `unavailable` → oferta morta: desativar/`reactivation_pending` (operacional). Padrão de `error` (muitos) → revisar `marketplace_scraper.py`/`offer_price_monitor.py` (**código**) | operacional / código se padrão |
| `covers` | `publicados_sem_capa`, `cover_inconsistente`, `capas_mortas[]` | `publicados_sem_capa` (status_cover=2) → re-rodar capas (step 12) é operacional. `cover_inconsistente` (status_cover=1 sem url) → bug de dado/lógica em `covers.py`/`publish.py` (**código**). `capas_mortas` → limpar `imagem_url`/re-capa (dado/operacional) | operacional/dado/código |
| `classification` | `publicados_sem_categoria`, `categorize_inconsistente`, `sem_categoria_primaria` | `publicados_sem_categoria` → re-rodar categorizar (step 9/10) é operacional. `categorize_inconsistente` (status_categorize=1 sem linhas) → bug em `categorize_import.py` (**código**). `sem_categoria_primaria` → faltou `primary_cat` (dado/código) | operacional/dado/código |

Ao final da Etapa 1, apresente um diagnóstico curto: o `mode`, nº de falhas, e a
divisão **correções reais a aplicar** vs **lacunas operacionais** (dispensadas).

---

## Etapa 2 — Correção + arquivamento

1. Para cada falha classificada como **correção real** (priorize as de maior
   severidade / que quebram páginas):
   - Abra o arquivo indicado na tabela.
   - Aplique a correção no código/dado real (`app/...`, `scripts/...`, `lib/...`).
2. **Não** gere correção para falhas **operacionais** (capa pendente, bios a gerar,
   listas a recompor, conteúdo a regenerar) nem para resultados `ok: true`.
   Registre que foram avaliados e dispensados — **não invente fix**.
3. **Somente após ler o relatório e aplicar/avaliar todas as correções**, mova o
   relatório para `processed_logs/` com o comando abaixo (substitua
   `NNNN_audit_MODE.json` pelo nome real):

```bash
python -c "
from pathlib import Path
import shutil

def find_repo_root():
    for p in [Path.cwd()] + list(Path.cwd().parents):
        if (p / 'scripts' / 'main.py').exists():
            return p
    return None

repo = find_repo_root()
if not repo:
    raise RuntimeError('repo root nao encontrado')

src  = repo / 'scripts' / 'data' / 'logs' / 'NNNN_audit_MODE.json'
dest = repo / 'scripts' / 'data' / 'log_analysis' / 'processed_logs'
dest.mkdir(parents=True, exist_ok=True)
if not src.exists():
    raise FileNotFoundError(f'relatorio nao encontrado: {src}')
dest_path = dest / src.name
if dest_path.exists():
    from datetime import datetime, timezone
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    dest_path = dest / f'{src.stem}__{stamp}{src.suffix}'
shutil.move(str(src), str(dest_path))
print(f'Movido: {src.name} -> {dest_path.name}')
"
```

---

## Regras (atenção à movimentação de arquivos)

- **Separação rígida das etapas:** Etapa 1 = diagnóstico **sem editar nada**;
  Etapa 2 = implementação + arquivamento. Não misture.
- **Movimentação — ponto crítico:** o relatório JSON só sai de
  `scripts/data/logs/` **depois** que foi lido e as correções foram aplicadas
  (Etapa 2, passo 3). Destino: `scripts/data/log_analysis/processed_logs/`.
  Mesmo nome; sufixo timestamp `__YYYYMMDDTHHMMSSz` adicionado automaticamente
  se já existir um arquivo homônimo (colisão). Nunca o deixe em `logs/` após processar.
- **Sem redundância:** o relatório de auditoria já é o dado estruturado — **não
  gere outro JSON de análise**. Apenas leia, corrija e mova.
- **1 relatório por invocação.**

---

## Encerramento

Reporte de forma sucinta:
- relatório processado (`NNNN_audit_MODE.json`) e nº de falhas;
- arquivos corrigidos (lista) — ou "nenhuma correção de código necessária";
- lacunas operacionais dispensadas (ex.: "5 capas mortas → re-rodar step 11");
- confirmação de que o relatório foi movido para `processed_logs/`.
