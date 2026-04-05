@echo off
REM ============================================================
REM Cowork Autopilot — Livraria Alexandria
REM Roda o agente cowork_autopilot via Claude Code CLI
REM Agendado no Windows Task Scheduler a cada 30 min
REM ============================================================

cd /d "C:\Users\Leandro Moda\livraria-alexandria"

npx --yes @anthropic-ai/claude-code -p "Read agents/cowork_autopilot/prompt.md and execute all instructions in it. Work autonomously — generate inputs if needed, process synopses and categories, import results, and apply blacklist. Report a summary when done." --max-turns 50
