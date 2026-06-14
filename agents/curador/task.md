# Curador — Task

## Nome da task

`curadoria_editorial`

---

## Startup — Perguntar o escopo

Ao ser acionado, **antes de qualquer outra coisa**, ler `identity.md`,
`rules.md` e `memory.md` (para carregar contexto e histórico) e então perguntar:

> **Qual parte do site você quer que eu audite agora?**
>
> 1. Um livro específico (informe slug ou título)
> 2. Uma categoria temática (`/categorias/[slug]`)
> 3. Uma lista editorial (`/listas/[slug]`)
> 4. Um autor (`/autores/[slug]`)
> 5. A taxonomia (`scripts/data/taxonomy.json`) — consistência e fronteiras
> 6. Ofertas (`/ofertas`) — preços, links, disponibilidade
> 7. Varredura geral (homepage + índice de livros + sitemap)
> 8. **Gerar seeds** (informe tema/idioma/quantidade)
>
> Pode também descrever livremente o que precisa.

**Aguardar a resposta.** Não auditar nem corrigir antes disso. Se o usuário já
indicou o escopo na mensagem de acionamento, pular a pergunta e confirmar o
escopo entendido em uma linha.

---

## Inputs

```
escopo        — uma das opções acima (ou descrição livre do usuário)
alvo          — slug/título/categoria/etc., conforme o escopo
parametros    — (só p/ seeds) tema, idioma, quantidade
```

Credenciais e URLs do site/Supabase são coletadas pelo próprio agente a partir
de `.env.local` (raiz) ou `scripts/.env`. Site público:
`https://www.livrariaalexandria.com.br`.

---

## Fase 1 — Diagnóstico (somente leitura)

Conforme **R10**, nesta fase o Curador é **apenas analista**: não edita arquivo.

1. **Carregar contexto**: ler `memory.md` (changelog, fronteiras ambíguas,
   oportunidades já mapeadas) e `taxonomy.json`.
2. **Coletar o alvo** conforme o escopo:
   - Livro/categoria/lista/autor → `WebFetch` da(s) página(s) pública(s) +,
     se necessário, consulta Supabase REST para o dado bruto.
   - Taxonomia → ler `taxonomy.json` por completo; cruzar com as categorias
     publicadas no Supabase (quais têm livros, quais estão órfãs).
   - Ofertas → `WebFetch /ofertas` + Supabase `ofertas`.
   - Varredura geral → `/sitemap.xml` → homepage → `/livros` (amostragem).
3. **Identificar erros**, por tipo:
   - **Conteúdo**: sinopse incompatível/placeholder, título/autor incorreto,
     bio inconsistente, encoding/acentuação quebrada, ano/ISBN errado.
   - **Taxonomia**: categoria temática errada para um livro; fronteiras
     ambíguas entre categorias; categoria órfã (sem livros); redundância;
     lacuna temática.
   - **SEO**: slug inconsistente, metadado faltante, descrição vazia/longa
     demais, lista sem introdução.
   - **Navegação**: link interno quebrado, livro não alcançável, categoria
     vazia exibida.
   - **Ofertas**: preço inválido/zero, link quebrado, CTA sem link.
4. **Validar fatos** duvidosos por `WebSearch`/`WebFetch` (R4).
5. **Classificar cada achado por risco** (R2) e montar a lista de remediação,
   separando **correções reais** de **lacunas operacionais** (que exigiriam
   rodar um step do pipeline — estas só são reportadas, não corrigidas aqui).

Apresentar ao usuário o **resumo de diagnóstico**: achados agrupados por risco,
com a ação proposta para cada um.

---

## Fase 2 — Remediação

1. **Baixo risco** → aplicar **autonomamente** (Edit/Write/Supabase REST),
   uma correção por vez, verificável.
2. **Médio/alto risco** → **só depois de aprovação** do usuário. Apresentar o
   plano (alvo, de → para, evidência) e aguardar "ok"/ajuste.
3. Após cada correção aplicada → **registrar** (Fase 3) imediatamente.
4. Lacunas operacionais → **não** corrigir; reportar quais steps resolvem.
5. **Correções em arquivos do repositório que o usuário queira commitar** →
   verificar **R12** antes de criar qualquer branch: nenhum PR aberto,
   branch local em `main` e limpo, GitHub Desktop fechado.

### Correções típicas e como aplicar

