# Pipeline de Crescimento de Dados — Livraria Alexandria

## Arquitetura

Pipeline modular baseado em scripts independentes com execução incremental e estado salvável.

## Banco local

SQLite → `data/livros.db`

## Scripts

1. Prospect → coleta livros em APIs públicas
2. Slug → normalização + colisão incremental
3. Dedupe → remoção inteligente
4. Synopsis Generate → LLM local
5. Synopsis Review → revisão linguística
6. Cover Generate → URLs de capas
7. Publish → envio Supabase

## Características

- Execução em pacotes
- Heartbeat de atividade
- Resume pós-interrupção
- Deduplicação incremental
- Clusters semânticos de biblioteca
