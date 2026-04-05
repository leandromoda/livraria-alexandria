@echo off
REM ============================================================
REM Registra o Cowork Autopilot no Windows Task Scheduler
REM Execute este script como administrador (clique direito > Executar como admin)
REM ============================================================

schtasks /create /tn "LivrariaAlexandria-CoworkAutopilot" /tr "C:\Users\Leandro Moda\livraria-alexandria\scripts\cowork_autopilot.bat" /sc minute /mo 30 /f

if %ERRORLEVEL% EQU 0 (
    echo.
    echo Tarefa agendada com sucesso! O autopilot vai rodar a cada 30 minutos.
    echo Para verificar: schtasks /query /tn "LivrariaAlexandria-CoworkAutopilot"
    echo Para remover:   schtasks /delete /tn "LivrariaAlexandria-CoworkAutopilot" /f
) else (
    echo.
    echo ERRO ao criar tarefa. Tente executar como administrador.
)

pause
