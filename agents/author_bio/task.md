# TASK — Gerar bio editorial de autor

## Objetivo

Gerar uma bio editorial curta e factual sobre o autor identificado no input,
seguindo as regras de R1 a R7.

## Inputs disponíveis

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `nome` | string | Nome completo do autor (obrigatório) |
| `nacionalidade` | string ou null | Nacionalidade (ex.: "Brasileiro", "Francês") |
| `titulos` | lista de strings | Títulos de livros do autor disponíveis no catálogo |
| `idioma` | string | Idioma de saída — sempre "PT" neste contexto |

## Processo de geração

1. Identificar o autor pelo nome — verificar se é um autor de conhecimento público confirmado
2. Estruturar os três eixos de R1: quem é → escola/movimento → obras principais
3. Selecionar obras para mencionar:
   - Se `titulos` contiver obras reconhecidas do autor → priorizar esses títulos
   - Se `titulos` contiver apenas obras obscuras → complementar com obras consagradas conhecidas
   - Se `titulos` for vazio → usar obras consagradas do autor (se conhecido)
4. Redigir a bio em prosa corrida, respeitando R2 (80–160 palavras) e R4 (proibições)
5. Retornar apenas o JSON `{"bio": "..."}`

## Tratamento de falha

Se o autor for completamente desconhecido e `titulos` for vazio:
```json
{"bio": "Autor disponível no catálogo da Livraria Alexandria."}
```

Se o autor for desconhecido mas `titulos` não for vazio:
```json
{"bio": "Autor com obras em [área inferida dos títulos], incluindo [titulo_1] e [titulo_2]."}
```

## Contrato de output

- Exatamente um campo: `"bio"`
- Valor: string em português do Brasil
- Sem markdown interno, sem listas, sem quebras de parágrafo (\\n)
- Tamanho: 80–160 palavras
