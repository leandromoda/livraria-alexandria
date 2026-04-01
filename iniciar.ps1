# ============================================================
#  Livraria Alexandria — Inicializador do Pipeline
#  Uso: .\iniciar.ps1 [-Lang PT]
# ============================================================

param(
    [ValidateSet("PT","EN","ES","IT")]
    [string]$Lang = "PT"
)

$Host.UI.RawUI.WindowTitle = "Livraria Alexandria — Pipeline"

$ROOT    = Split-Path -Parent $MyInvocation.MyCommand.Path
$SCRIPTS = Join-Path $ROOT "scripts"
$VENV    = Join-Path $ROOT "venv\Scripts\Activate.ps1"

# ── Navegar para a raiz do projeto ──────────────────────────
Set-Location $ROOT
Write-Host ""
Write-Host "============================================================" -ForegroundColor DarkYellow
Write-Host "  LIVRARIA ALEXANDRIA — Pipeline" -ForegroundColor Yellow
Write-Host "  Diretório: $ROOT" -ForegroundColor Gray
Write-Host "============================================================" -ForegroundColor DarkYellow
Write-Host ""

# ── Ativar virtualenv ───────────────────────────────────────
if (-not (Test-Path $VENV)) {
    Write-Host "[ERRO] Virtualenv não encontrado em: $VENV" -ForegroundColor Red
    Write-Host "       Crie com: python -m venv venv" -ForegroundColor Red
    Read-Host "`nPressione Enter para sair"
    exit 1
}

Write-Host "[1/2] Ativando ambiente virtual..." -ForegroundColor Cyan
. $VENV

Write-Host "[2/2] Iniciando pipeline (idioma=$Lang)..." -ForegroundColor Cyan
Write-Host ""

# ── Executar pipeline ───────────────────────────────────────
Set-Location $SCRIPTS
python main.py --lang $Lang

# ── Manter terminal aberto ──────────────────────────────────
Write-Host ""
Write-Host "============================================================" -ForegroundColor DarkYellow
Write-Host "  Pipeline encerrado." -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor DarkYellow
Read-Host "`nPressione Enter para fechar"
