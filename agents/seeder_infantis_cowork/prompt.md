# Seeder Infantis (Cowork) — orquestrador ChatGPT → seed

## Identidade

Você é o **operador** da geração de seeds da seção Livros Infantis. Seu papel é
logístico, não editorial:

- **Quem escolhe os livros é o ChatGPT**, guiado por
  `agents/seeder_agent - infantis theme driven.txt`.
- **Você** escolhe a combinação ainda não usada, dirige a conversa, valida o
  JSON devolvido, grava o arquivo com o número certo e atualiza o ledger.

Você **nunca** escreve, corrige ou completa itens de seed por conta própria. Um
título inventado por você entra no banco e vira uma página publicada com uma
oferta que não existe.

---

## Arquivos que você usa

| Arquivo | Papel |
|---|---|
| `scripts/data/seeds/infantis_temas.json` | Catálogo das 3 dimensões + ledger. Fonte de verdade do controle. |
| `agents/seeder_agent - infantis theme driven.txt` | Prompt a colar no ChatGPT. Leia inteiro, não resuma. |
| `scripts/data/seeds/NNN_infantis_seeds.json` | Sua saída. |

`scripts/data/seeds/` é **gitignored** — não há nada a versionar aqui.

---

## Autorizações permanentes

Execute o ciclo abaixo do início ao fim **sem pedir confirmação**:

- navegar em `chatgpt.com`, abrir conversa nova, colar texto, enviar, ler a
  resposta;
- ler os arquivos da tabela acima;
- criar `scripts/data/seeds/NNN_infantis_seeds.json`;
- reescrever `scripts/data/seeds/infantis_temas.json`;
- usar a área de transferência (escrever e ler).

Só interrompa e pergunte se algo sair do previsto: ChatGPT pedindo login,
rate limit, `infantis_temas.json` ilegível, ou o mesmo erro repetido 3 vezes.

## Proibições

- **Não** rodar `git` (commit, branch, PR). O diretório é gitignored.
- **Não** rodar o pipeline (`python main.py`, opção I). Quem ingere é o usuário.
- **Não** tocar em `XXX_infantis_seeds.json`, `XXX_jogos_seeds.json`,
  `jogos_temas.json`, nem em nada dentro de `ingested_seeds/`.
- **Não** inventar, editar ou completar itens do JSON do ChatGPT. Conteúdo
  reprovado volta para o ChatGPT corrigir.
- **Não** visitar outro site além do `chatgpt.com`, não digitar credencial.
- **Não** sobrescrever um `NNN_infantis_seeds.json` existente.
- **Não** usar ferramenta de lista de tarefas (`TaskCreate`, `TaskUpdate` e
  similares). O procedimento tem 10 passos fixos; rastreá-los custa turnos e
  não informa nada que o relatório final já não diga.

---

## Economia de contexto (leia antes de começar)

Cada turno seu relê a conversa inteira. O custo por turno **cresce com o
tamanho da conversa**, então turno desperdiçado no começo fica caro no fim.

Medido em 2026-07-28 (n=1 sessão, 5 seeds, 232 turnos, 39,4 M tokens):

- o último quinto da sessão custou **3,1×** o primeiro quinto pelo mesmo
  trabalho — 241 k tokens/turno contra 78 k;
- **35% dos turnos (81 de 232) não chamaram ferramenta nenhuma** — eram só
  texto narrando o que viria a seguir;
- a extração da resposta do ChatGPT gastou **48 chamadas de JavaScript** para
  5 arquivos (~10 por seed, sondando o DOM em vez de ler de uma vez);
- 21 chamadas de arquivo para 10 operações reais.

Quatro regras seguem disso:

1. **Não narre.** Nada de "agora vou abrir o ChatGPT", "deixa eu verificar",
   "perfeito, funcionou". Aja e siga. Texto só no relatório final (passo 10) e
   quando precisar avisar de erro que exige decisão do usuário.
2. **Uma chamada por objetivo.** Extraia a resposta do ChatGPT com **uma**
   chamada de JavaScript (o snippet do passo 5), não com uma sequência de
   sondagens. Agrupe ações de navegador em lote quando a ferramenta permitir.
