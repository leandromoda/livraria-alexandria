-- Fatos do Wikidata para "Sobre a obra" (livros) e dados do autor.
-- Gerado por scripts/steps/wikidata_enrich.py; o JSON só tem chave quando há
-- dado (o site não renderiza "não informado").
-- Idempotente. Rodar uma vez no SQL Editor do Supabase.
ALTER TABLE livros  ADD COLUMN IF NOT EXISTS wiki jsonb;
ALTER TABLE autores ADD COLUMN IF NOT EXISTS wiki jsonb;