| Tipo | Ação |
|------|------|
| Typo/encoding em sinopse/bio/título | Supabase REST `PATCH livros`/`autores` por `id` |
| Categoria temática errada de 1 livro | Supabase `livros_categorias_tematicas` (corrige vínculo) |
| `description`/`label`/`group` de categoria | `Edit taxonomy.json` + (se publicada) `PATCH categorias` |
| Nova/fusão/remoção de categoria | `Edit taxonomy.json` (aprovação) + sincronizar Supabase |
| Oferta quebrada | Supabase `PATCH ofertas` (`ativa=false`) ou ajuste de URL |
| Slug publicado | **alto risco**: aprovação + considerar redirect |

Sempre validar JSON após editar `taxonomy.json`
(`python -c "import json; json.load(open('scripts/data/taxonomy.json', encoding='utf-8'))"`).

---

## Fase 3 — Registro (obrigatório, R8)

Para **cada** alteração aplicada:

### 3a — Log auditável estruturado

Acrescentar uma entrada em
`scripts/data/curador/curador_log_YYYYMMDD.json` (criar a pasta/arquivo se não
existir; o arquivo é um objeto com array `entries`):

```json
{
  "data": "2026-06-09",
  "entries": [
    {
      "timestamp": "2026-06-09T14:30:00Z",
      "escopo": "categoria | livro | taxonomia | oferta | seed | ...",
      "tipo": "correcao_conteudo | recategorizacao | taxonomia | oferta | seed | ...",
      "alvo": "<slug/id/arquivo afetado>",
      "de": "<valor anterior, se aplicável>",
      "para": "<novo valor>",
      "risco": "baixo | medio | alto",
      "confianca": "alta | media | baixa",
      "evidencia": "<fonte/justificativa objetiva>",
      "aprovado_por": "autonomo | usuario"
    }
  ]
}
```

Se o arquivo do dia já existir, **mesclar** (append em `entries`), nunca
sobrescrever entradas anteriores.

### 3b — Memória operacional legível

Atualizar `agents/curador/memory.md`:
- **Changelog** — uma linha por alteração relevante (data + resumo).
- **Oportunidades de expansão** — lacunas temáticas observadas (R9).
- **Fronteiras de taxonomia** — ambiguidades entre categorias e a regra
  adotada, para decisões consistentes no futuro.
- **Padrões/erros recorrentes** — para acelerar auditorias futuras.

---

## Fluxo de geração de seeds (escopo 8)

Quando o escopo for **gerar seeds** (R7):

1. Coletar do usuário: **tema/cluster, idioma, quantidade** (sugerir preencher
   lacunas de `memory.md` → *Oportunidades de expansão*).
2. **Calcular o próximo número**: varrer `scripts/data/seeds/*.json` **e**
   `scripts/data/seeds/ingested_seeds/*.json`, extrair o maior `NNN`, somar 1,
   formatar com 3 dígitos.
3. Gerar os itens (livros reais, anti-alucinação), alternando marketplace,
   alinhando `categoria` à taxonomia.
4. Escrever **JSONL** (um objeto por linha) em
   `scripts/data/seeds/NNN_offer_seeds.json`.
5. Registrar no log e em `memory.md` (changelog: "gerado seed NNN — tema, N
   itens"). **Não** rodar a ingestão.
6. Informar ao usuário o caminho e o número do arquivo, e que a ingestão é a
   próxima etapa manual (pipeline step 1).

---

## Output Contract

A task está concluída quando:

1. O escopo foi perguntado e respondido (ou já fornecido).
2. O diagnóstico foi apresentado, com achados classificados por risco.
3. Correções de baixo risco foram aplicadas; as de médio/alto risco foram
   aplicadas **só** após aprovação (ou registradas como pendentes se recusadas).
4. **Toda** alteração aplicada está em `curador_log_YYYYMMDD.json` **e** em
   `memory.md`.
5. (Se houve geração de seeds) o arquivo `NNN_offer_seeds.json` existe em
   `scripts/data/seeds/`, com numeração crescente correta e JSONL válido.
6. Um resumo final foi escrito:
   `Escopo: X | Achados: N | Corrigidos: C (baixo:b, aprovados:a) | Pendentes: P | Seeds gerados: S`.

---

## Princípio operacional

```
perguntar escopo → diagnosticar (ler) → classificar risco →
corrigir (baixo) / aprovar (médio·alto) → registrar (log + memória)
```
