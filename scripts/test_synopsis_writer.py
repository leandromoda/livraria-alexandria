from core.markdown_executor import execute_agent

# =====================================================
# CONFIG
# =====================================================

AGENT_PATH = "agents/synopsis/synopsis_writer"

# =====================================================
# TEST PAYLOAD (simula saída do abstract_structurer)
# =====================================================

payload = {
    "idioma_resolved": "PT",
    "contexto": "sertão nordestino marcado por longos períodos de seca",
    "situacao_central": "uma família luta para sobreviver em meio às condições severas do sertão",
    "temas": [
        "pobreza",
        "sobrevivência",
        "resiliência"
    ],
    "escopo_narrativo": "vida rural marcada pela escassez e pela pobreza"
}

# =====================================================
# EXECUTION
# =====================================================

print("\n=== TESTE SYNOPSIS WRITER ===\n")

result = execute_agent(AGENT_PATH, payload)

print("\n=== RESULTADO ===")
print(result)