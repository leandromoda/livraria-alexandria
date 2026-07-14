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
