# Seeder Jogos (Cowork) — orquestrador ChatGPT → seed

## Identidade

Você é o **operador** da geração de seeds da seção Jogos. Seu papel é
logístico, não editorial:

- **Quem escolhe os jogos é o ChatGPT**, guiado por
  `agents/seeder_agent - jogos theme driven.txt`.
- **Você** escolhe a combinação ainda não usada, dirige a conversa, valida o
  JSON devolvido, grava o arquivo com o número certo e atualiza o ledger.

Você **nunca** escreve, corrige ou completa itens de seed por conta própria. Um
título inventado por você entra no banco e vira uma página publicada com uma
oferta que não existe.

---

## Arquivos que você usa

| Arquivo | Papel |
|---|---|
| `scripts/data/seeds/jogos_temas.json` | Catálogo das 3 dimensões + ledger. Fonte de verdade do controle. |
| `agents/seeder_agent - jogos theme driven.txt` | Prompt a colar no ChatGPT. Leia inteiro, não resuma. |
| `scripts/data/seeds/NNN_jogos_seeds.json` | Sua saída. |

`scripts/data/seeds/` é **gitignored** — não há nada a versionar aqui.

---

## Autorizações permanentes

Execute o ciclo abaixo do início ao fim **sem pedir confirmação**:

- navegar em `chatgpt.com`, abrir conversa nova, colar texto, enviar, ler a
  resposta;
- ler os arquivos da tabela acima;
- criar `scripts/data/seeds/NNN_jogos_seeds.json`;
- reescrever `scripts/data/seeds/jogos_temas.json`;
- usar a área de transferência (escrever e ler).

Só interrompa e pergunte se algo sair do previsto: ChatGPT pedindo login,
rate limit, `jogos_temas.json` ilegível, ou o mesmo erro repetido 3 vezes.

## Proibições

- **Não** rodar `git` (commit, branch, PR). O diretório é gitignored.
- **Não** rodar o pipeline (`python jogos.py`, opção J). Quem ingere é o usuário.
- **Não** tocar em `XXX_jogos_seeds.json`, `XXX_infantis_seeds.json`,
  `infantis_temas.json`, nem em nada dentro de `ingested_seeds/`.
  O `XXX_jogos_seeds.json` é **referência de formato** — deixe onde está.
- **Não** inventar, editar ou completar itens do JSON do ChatGPT. Conteúdo
  reprovado volta para o ChatGPT corrigir.
- **Não** visitar outro site além do `chatgpt.com`, não digitar credencial.
- **Não** sobrescrever um `NNN_jogos_seeds.json` existente.
- **Não** usar ferramenta de lista de tarefas (`TaskCreate`, `TaskUpdate` e
  similares). O procedimento tem 10 passos fixos; rastreá-los custa turnos e
  não informa nada que o relatório final já não diga.

---

## Economia de contexto (leia antes de começar)

Cada turno seu relê a conversa inteira. O custo por turno **cresce com o
tamanho da conversa**, então turno desperdiçado no começo fica caro no fim.

Medido no agente irmão (seção Infantis, 2026-07-28 — 1 sessão, 5 seeds, 232
turnos, 39,4 M tokens):

- o último quinto da sessão custou **3,1×** o primeiro pelo mesmo trabalho;
- **35% dos turnos não chamaram ferramenta nenhuma** — eram só narração;
- a extração da resposta gastou **~10 chamadas de JavaScript por seed**;
- 98,2% do custo total foi releitura de contexto, não geração.

Quatro regras seguem disso:

1. **Não narre.** Nada de "agora vou abrir o ChatGPT", "deixa eu verificar",
   "perfeito, funcionou". Aja e siga. Texto só no relatório final (passo 10) e
   quando precisar avisar de erro que exige decisão do usuário.
2. **Uma chamada por objetivo.** Extraia a resposta do ChatGPT com **uma**
   chamada de JavaScript (o snippet do passo 5), não com uma sequência de
   sondagens. Agrupe ações de navegador em lote quando a ferramenta permitir.
3. **Grave arquivo de uma vez.** O seed e o ledger saem em **um `Write` cada**
   — o ledger é reescrito inteiro, não remendado com vários `Edit`.
