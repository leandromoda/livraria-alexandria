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
| 2026-06-14 | varredura_geral | `sobre/page.tsx`: título double-suffix → `"Sobre"` | baixo | autônomo |
| 2026-06-14 | varredura_geral | `categorias/page.tsx`: título double-suffix → `"Categorias"` | baixo | autônomo |
| 2026-06-14 | varredura_geral | `layout.tsx` footer 4×: `hover:text-[#8B1A1A]` → `hover:text-[#C9A84C]` (paleta) | baixo | autônomo |
| 2026-06-14 | varredura_geral | `layout.tsx` metadataBase: `livrariaalexandria.com.br` → `www.livrariaalexandria.com.br` | médio | usuário |

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

### Estratégia de auditoria do site (2026-06-14)

`WebFetch` retorna **403** para `www.livrariaalexandria.com.br` (CDN/Vercel bloqueia o UA da ferramenta).

**Workaround 1 — Chrome MCP** (`mcp__Claude_in_Chrome__*`): requer Chrome com a extensão Claude conectada. Permite ler páginas ao vivo com DOM. Pedir ao usuário que abra o Chrome com a extensão antes de iniciar auditorias de UI/navegação.

**Workaround 2 — Supabase REST API**: funciona sem Chrome. Usar `Invoke-WebRequest` (PowerShell) com headers `apikey` + `Authorization` lidos do `.env.local`. Retorna dados brutos de qualquer tabela. Útil para contar registros, verificar campos, checar lacunas.

**Workaround 3 — Filesystem (código-fonte)**: ler os arquivos `.tsx`/`.ts` em `app/` diretamente. Permite auditar metadados, cores, lógica de negócio sem precisar do site ao vivo. Suficiente para bugs de código (títulos duplicados, paleta, generateMetadata).

**Padrão adotado na varredura geral de 2026-06-14**: filesystem (código) + Supabase REST. Encontrou todos os bugs de código sem Chrome.

### Bugs de metadados (title template duplicado)

O `layout.tsx` usa template `"%s | Livraria Alexandria"`. Páginas que incluem o sufixo no próprio título renderizam double-suffix. Padrão de verificação: buscar nos `page.tsx` por `title: ".*\| Livraria Alexandria"`. Correção: remover o sufixo do título da página, deixar só o nome da seção.

Páginas afetadas encontradas em 2026-06-14: `sobre/page.tsx`, `categorias/page.tsx`.

---

## Seeds gerados

Registro dos seeds gerados pelo Curador (numeração, tema, quantidade), para
evitar duplicação e acompanhar o que ainda aguarda ingestão em
`scripts/data/seeds/`.

| Arquivo | Tema / cluster | Idioma | Itens | Data | Ingerido? |
|---------|----------------|--------|-------|------|-----------|
| _(vazio)_ | | | | | |
