---
description: Gera seeds de livros infantis via ChatGPT — escolhe a combinação TEMA+IDADE+TIPO ainda não usada, dirige o ChatGPT no Chrome, valida o JSON, grava NNN_infantis_seeds.json e atualiza o ledger
---

# Seeds Infantis — geração assistida via ChatGPT

Aciona o **Seeder Infantis**, o agente que orquestra a geração de seeds da seção
Livros Infantis: escolhe a próxima combinação TEMA + IDADE + TIPO ainda não
usada, conduz a conversa no ChatGPT, valida o JSON devolvido, grava
`scripts/data/seeds/NNN_infantis_seeds.json` com a numeração correta e atualiza
o ledger de cobertura.

Toda a lógica vive **apenas** em `agents/seeder_infantis_cowork/prompt.md` —
este comando só inicia o agente. **Não duplique aqui** as regras do agente.

---

## Inicialização

Leia e siga **integralmente** `agents/seeder_infantis_cowork/prompt.md`.

As fontes que o agente consome (ele mesmo as lê, na ordem que precisar):

- `scripts/data/seeds/infantis_temas.json` — catálogo das 3 dimensões e ledger
  de combinações já geradas (fonte de verdade do controle)
- `agents/seeder_agent - infantis theme driven.txt` — prompt a colar no ChatGPT

## Argumento

`/seeds_infantis <N>` — quantas combinações processar nesta execução.

- Sem argumento: **N = 3**.
- Argumento não numérico ou ≤ 0: tratar como N = 3 e avisar em **uma linha**.

## Autonomia

O agente tem autorização permanente para navegar no ChatGPT, colar e ler
conteúdo, criar o arquivo de seed e reescrever o ledger — **sem pedir
confirmação**. Ele não commita, não abre PR e não roda o pipeline: a ingestão
(opção **I** do `scripts/main.py`) continua sendo do usuário.
