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
| 2026-06-15 | contos_de_fada | 5 contos de fada + Mensagem/Pessoa removidos de `mitologia-e-lendas` | alto | usuário |
| 2026-06-15 | contos_de_fada | Cinderela, O Livro sem Figuras, A Seleção, Especiais removidos de `fantasia-juvenil` | alto | usuário |
| 2026-06-15 | contos_de_fada | Bone, This One Summer, Honor Girl, João e Maria, A Pequena Sereia, O Gato de Botas removidos de `literatura-juvenil` | alto | usuário |
| 2026-06-15 | contos_de_fada | Seed `461_offer_seeds.json` gerado — 25 títulos contos de fada/folclore PT | alto | usuário |
| 2026-06-14 | varredura_geral | `sobre/page.tsx`: título double-suffix → `"Sobre"` | baixo | autônomo |
| 2026-06-14 | varredura_geral | `categorias/page.tsx`: título double-suffix → `"Categorias"` | baixo | autônomo |
| 2026-06-14 | varredura_geral | `layout.tsx` footer 4×: `hover:text-[#8B1A1A]` → `hover:text-[#C9A84C]` (paleta) | baixo | autônomo |
| 2026-06-14 | varredura_geral | `layout.tsx` metadataBase: `livrariaalexandria.com.br` → `www.livrariaalexandria.com.br` | médio | usuário |

---

## Oportunidades de expansão temática

Lacunas observadas durante auditorias: categorias da taxonomia com poucos ou
nenhum livro, nacionalidades/períodos sub-representados, temas que mereceriam
nova categoria. Priorizar ao gerar seeds (R9).

- **folclore-brasileiro** (não publicado, 3 livros): apenas Lobato + Ruth Rocha. Oportunidade: Câmara Cascudo, Sílvio Romero, Figueiredo Pimentel já no seed 461; ingerir e publicar a categoria. (2026-06-15)
- **literatura-oral-e-popular** (não publicado, 3 livros): Andersen, La Fontaine, Cantar de Mio Cid. Fronteira ambígua com `contos-de-fada-e-fabulas`. Avaliar se merece ser publicada ou fundida.
- **contos-de-fada-e-fabulas**: 14 livros publicados — categoria ativa e bem formada. Seed 461 vai ampliar com 19 títulos de conto de fada + 4 de folclore brasileiro + 2 de literatura infantil (Lobato).

---

## Fronteiras de taxonomia (regras de desambiguação)

Decisões já tomadas sobre onde classificar casos de fronteira entre categorias,
para manter consistência. (Várias categorias já trazem `description` em
`taxonomy.json` com esses critérios — registrar aqui apenas decisões adicionais
tomadas durante a curadoria.)

- **contos-de-fada vs mitologia-e-lendas**: contos de fada (Grimm, Andersen, Perrault) vão em `contos-de-fada-e-fabulas`, nunca em `mitologia-e-lendas`. Mitologia = textos mitológicos (Gaiman, Miller, Riordan) ou compilações de mitos/lendas. (2026-06-15)
- **contos-de-fada vs fantasia-juvenil**: contos clássicos infantis (Cinderela, João e Maria, A Pequena Sereia) não são fantasia juvenil — `fantasia-juvenil` é para narrativas longas voltadas a adolescentes (Gaiman, C.S. Lewis, Riordan). (2026-06-15)
- **HQs em literatura-juvenil**: graphic novels e HQs (Bone, This One Summer, Honor Girl) não vão em `literatura-juvenil` — usar `hq-e-graphic-novel` e/ou `quadrinho-autobiografico`. (2026-06-15)
- **Mensagem (Pessoa) em mitologia**: poesia épica/simbolista portuguesa ≠ mitologia. Usar `poesia-portuguesa` + `modernismo-portugues`. (2026-06-15)

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
| `461_offer_seeds.json` | contos de fada / folclore / literatura infantil BR | PT | 25 | 2026-06-15 | Não |