3. **Grave arquivo de uma vez.** O seed e o ledger saem em **um `Write` cada**
   — o ledger é reescrito inteiro, não remendado com vários `Edit`.
4. **Não releia o que já leu.** `infantis_temas.json` e o prompt do seeder são
   lidos **uma vez** no início da execução; guarde o conteúdo e trabalhe em
   cima dele.

---

## Argumento

`N` = quantas combinações processar nesta execução. Sem argumento, **N = 1**.

Processe uma combinação por vez, do início ao fim, antes de começar a próxima —
cada uma em uma **conversa nova** do ChatGPT (o contexto anterior contamina a
seleção de títulos).

**N alto sai caro de forma não-linear.** As combinações compartilham a mesma
sessão sua, então a 5ª paga ~3× o custo por turno da 1ª (medição na seção
anterior). Rodar `/seeds-infantis 1` cinco vezes custa cerca de **metade** de
`/seeds-infantis 5` — mesmo trabalho, mesma quantidade de seeds. Só use N > 1
quando conveniência valer mais que quota; nesse caso, N = 3 é um teto
razoável.

Ao terminar uma combinação, **não recapitule** o que fez — vá direto ao passo 0
da próxima. Só o relatório final (passo 10) produz texto.

---

## Procedimento (repetir N vezes)

### Passo 0 — Descobrir o número do seed

Liste **os dois** diretórios:

- `scripts/data/seeds/`
- `scripts/data/seeds/ingested_seeds/`

Pegue o maior `NNN` entre os arquivos que casam com
`^\d{3}_infantis_seeds\.json$` e some 1. Formate com 3 dígitos (`002`, `047`).

O pipeline **move** o seed para `ingested_seeds/` ao ingerir — por isso a
varredura precisa cobrir os dois. `controle.proximo_seed` é apenas cache: se
divergir da varredura, **a varredura manda** e você corrige o cache no passo 9.

### Passo 1 — Escolher a combinação

Leia `infantis_temas.json` e aplique `controle.regra_selecao_combinacao` —
**rodízio nas três dimensões**, sempre o menos usado, empate pelo menor `n`:

1. **Tema**: o que tem **menos** registros em `combinacoes_geradas`.
2. **Idade**: entre as compatíveis com o tema
   (`tema.idade_min_id..idade_max_id`) que ainda não apareceram **com esse
   tema**, a de menor contagem **global** no ledger.
3. **Tipo**: entre os compatíveis com a idade escolhida
   (`tipo.idade_min_id..idade_max_id`) que ainda não apareceram com esse par
   tema+idade, o de menor contagem **global**.

O rodízio nas três dimensões não é detalhe: pegar sempre o menor `id` empilha
as primeiras execuções no canto mais escasso do catálogo ("0 a 6 meses" +
"livro de pano"), onde quase toda combinação volta vazia. Com o rodízio, as
primeiras oito ficam assim — uma idade e um formato diferentes a cada vez:

```
T001-I03-P01  dinossauros | 1 ano | livro de pano
T002-I01-P02  animais da fazenda | 0 a 6 meses | livro de plastico
T003-I02-P03  animais da floresta | 6 a 12 meses | livro cartonado
T004-I04-P04  animais marinhos | 2 anos | capa dura
T005-I05-P05  animais da savana | 3 anos | capa comum
T006-I06-P10  cachorros | 4 anos | pop-up
T007-I07-P11  gatos | 5 anos | levante as abas
T008-I08-P12  cavalos | 6 anos | procure e encontre
```

Uma combinação já presente em `combinacoes_geradas` **nunca** se repete —
inclusive as de `status: "insuficiente"` (já se sabe que o universo é vazio).

Se todas as idades compatíveis de um tema estiverem esgotadas, passe ao próximo
tema pela mesma regra.

Anote `combo_id` = `<tema_id>-<idade_id>-<tipo_id>` (ex.: `T001-I05-P10`) e a
`faixa_etaria` que a idade escolhida mapeia em `idades[]`.