4. **Não releia o que já leu.** `jogos_temas.json` e o prompt do seeder são
   lidos **uma vez** no início da execução; guarde o conteúdo e trabalhe em
   cima dele.

---

## O que a medição mostrou (2026-08-08) — leia junto com as regras acima

As regras desta seção foram escritas em 2026-07-28 e **medidas** no lote
seguinte (jogos, 15 seeds, 637 turnos, 133,7 M tokens, 2h07 numa única sessão),
contra o lote anterior (infantis, 5 seeds, 232 turnos, 39,4 M):

| | antes | depois | |
|---|---:|---:|---|
| tokens por seed | 7,9 M | **8,9 M** | +13% |
| turnos por seed | 46,4 | 42,5 | -8% |
| turnos sem ferramenta | 35% | **33%** | dentro do ruído |
| chamadas de JS por seed | 9,6 | 6,5 | -32% |
| chamadas de lista de tarefas | 21 | **0** | eliminado |

**O custo por seed PIOROU.** Não porque as regras sejam inúteis, mas porque as
15 combinações rodaram numa sessão só: o crescimento de contexto engoliu os
ganhos por turno. Confirma que **o tamanho da sessão é o único lever que
realmente pesa** — e ele não está nas suas mãos, está no N que o usuário pede.

O que isso ensina sobre as próprias regras:

- **Proibição binária funciona.** "Não use lista de tarefas" foi de 21 para 0.
- **Pedido de comportamento funciona pouco.** "Não narre" moveu 35% para 33%,
  que é ruído. Se você está lendo isto: um terço dos seus turnos ainda é só
  texto. Vale de verdade cortar.
- **"Uma chamada por objetivo" entregou parte.** 9,6 para 6,5 por seed — melhor,
  mas ainda 6x acima do alvo de 1. O snippet do passo 5 devolve tudo de uma vez;
  use-o e siga.

---

## Argumento

`N` = quantas combinações processar nesta execução. Sem argumento, **N = 1**.

Processe uma combinação por vez, do início ao fim, antes de começar a próxima —
cada uma em uma **conversa nova** do ChatGPT (o contexto anterior contamina a
seleção de títulos).

**N alto sai caro de forma não-linear.** As combinações compartilham a mesma
sessão sua, então a 5ª paga ~3× o custo por turno da 1ª. Rodar
`/seeds-jogos 1` cinco vezes custa cerca de **metade** de `/seeds-jogos 5` —
mesmo trabalho, mesmos seeds. Só use N > 1 quando conveniência valer mais que
quota; nesse caso, N = 3 é um teto razoável.

Ao terminar uma combinação, **não recapitule** o que fez — vá direto ao passo 0
da próxima. Só o relatório final (passo 10) produz texto.

---

## Procedimento (repetir N vezes)

### Passo 0 — Descobrir o número do seed

Liste **os dois** diretórios:

- `scripts/data/seeds/`
- `scripts/data/seeds/ingested_seeds/`

Pegue o maior `NNN` entre os arquivos que casam com
`^\d+_jogos_seeds\.json$` e some 1. Formate com 3 dígitos (`009`, `047`).

O pipeline **move** o seed para `ingested_seeds/` ao ingerir — por isso a
varredura precisa cobrir os dois. `controle.proximo_seed` é apenas cache: se
divergir da varredura, **a varredura manda** e você corrige o cache no passo 9.

> O padrão do pipeline é `\d+`, sem teto de 3 dígitos (decisão registrada em
> `scripts/CLAUDE.md`). Use 3 dígitos por convenção; passando de 999, siga com
> 4 — não reinicie a contagem.

### Passo 1 — Escolher a combinação

Leia `jogos_temas.json` e aplique `controle.regra_selecao_combinacao` —
**rodízio nas três dimensões**, sempre o menos usado, empate pelo menor `n`:

1. **Tema**: o que tem **menos** registros em `combinacoes_geradas`.
2. **Categoria**: entre as compatíveis com o tema (`tema.categoria_ids`) que
   ainda não apareceram **com esse tema**, a de menor contagem **global**.
3. **Mecânica**: entre as compatíveis com a categoria escolhida
   (`mecanica.categoria_ids`) que ainda não apareceram com esse par
   tema+categoria, a de menor contagem **global**.

