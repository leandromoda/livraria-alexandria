from core.markdown_executor import execute_agent

AGENT_PATH = "agents/synopsis/fact_extractor"

payload = {
    "descricao_base": """
Fabiano e sua família vivem no sertão nordestino, enfrentando longos períodos de seca.
A narrativa acompanha suas dificuldades diante da pobreza e da escassez de recursos.
O romance retrata a luta pela sobrevivência em um ambiente hostil.
""",
    "idioma_resolved": "PT"
}

result = execute_agent(AGENT_PATH, payload)

print("\n=== RESULTADO ===")
print(result)