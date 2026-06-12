# Curador — Memory

Memória operacional persistente do Curador, mantida **pelo próprio agente** entre
execuções. Direciona trabalhos futuros: o que já foi alterado, onde estão as
fronteiras ambíguas da taxonomia, e quais oportunidades de expansão existem.

Não editar manualmente, exceto para corrigir entradas desatualizadas.

> Log auditável estruturado (uma entrada por alteração) fica em
> `scripts/data/curador/curador_log_YYYYMMDD.json`. Esta memória é a visão
> legível e sintética desse histórico.

---

## Changelog

Uma linha por alteração relevante aplicada (mais recentes no topo).

| Data | Escopo | Alteração | Risco | Aprovação |
|------|--------|-----------|-------|-----------|
| _(vazio — nenhuma alteração registrada ainda)_ | | | | |

---

## Oportunidades de expansão temática

Lacunas observadas durante auditorias: categorias da taxonomia com poucos ou
nenhum livro, nacionalidades/períodos sub-representados, temas que mereceriam
nova categoria. Priorizar ao gerar seeds (R9).

- _(vazio — nenhuma oportunidade mapeada ainda)_

---

## Fronteiras de taxonomia (regras de desambiguação)

Decisões já tomadas sobre onde classificar casos de fronteira entre categorias,
para manter consistência. (Várias categorias já trazem `description` em
`taxonomy.json` com esses critérios — registrar aqui apenas decisões adicionais
tomadas durante a curadoria.)

- _(vazio — nenhuma decisão adicional registrada ainda)_

---

## Padrões / erros recorrentes

Problemas que aparecem com frequência e como tratá-los, para acelerar auditorias
futuras (ex.: encoding quebrado em sinopses de certa origem, sinopses
placeholder de um período de geração, ofertas de um marketplace que expiram
rápido).

- _(vazio — nenhum padrão registrado ainda)_

---

## Seeds gerados

Registro dos seeds gerados pelo Curador (numeração, tema, quantidade), para
evitar duplicação e acompanhar o que ainda aguarda ingestão em
`scripts/data/seeds/`.

| Arquivo | Tema / cluster | Idioma | Itens | Data | Ingerido? |
|---------|----------------|--------|-------|------|-----------|
| _(vazio)_ | | | | | |
