@echo off
REM ============================================================
REM Cowork Autopilot — Livraria Alexandria
REM Ciclo completo: export → Claude → import
REM ============================================================

cd /d "C:\Users\Leandro Moda\livraria-alexandria"

echo.
echo === [1/3] EXPORT ===
echo.
cd scripts
python -c "from steps import synopsis_export, categorize_export; synopsis_export.run('PT', 25); categorize_export.run(50)"

REM Verificar se algum input foi gerado
if not exist "data\synopsis_input.json" if not exist "data\categorize_input.json" (
    echo.
    echo Nenhum livro pendente. Encerrando.
    exit /b 0
)

echo.
echo === [2/3] CLAUDE — gerando conteudo ===
echo.
cd /d "C:\Users\Leandro Moda\livraria-alexandria"
npx --yes @anthropic-ai/claude-code -p "Leia agents/cowork_autopilot/prompt.md e execute todas as instrucoes. Leia os inputs em scripts/data/, gere os outputs e salve em scripts/data/. Sem interacao." --max-turns 50

echo.
echo === [3/3] IMPORT ===
echo.
cd scripts
python -c "from steps import synopsis_import, categorize_import, apply_blacklist; synopsis_import.run(); categorize_import.run(); apply_blacklist.run(dry_run=False)" 2>nul

echo.
echo === AUTOPILOT CONCLUIDO ===
echo.
