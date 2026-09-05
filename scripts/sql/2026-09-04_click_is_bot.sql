-- ============================================================
-- Tabelas de clique: coluna is_bot
-- Livraria Alexandria — 2026-09-04
-- ============================================================
--
-- CONTEXTO. Cinco dias depois de o tracking voltar a gravar (#312), o primeiro
-- retrato de `oferta_clicks` mostrou 3.182 cliques — contra os 518 que o GSC
-- registra em CINCO MESES. O perfil não é de audiência:
--
--   * 2.746 de 3.182 (86%) sem referer nenhum, batendo em /api/click/ direto;
--   * 2.191 livros DISTINTOS para 3.182 cliques — varredura de catálogo;
--   * 732 ip_hash, o maior com 78 cliques em intervalos de 1-3 min de madrugada;
--   * 1.107 cliques com exatamente o mesmo user-agent de Mac.
--
-- Cada um ia para a Amazon COM a tag de afiliado — clique artificial em volume
-- maior do que o pipeline gerava antes do #311. O route agora redireciona esse
-- tráfego SEM a tag e marca a linha, para a métrica continuar utilizável.
--
-- ⚠ A MIGRAÇÃO É OPCIONAL PARA O REDIRECT, mas necessária para a MARCAÇÃO.
-- Sem ela o route detecta o PGRST204 e grava sem `is_bot` (com um WARN no log
-- da Vercel) — nenhum clique se perde. Foi assim que 5 meses de dados sumiram
-- em `oferta_clicks`, e o retry existe justamente para não repetir.
--
-- Rodar no SQL Editor do Supabase.

ALTER TABLE oferta_clicks          ADD COLUMN IF NOT EXISTS is_bot BOOLEAN;
ALTER TABLE jogo_clicks            ADD COLUMN IF NOT EXISTS is_bot BOOLEAN;
ALTER TABLE livro_infantil_clicks  ADD COLUMN IF NOT EXISTS is_bot BOOLEAN;

-- Índice para a consulta que interessa: quantos cliques HUMANOS por dia.
CREATE INDEX IF NOT EXISTS idx_oferta_clicks_is_bot_created
  ON oferta_clicks (is_bot, created_at DESC);

-- As 3.182 linhas anteriores ficam com is_bot NULL — "não classificado".
-- NÃO preencher retroativamente por heurística: o dado bruto (user_agent,
-- referer) continua lá e a classificação de hoje pode não ser a de amanhã.
-- Para separar o histórico, use a mesma regra do lib/afiliado.ts na consulta:
--
--   SELECT COUNT(*) FROM oferta_clicks
--    WHERE is_bot IS FALSE
--       OR (is_bot IS NULL AND referer LIKE '%livrariaalexandria.com.br%');
