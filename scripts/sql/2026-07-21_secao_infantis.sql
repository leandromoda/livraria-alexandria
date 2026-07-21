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