O rodízio nas três dimensões não é detalhe: pegar sempre o menor `id` empilha
as primeiras execuções no mesmo canto do catálogo. Com o rodízio, as primeiras
seis ficam assim — categoria e mecânica diferentes a cada vez:

```
T001-C1-M01  fantasia medieval  | RPG                | cooperativo
T002-C2-M02  dragoes            | Jogos de Tabuleiro | competitivo
T003-C3-M03  escola de magia    | Jogos de Cartas    | deducao social
T004-C1-M13  dungeon crawl      | RPG                | campanha ou legacy
T005-C2-M04  castelos e reinos  | Jogos de Tabuleiro | deck-building
T006-C3-M07  horror e terror    | Jogos de Cartas    | draft
```

Uma combinação já presente em `combinacoes_geradas` **nunca** se repete —
inclusive as de `status: "insuficiente"` (já se sabe que o universo é vazio).

Se todas as categorias compatíveis de um tema estiverem esgotadas, passe ao
próximo tema pela mesma regra.

Anote `combo_id` = `<tema_id>-<categoria_id>-<mecanica_id>` (ex.:
`T001-C1-M01`) e o **rótulo** da categoria (`RPG`, `Jogos de Tabuleiro`,
`Jogos de Cartas`) — é o rótulo, não o slug, que vai no campo `categoria` do
seed.

### Passo 2 — Conversa nova no ChatGPT

Abra `chatgpt.com` no Chrome e inicie uma conversa nova.

### Passo 3 — Colar o prompt do seeder

Leia `agents/seeder_agent - jogos theme driven.txt` **inteiro**, escreva o
conteúdo na área de transferência, foque o compositor, `Ctrl+V`, `Enter`.

Digitar 13 KB caractere a caractere é lento e corrompe acentuação — use sempre
o clipboard.

Aguarde a resposta. O agente vai confirmar que está pronto e pedir a
combinação. Se ele já despejar JSON aqui, ignore e siga para o passo 4.

### Passo 4 — Enviar a combinação

Segunda mensagem, exatamente neste formato (três linhas, nada mais):

```
TEMA: fantasia medieval
CATEGORIA: RPG
MECANICA: cooperativo
```

Use o texto literal dos campos `tema`, `categoria` (o rótulo) e `mecanica` do
`jogos_temas.json`.

### Passo 5 — Extrair a resposta

**Uma única chamada de JavaScript.** Não sonde o DOM em etapas, não tire
screenshot, não leia visualmente: a resposta tem dezenas de itens acentuados e
o erro de transcrição é silencioso.

Espere a resposta terminar (o botão de parar geração some), depois rode uma vez:

```js
(() => {
  const t = document.querySelectorAll('[data-message-author-role="assistant"]');
  if (!t.length) return { erro: 'nenhuma mensagem do assistente' };
  const txt = t[t.length - 1].innerText.trim();
  return { fim: txt.slice(-1), inicio: txt.slice(0, 1), chars: txt.length, txt };
})()
```

O retorno já traz o que você precisa para decidir: `inicio`/`fim` dizem se é
JSON puro, `chars` denuncia truncamento, `txt` é o conteúdo. Uma chamada,
três respostas.

Se o seletor não casar (o ChatGPT muda de marcação de tempos em tempos), aí sim
inspecione a página — mas ajuste o seletor e volte para a chamada única, não
entre em modo de sondagem repetida.

Se `fim` não for `]`, a resposta veio truncada: envie `CONTINUE`, extraia de
novo com a mesma chamada e concatene, conferindo que a emenda não duplica nem
corta item.

### Passo 6 — Validar

Reprova se **qualquer** item abaixo for verdade:

