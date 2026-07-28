---
name: seeds_infantis
description: Gera seeds de livros infantis via ChatGPT. Escolhe a combinação TEMA+IDADE+TIPO ainda não usada no catálogo, dirige a conversa no ChatGPT pelo Chrome, valida o JSON devolvido, grava scripts/data/seeds/NNN_infantis_seeds.json com a numeração correta e atualiza o ledger de cobertura. Esta skill deve ser usada quando o usuário pedir seeds infantis, novos livros para a seção Infantis, ou invocar /seeds_infantis.
---

# Seeds Infantis — geração assistida via ChatGPT

Aciona o **Seeder Infantis**, o agente que orquestra a geração de seeds da seção
Livros Infantis.

## Modelo e esforço recomendados

**Sonnet 5, esforço Alto.**

Os passos de navegador são mecânicos — abrir conversa, colar, copiar. O que
exige rigor é o checklist de validação do JSON e a recuperação de erro
(resposta truncada, cerca de markdown, `faixa_etaria` com grafia errada), e
isso responde a **esforço**, não a modelo maior.

Rodar em Opus aqui é desperdício direto: o gargalo de publicação do projeto é a
quota da sessão PRO gerando sinopses (ver "Gargalo de publicação" em
`scripts/CLAUDE.md`), e cada janela gasta neste trabalho de navegador é uma
janela que não vira livro publicado.

Modelo e esforço se escolhem no seletor do compositor — não são campos de
SKILL.md.

## Inicialização

Leia e siga **integralmente** `agents/seeder_infantis_cowork/prompt.md`.

As fontes que o agente consome (ele mesmo as lê, na ordem que precisar):

- `scripts/data/seeds/infantis_temas.json` — catálogo das 3 dimensões e ledger
  de combinações já geradas (fonte de verdade do controle)
- `agents/seeder_agent - infantis theme driven.txt` — prompt a colar no ChatGPT

**Não duplique aqui** as regras do agente. Toda a lógica vive no `prompt.md`.

## Argumento

`/seeds_infantis <N>` — quantas combinações processar nesta execução.

- Sem argumento: **N = 3**.
- Argumento não numérico ou ≤ 0: tratar como N = 3 e avisar em **uma linha**.

## Autonomia

O agente tem autorização permanente para navegar no ChatGPT, colar e ler
conteúdo, criar o arquivo de seed e reescrever o ledger — **sem pedir
confirmação**. Ele não commita, não abre PR e não roda o pipeline: a ingestão
(opção **I** do `scripts/main.py`) continua sendo do usuário.
