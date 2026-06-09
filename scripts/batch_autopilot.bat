@echo off
REM ============================================================
REM Batch Autopilot — Livraria Alexandria
REM Ciclo: (export SOMENTE se a fila estiver completamente ociosa) -> Claude -> import
REM
REM Regra de controle (batch_guard.py): exporta novos lotes apenas quando NAO houver:
REM   - inputs pendentes em data\batch\ (aguardando o agente)
REM   - outputs pendentes em data\batch\ (aguardando import)
REM   - lotes em voo: input ja movido para processed_*\ pelo agente mas
REM     output ainda nao gerado (janela de overlap entre ciclos do scheduler)
REM ============================================================

cd /d "C:\Users\Leandro Moda\livraria-alexandria\scripts"

echo.
echo === [1/3] VERIFICAR FILA ===
echo.

REM Guard completo: inputs + outputs + lotes em voo (ver batch_guard.py)
python batch_guard.py
if errorlevel 1 (
    echo Export ignorado - aguardando ciclo anterior completar.
) else (
    echo Exportando novos lotes.
    python -c "from steps import synopsis_export, categorize_export; synopsis_export.run('PT', 25); categorize_export.run(25)"
)

REM Apos a decisao de export, ha de fato algo para processar? Se nao, encerra.
python -c "import glob,sys; sys.exit(0 if (glob.glob('data/batch/*_synopsis_input.json') or glob.glob('data/batch/*_categorize_input.json')) else 1)"
if errorlevel 1 (
    echo.
    echo Nenhum lote pendente para processar. Encerrando.
    exit /b 0
)

echo.
echo === [2/3] CLAUDE — gerando conteudo ===
echo.
cd /d "C:\Users\Leandro Moda\livraria-alexandria"
npx --yes @anthropic-ai/claude-code -p "Leia agents/batch_autopilot/prompt.md e execute todas as instrucoes. Leia os inputs em scripts/data/batch/, gere os outputs e salve em scripts/data/batch/. Sem interacao." --max-turns 50

echo.
echo === [3/3] IMPORT ===
echo.
cd /d "C:\Users\Leandro Moda\livraria-alexandria\scripts"
python -c "from steps import synopsis_import, categorize_import, apply_blacklist; synopsis_import.run(); categorize_import.run(); apply_blacklist.run(dry_run=False)" 2>nul

echo.
echo === AUTOPILOT CONCLUIDO ===
echo.
