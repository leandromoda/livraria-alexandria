-- ============================================================
-- SEÇÃO JOGOS — migração Supabase (rodar UMA VEZ no SQL Editor)
-- Livraria Alexandria · 2026-07-14
--
-- Tabelas do pipeline paralelo de jogos. Nenhuma tabela de
-- livros é alterada. Idempotente (IF NOT EXISTS / drop policy).
--
-- Depois de aplicar: python scripts/jogos.py → opção 7 (Publicar).
-- ============================================================

-- Catálogo de jogos (RPG de mesa, tabuleiro, cartas)
create table if not exists public.jogos (
  id             uuid primary key,
  titulo         text not null,
  slug           text not null unique,
  autor          text,                    -- designer / autor de RPG
  categoria      text not null,           -- 'rpg' | 'jogos-de-tabuleiro' | 'jogos-de-cartas'
  descricao      text,                    -- sinopse editorial (convenção igual a livros)
  imagem_url     text,
  ano_publicacao integer,
  preco_atual    numeric,
  marketplace    text,                    -- amazon | mercado_livre
  url_afiliada   text,
  offer_status   text default 'active',
  is_publishable boolean default true,
  created_at     timestamptz default now(),
  updated_at     timestamptz default now()
);

create index if not exists idx_jogos_categoria on public.jogos (categoria);

alter table public.jogos enable row level security;

drop policy if exists "public_read_jogos" on public.jogos;
create policy "public_read_jogos"
  on public.jogos for select
  using (true);

-- Click tracking de jogos (espelha oferta_clicks; insert só via service role)
create table if not exists public.jogo_clicks (
  id          uuid primary key default gen_random_uuid(),
  jogo_id     uuid references public.jogos (id),
  user_agent  text,
  referer     text,
  ip_hash     text,
  utm_source  text,
  utm_medium  text,
  utm_campaign text,
  session_id  text,
  created_at  timestamptz default now()
);

create index if not exists idx_jogo_clicks_jogo_id on public.jogo_clicks (jogo_id);

alter table public.jogo_clicks enable row level security;
-- GRANTs explícitos (ver nota no fim do arquivo sobre 30/10/2026).
grant select on public.jogos to anon, authenticated;
grant select, insert, update, delete on public.jogos to service_role;

grant select, insert, update, delete on public.jogo_clicks to service_role;

-- ------------------------------------------------------------------
-- Por que os GRANTs acima existem
--
-- Até 30/10/2026 o Supabase concedia acesso ao Data API automaticamente a toda
-- tabela nova em `public`. Depois dessa data, não concede mais: tabela criada
-- sem GRANT fica inalcançável pelo PostgREST, mesmo com RLS e policy corretas.
--
-- As tabelas em produção foram criadas antes do corte e herdaram o acesso —
-- nada muda para elas. Estes GRANTs existem para que reexecutar este arquivo
-- (projeto novo, branch de preview, `supabase db reset`) produza o mesmo
-- resultado depois de 30/10.
--
-- Sem eles, o modo de falha seria silencioso do jeito ruim: a policy
-- `public_read_*` existiria, o build não quebraria, e a seção apareceria
-- vazia no site — o mesmo tipo de erro que o comentário do fetchAll em
-- app/sitemap.ts já descreve ter ficado meses invisível.
--
-- Tabela de clique não recebe nada além de service_role: ninguém deve ler
-- clique pelo cliente.
-- ------------------------------------------------------------------