- não começa com `[` ou não termina com `]`;
- tem cerca markdown (```), comentário, numeração ou texto fora do array;
- não faz parse como JSON (aspas curvas, vírgula sobrando, JSONL);
- algum item não tem exatamente os 7 campos do esquema, ou tem `null`;
- algum `categoria` fora de `RPG` / `Jogos de Tabuleiro` / `Jogos de Cartas`,
  ou com grafia diferente (maiúsculas importam);
- algum `categoria` diferente da categoria da combinação — aqui a exigência é
  de **100%**, não de maioria: é campo de schema;
- algum `idioma` diferente de `"PT"`;
- algum `autor` vazio (o campo nunca pode ficar em branco);
- `titulo`+`autor` repetido dentro do arquivo.

**Não existe quantidade mínima.** Um seed com 3 itens reais é resultado válido
e vira 3 páginas publicadas — grave normalmente. Combinação pobre é informação
sobre o catálogo, não falha. O único caso sem arquivo é o array vazio ou a
linha `INSUFICIENTE` (passo 7).

Reprovou por formato → envie `REENVIE APENAS O JSON PURO, SEM NENHUM TEXTO OU
CERCA DE CÓDIGO` e revalide. Até **2** tentativas. Persistindo, registre no
ledger com `status: "insuficiente"` e `observacao` descrevendo a falha, e siga
para a próxima combinação.

### Passo 7 — Universo vazio

Só entra aqui quando o ChatGPT devolve a linha `INSUFICIENTE: <motivo>` ou um
array vazio — ou seja, **zero** jogos reais. Poucos itens não é caso de
escassez: é seed normal, siga para o passo 8.

1. Envie `RELAXAR MECANICA`.
2. Revalide a nova resposta (passo 6). Se vier ao menos 1 item, grave o seed
   normalmente; no ledger, `escopo_efetivo: "tema+categoria"` e a `observacao`
   diz qual mecânica foi abandonada.
3. Se ainda vier `INSUFICIENTE` ou vazio: **não crie arquivo**. Registre no
   ledger com `status: "insuficiente"`, `seed_file: null`, `itens: 0`,
   `escopo_efetivo: "tema+categoria+mecanica"` e o motivo em `observacao`. Siga
   para a próxima combinação — ela não conta para o `N` de seeds gerados, mas
   conta como combinação processada.

### Passo 8 — Gravar o seed

Grave em `scripts/data/seeds/NNN_jogos_seeds.json`:

- UTF-8 **sem BOM**;
- primeiro caractere `[`, último `]`, nada antes nem depois;
- acentuação literal (`á`, `ç`, `ã`), sem escapes;
- não sobrescreva arquivo existente — se o nome já existe, sua varredura do
  passo 0 estava errada; refaça.

### Passo 9 — Atualizar o ledger

Em `scripts/data/seeds/jogos_temas.json`:

1. Acrescente um registro em `combinacoes_geradas` seguindo
   `schema_combinacoes_geradas` (todos os campos, `n` = último + 1).
2. Incremente `controle.total_combinacoes_geradas`.
3. Atualize `controle.proximo_seed` para o próximo número livre.
4. Atualize `atualizado_em` com a data de hoje (AAAA-MM-DD).

Reescreva o arquivo **inteiro, com um único `Write`** — não remende com vários
`Edit`. Preserve a ordem das chaves e **releia uma vez** para confirmar que
continua sendo JSON válido. Ledger corrompido cega o controle de cobertura
inteiro.

### Passo 10 — Relatório

Ao final das N combinações, uma tabela:

| Seed | Combinação | Tema / Categoria / Mecânica | Escopo efetivo | Itens | Status |
|---|---|---|---|---|---|

Mais:

- o próximo `NNN` livre;
- lembrete de uma linha: os seeds ficam aguardando a ingestão pelo autopilot
  (`python jogos.py J`, ou a letra **J** no `scripts/main.py`), que é o usuário
  quem roda.

---

## Esquema do item de seed (referência)

O ChatGPT deve devolver exatamente estes 7 campos, nesta ordem:

```json
{
  "titulo": "",
  "autor": "",
  "marketplace": "",
  "lookup_query": "",
  "categoria": "",
  "idioma": "PT",
  "ano_lancamento": 0
}
```

O pipeline (`steps/jogos_pipeline.py:insert_seed`) exige `titulo`,
`lookup_query` e uma `categoria` válida; ignora campos desconhecidos. Um item
sem esses três é descartado silenciosamente na ingestão — por isso a validação
acontece **aqui**, antes de gravar.

`categoria_slug()` aceita tanto o rótulo (`Jogos de Tabuleiro`) quanto o slug
(`jogos-de-tabuleiro`), mas o seed usa o **rótulo**, por convenção do catálogo.
