-- ============================================================
-- oferta_clicks: acrescentar utm_medium (paridade com as tabelas irmãs)
-- Livraria Alexandria — 2026-08-30
-- ============================================================
--
-- CONTEXTO. De 2026-03-18 a 2026-08-30 o `/api/click/[id]` mandava
-- `utm_medium` num INSERT para `oferta_clicks`, e a coluna NÃO existe. O
-- PostgREST devolvia 400 PGRST204 "column not found", o handler não conferia o
-- erro e seguia para o redirect 302 — falha silenciosa por 5 meses.
--
-- No mesmo intervalo o GSC registrou 518 cliques de visitantes reais. Não há um
-- único dado de oferta sobre eles.
--
-- As tabelas irmãs `jogo_clicks` e `livro_infantil_clicks` JÁ têm `utm_medium`,
-- e são justamente as duas que continuaram registrando (42 e 4 linhas).
--
-- ⚠ ESTA MIGRAÇÃO É OPCIONAL. A correção do bug NÃO depende dela: o route já
-- foi alinhado ao schema real e voltou a gravar sem `utm_medium`. Aplique isto
-- só se quiser a paridade de schema entre as três tabelas de clique — e, nesse
-- caso, volte a incluir `utm_medium` no payload do route (há um comentário lá
-- apontando para este arquivo).
--
-- Rodar no SQL Editor do Supabase.

ALTER TABLE oferta_clicks
  ADD COLUMN IF NOT EXISTS utm_medium TEXT;

-- Conferência: as três tabelas de clique devem ter o mesmo conjunto de colunas
-- de UTM depois disto.
--
--   SELECT table_name, column_name
--     FROM information_schema.columns
--    WHERE table_name IN ('oferta_clicks', 'jogo_clicks', 'livro_infantil_clicks')
--      AND column_name LIKE 'utm%'
--    ORDER BY table_name, column_name;
