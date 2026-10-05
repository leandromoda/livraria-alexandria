-- ============================================================
-- SEÇÃO LIVROS INFANTIS — migração Supabase (rodar UMA VEZ)
-- Livraria Alexandria · 2026-07-21
--
-- Tabelas do pipeline paralelo de livros infantis (até 12 anos).
-- Nenhuma tabela existente é alterada. Idempotente.
--
-- Depois de aplicar: python scripts/main.py -> opção I (autopilot).
-- ============================================================

create table if not exists public.livros_infantis (
  id             uuid primary key,
  titulo         text not null,
  slug           text not null unique,
  autor          text,
  ilustrador     text,                    -- coautor de fato no livro infantil
  faixa_etaria   text not null,           -- '0-2-anos'|'3-5-anos'|'6-8-anos'|'9-12-anos'
  idade_min      integer,
  idade_max      integer,
  descricao      text,                    -- sinopse editorial (convenção do site)
  imagem_url     text,
  ano_publicacao integer,
  preco_atual    numeric,
  marketplace    text,
  url_afiliada   text,
  offer_status   text default 'active',
  is_publishable boolean default true,
  created_at     timestamptz default now(),
  updated_at     timestamptz default now()
);

create index if not exists idx_livros_infantis_faixa
  on public.livros_infantis (faixa_etaria);

alter table public.livros_infantis enable row level security;

drop policy if exists "public_read_livros_infantis" on public.livros_infantis;
create policy "public_read_livros_infantis"
  on public.livros_infantis for select
  using (true);

-- Click tracking próprio (espelha oferta_clicks / jogo_clicks)
create table if not exists public.livro_infantil_clicks (
  id                uuid primary key default gen_random_uuid(),
  livro_infantil_id uuid references public.livros_infantis (id),
  user_agent        text,
  referer           text,
  ip_hash           text,
  utm_source        text,
  utm_medium        text,
  utm_campaign      text,
  session_id        text,
  created_at        timestamptz default now()
);

create index if not exists idx_livro_infantil_clicks_id
  on public.livro_infantil_clicks (livro_infantil_id);

alter table public.livro_infantil_clicks enable row level security;
-- GRANTs explícitos (ver nota no fim do arquivo sobre 30/10/2026).
grant select on public.livros_infantis to anon, authenticated;
grant select, insert, update, delete on public.livros_infantis to service_role;

grant select, insert, update, delete on public.livro_infantil_clicks to service_role;

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

