# ============================================================
#  Livraria Alexandria — Inicializador do Pipeline
# ============================================================

$Host.UI.RawUI.WindowTitle = "Livraria Alexandria — Pipeline"

Set-Location "C:\Users\Leandro Moda\livraria-alexandria"
. ".\venv\Scripts\Activate.ps1"
Set-Location "scripts"
python main.py

Read-Host "`nPressione Enter para fechar"
