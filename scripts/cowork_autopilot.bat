@echo off
REM ============================================================
REM Cowork Autopilot — Livraria Alexandria
REM Ciclo: (export SOMENTE se a fila estiver vazia) -> Claude -> import
REM
REM Regra de controle: so exporta novos lotes para data\cowork\ quando
REM NAO houver mais arquivos de input pendentes para processar. Isso evita
REM o acumulo descontrolado de lotes nao processados.
REM ============================================================

cd /d "C:\Users\Leandro Moda\livraria-alexandria\scripts"

echo.
echo === [1/3] EXPORT (somente se nao houver lotes pendentes) ===
echo.

REM Ha inputs pendentes em data\cowork\? errorlevel 1 = sim (pular export).
python -c "import glob,sys; sys.exit(1 if (glob.glob('data/cowork/*_synopsis_input.json') or glob.glob('data/cowork/*_categorize_input.json')) else 0)"
if errorlevel 1 (
    echo Ja existem lotes de input pendentes em data\cowork\ - export ignorado.
) else (
    echo Fila vazia - exportando novos lotes.
    python -c "from steps import synopsis_export, categorize_export; synopsis_export.run('PT', 25); categorize_export.run(25)"
)

REM Apos a decisao de export, ha de fato algo para processar? Se nao, encerra.
python -c "import glob,sys; sys.exit(0 if (glob.glob('data/cowork/*_synopsis_input.json') or glob.glob('data/cowork/*_categorize_input.json')) else 1)"
if errorlevel 1 (
    echo.
    echo Nenhum lote pendente para processar. Encerrando.
    exit /b 0
)

echo.
echo === [2/3] CLAUDE — gerando conteudo ===
echo.
cd /d "C:\Users\Leandro Moda\livraria-alexandria"
npx --yes @anthropic-ai/claude-code -p "Leia agents/cowork_autopilot/prompt.md e execute todas as instrucoes. Leia os inputs em scripts/data/cowork/, gere os outputs e salve em scripts/data/cowork/. Sem interacao." --max-turns 50

echo.
echo === [3/3] IMPORT ===
echo.
cd /d "C:\Users\Leandro Moda\livraria-alexandria\scripts"
python -c "from steps import synopsis_import, categorize_import, apply_blacklist; synopsis_import.run(); categorize_import.run(); apply_blacklist.run(dry_run=False)" 2>nul

echo.
echo === AUTOPILOT CONCLUIDO ===
echo.
