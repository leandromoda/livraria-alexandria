@echo off
REM ============================================================
REM Registra o Batch Autopilot no Windows Task Scheduler
REM Execute este script como administrador (clique direito > Executar como admin)
REM ============================================================

schtasks /create /tn "LivrariaAlexandria-BatchAutopilot" /tr "\"%~dp0batch_autopilot.bat\"" /sc minute /mo 30 /f

if %ERRORLEVEL% EQU 0 (
    echo.
    echo Tarefa agendada com sucesso! O autopilot vai rodar a cada 30 minutos.
    echo Para verificar: schtasks /query /tn "LivrariaAlexandria-BatchAutopilot"
    echo Para remover:   schtasks /delete /tn "LivrariaAlexandria-BatchAutopilot" /f
) else (
    echo.
    echo ERRO ao criar tarefa. Tente executar como administrador.
)

pause
