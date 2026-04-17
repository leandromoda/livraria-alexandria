# RULES — Author Bio Generator

## R1 — Estrutura obrigatória da bio

A bio deve cobrir os três eixos abaixo, nessa ordem:

1. **Quem é o autor** — nacionalidade, período histórico, área principal de atuação
   (romance, poesia, ensaio, filosofia etc.)
2. **Escola, movimento ou corrente** — ex.: Realismo, Modernismo, Boom Latino-Americano,
   Nouveau Roman, Beat Generation, Literatura de Testemunho. Se o autor não se enquadrar
   em movimento reconhecido, mencione influências ou contexto literário relevante.
3. **Principais obras** — cite de 2 a 4 títulos que o autor seja reconhecido por ter escrito.
   Priorize os títulos presentes no campo `titulos` do input quando forem obras conhecidas.
   Se os títulos do input forem obscuros ou genéricos, use obras consagradas do autor
   (apenas se tiver conhecimento verificado delas).

## R2 — Tamanho

- Mínimo: 80 palavras
- Máximo: 160 palavras
- Faixa ideal: 100–140 palavras

## R3 — Idioma

Sempre português do Brasil, independente da nacionalidade do autor.

## R4 — Proibições absolutas

- Adjetivos vazios (brilhante, genial, revolucionário, fascinante, incrível etc.)
- Superlativos sem respaldo factual
- Linguagem promocional ou imperativa
- Markdown, listas, subtítulos — a bio é prosa corrida
- Metadados visíveis (não mencione "input", "dados fornecidos" etc.)

## R5 — Autor desconhecido ou dados insuficientes

Se `nome` não corresponder a um autor de conhecimento verificado E `titulos` for vazio
ou contiver obras desconhecidas:
- Produza uma bio genérica baseada exclusivamente nos títulos fornecidos
- Não invente fatos biográficos
- Exemplo aceitável: "Autor com obras nos campos de [tema], com títulos como [X] e [Y]."

## R6 — Formato de saída

JSON puro, sem markdown, sem texto fora do objeto:

```json
{"bio": "Texto da bio aqui..."}
```

## R7 — Determinismo

Inputs idênticos devem produzir outputs equivalentes em conteúdo e extensão.
