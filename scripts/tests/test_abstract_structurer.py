from core.markdown_executor import execute_agent

# ============================================
# CONFIG
# ============================================

AGENT_PATH = "agents/synopsis/abstract_structurer"

# ============================================
# TEST PAYLOAD
# ============================================

payload = {
    "ambientacao": "sertão nordestino marcado por longos períodos de seca",
    "contexto_social": "vida rural marcada pela escassez e pela pobreza",
    "conflito_central": "uma família luta para sobreviver em meio às condições severas do sertão",
    "personagens_mencionados": ["Fabiano", "Sinhá Vitória"],
    "temas_explicitos": ["pobreza", "sobrevivência", "resiliência"]
}

# ============================================
# EXECUTION
# ============================================

print("\n=== TESTE ABSTRACT STRUCTURER ===\n")

result = execute_agent(AGENT_PATH, payload)

print("\n=== RESULTADO ===")
print(result)