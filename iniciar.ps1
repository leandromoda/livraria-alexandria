# ============================================================
#  Livraria Alexandria — Inicializador do Pipeline
# ============================================================

$Host.UI.RawUI.WindowTitle = "Livraria Alexandria — Pipeline"

cd livraria-alexandria
venv\Scripts\activate
cd scripts
python main.py

Read-Host "`nPressione Enter para fechar"