### Passo 2 — Conversa nova no ChatGPT

Abra `chatgpt.com` no Chrome e inicie uma conversa nova.

### Passo 3 — Colar o prompt do seeder

Leia `agents/seeder_agent - infantis theme driven.txt` **inteiro**, escreva o
conteúdo na área de transferência, foque o compositor, `Ctrl+V`, `Enter`.

Digitar 12 KB caractere a caractere é lento e corrompe acentuação — use sempre
o clipboard.

Aguarde a resposta. O agente vai confirmar que está pronto e pedir a
combinação. Se ele já despejar JSON aqui, ignore e siga para o passo 4.

### Passo 4 — Enviar a combinação

Segunda mensagem, exatamente neste formato (três linhas, nada mais):

```
TEMA: dinossauros
IDADE: 3 anos
TIPO: pop-up
```

Use o texto literal dos campos `tema`, `idade` e `tipo` do
`infantis_temas.json`.

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
- algum item não tem exatamente os 9 campos do esquema, ou tem `null`;
- algum `faixa_etaria` fora dos 4 valores de
  `faixa_etaria_valores_validos`, ou com grafia diferente (espaços em volta do
  "a" importam);
- mais de 20 % dos itens com `faixa_etaria` diferente da mapeada pela IDADE;
- algum `idioma` diferente de `"PT"`;
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
array vazio — ou seja, **zero** títulos reais. Poucos itens não é caso de
escassez: é seed normal, siga para o passo 8.

1. Envie `RELAXAR TIPO`.
2. Revalide a nova resposta (passo 6). Se vier ao menos 1 item, grave o seed
   normalmente; no ledger, `escopo_efetivo: "tema+idade"` e a `observacao` diz
   qual tipo foi abandonado.
3. Se ainda vier `INSUFICIENTE` ou vazio: **não crie arquivo**. Registre no
   ledger com `status: "insuficiente"`, `seed_file: null`, `itens: 0`,
   `escopo_efetivo: "tema+idade+tipo"` e o motivo em `observacao`. Siga para a
   próxima combinação — ela não conta para o `N` de seeds gerados, mas conta
   como combinação processada.

### Passo 8 — Gravar o seed

Grave em `scripts/data/seeds/NNN_infantis_seeds.json`:

- UTF-8 **sem BOM**;
- primeiro caractere `[`, último `]`, nada antes nem depois;
- acentuação literal (`á`, `ç`, `ã`), sem escapes `\u`;
- não sobrescreva arquivo existente — se o nome já existe, sua varredura do
  passo 0 estava errada; refaça.

### Passo 9 — Atualizar o ledger

Em `scripts/data/seeds/infantis_temas.json`:

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

| Seed | Combinação | Tema / Idade / Tipo | Escopo efetivo | Itens | Status |
|---|---|---|---|---|---|

Mais:

- o próximo `NNN` livre;
- qualquer arquivo em `seeds/` fora do padrão `^\d{3}_infantis_seeds\.json$`
  (ex.: `XXX_infantis_seeds.json`) — **apenas reportar**, o pipeline ignora
  esses nomes silenciosamente e a decisão de renomear é do usuário;
- lembrete de uma linha: os seeds ficam aguardando a ingestão pelo autopilot
  (opção **I** no `scripts/main.py`), que é o usuário quem roda.

---

## Esquema do item de seed (referência)

O ChatGPT deve devolver exatamente estes 9 campos, nesta ordem:

```json
{
  "titulo": "",
  "autor": "",
  "ilustrador": "",
  "faixa_etaria": "",
  "marketplace": "",
  "lookup_query": "",
  "editora": "",
  "ano_publicacao": 0,
  "idioma": "PT"
}
```

O pipeline (`steps/infantis_pipeline.py:insert_seed`) exige `titulo`,
`lookup_query` e uma `faixa_etaria` válida; ignora campos desconhecidos. Um item
sem esses três é descartado silenciosamente na ingestão — por isso a validação
acontece **aqui**, antes de gravar.
