# ============================================================
# JOGOS — CLI do pipeline paralelo (Seção Jogos)
# Livraria Alexandria
#
# Entrada INDEPENDENTE do main.py (decisão de isolamento 2026-07-14):
# o pipeline de livros não é tocado por nada daqui.
#
#   cd scripts && python jogos.py        # menu interativo
#   python jogos.py A                    # autopilot direto
# ============================================================

import sys

from steps import jogos_pipeline as jp


MENU = """
=== SEÇÃO JOGOS — PIPELINE PARALELO ===

 1  Importar seeds        (data/seeds/NNN_jogos_seeds.json)
 2  Resolver ofertas      (lookup_query → URL afiliada)
 3  Scraper marketplace   (capa + descrição + preço)
 4  Gerar slugs
 5  Sinopses (lote LLM — claude CLI)
 6  Quality gate
 7  Publicar no Supabase  (tabela jogos)

 A  Autopilot — passe completo (1→7)
 J  Autopilot multijanela — modelo G (espera reset da sessão e retoma)
 V  Verificar compatibilidade com o Supabase (contrato de publicação)
 S  Status
 Q  Sair
"""


def executar(opcao: str) -> bool:
    """Executa uma opção; retorna False para sair."""
    opcao = opcao.strip().upper()

    if opcao == "1":
        jp.import_seeds()
    elif opcao == "2":
        jp.resolve_offers()
    elif opcao == "3":
        jp.scrape()
    elif opcao == "4":
        jp.gen_slugs()
    elif opcao == "5":
        jp.run_synopsis_batch()
    elif opcao == "6":
        jp.quality_gate()
    elif opcao == "7":
        jp.publish()
    elif opcao == "A":
        jp.autopilot()
    elif opcao == "J":
        jp.autopilot_j()
    elif opcao == "V":
        jp.verify_supabase()
    elif opcao == "S":
        jp.status()
    elif opcao == "Q":
        return False
    elif opcao:
        print(f"Opção inválida: {opcao}")
    return True


def main():
    # Opção direta via argumento: python jogos.py A
    if len(sys.argv) > 1:
        executar(sys.argv[1])
        return

    jp.status()
    while True:
        print(MENU)
        try:
            opcao = input("Opção: ")
        except (EOFError, KeyboardInterrupt):
            break
        if not executar(opcao):
            break


if __name__ == "__main__":
    main()
