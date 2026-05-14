from core.markdown_executor import execute_agent

# =====================================================
# CONFIG
# =====================================================

AGENT_FACT_EXTRACTOR     = "agents/synopsis/fact_extractor"
AGENT_ABSTRACT_STRUCTURER = "agents/synopsis/abstract_structurer"
AGENT_SYNOPSIS_WRITER    = "agents/synopsis/synopsis_writer"
AGENT_SYNOPSIS_VALIDATOR = "agents/synopsis/synopsis_validator"

# =====================================================
# TEST PAYLOAD
# =====================================================

IDIOMA = "PT"

DESCRICAO_BASE = """
Fabiano e sua família vivem no sertão nordestino, enfrentando longos períodos de seca.
A narrativa acompanha suas dificuldades diante da pobreza e da escassez de recursos.
O romance retrata a luta pela sobrevivência em um ambiente hostil, onde a esperança
de dias melhores sustenta os personagens diante de condições extremas.
"""

# =====================================================
# HELPERS
# =====================================================

def section(title):
    print(f"\n{'=' * 50}")
    print(f"  {title}")
    print(f"{'=' * 50}\n")

def show(label, data):
    print(f"[{label}]")
    for k, v in data.items():
        print(f"  {k}: {v}")
    print()

# =====================================================
# PIPELINE
# =====================================================

section("STAGE 1 — FACT EXTRACTOR")

stage1_input = {
    "descricao_base": DESCRICAO_BASE,
    "idioma_resolved": IDIOMA,
}

stage1_output = execute_agent(AGENT_FACT_EXTRACTOR, stage1_input)

show("fact_extractor output", stage1_output)

required_fact_keys = {
    "ambientacao",
    "contexto_social",
    "conflito_central",
    "personagens_mencionados",
    "temas_explicitos",
}

missing_fact_keys = required_fact_keys - set(stage1_output.keys())

assert not missing_fact_keys, f"FALHA — fact_extractor: chaves ausentes: {missing_fact_keys}"

print("[STAGE 1] OK\n")

# =====================================================

section("STAGE 2 — ABSTRACT STRUCTURER")

stage2_input = stage1_output

stage2_output = execute_agent(AGENT_ABSTRACT_STRUCTURER, stage2_input)

show("abstract_structurer output", stage2_output)

required_abstract_keys = {
    "contexto",
    "situacao_central",
    "temas",
    "escopo_narrativo",
}

missing_abstract_keys = required_abstract_keys - set(stage2_output.keys())

assert not missing_abstract_keys, f"FALHA — abstract_structurer: chaves ausentes: {missing_abstract_keys}"

print("[STAGE 2] OK\n")

# =====================================================

section("STAGE 3 — SYNOPSIS WRITER")

stage3_input = {
    "idioma_resolved": IDIOMA,
    **stage2_output,
}

stage3_output = execute_agent(AGENT_SYNOPSIS_WRITER, stage3_input)

show("synopsis_writer output", stage3_output)

assert "synopsis" in stage3_output, "FALHA — synopsis_writer: campo 'synopsis' ausente"

synopsis_text = stage3_output["synopsis"]

assert isinstance(synopsis_text, str) and len(synopsis_text.strip()) > 0, \
    "FALHA — synopsis_writer: synopsis vazia"

word_count = len(synopsis_text.split())

print(f"[WORD COUNT] {word_count} palavras")

assert 90 <= word_count <= 160, \
    f"FALHA — synopsis_writer: word count fora do range (90-160): {word_count}"

print("[STAGE 3] OK\n")

# =====================================================

section("STAGE 4 — SYNOPSIS VALIDATOR")

stage4_input = {
    "synopsis": synopsis_text,
    "idioma_resolved": IDIOMA,
}

stage4_output = execute_agent(AGENT_SYNOPSIS_VALIDATOR, stage4_input)

show("synopsis_validator output", stage4_output)

assert "status" in stage4_output, "FALHA — synopsis_validator: campo 'status' ausente"

status = stage4_output["status"]

assert status in ("APPROVED", "REWRITE_REQUIRED"), \
    f"FALHA — synopsis_validator: status inválido: {status}"

assert status == "APPROVED", \
    f"FALHA — synopsis_validator: sinopse rejeitada: {status}"

print("[STAGE 4] OK\n")

# =====================================================

section("RESULTADO FINAL")

print(f"STATUS : APROVADO")
print(f"IDIOMA : {IDIOMA}")
print(f"WORDS  : {word_count}")
print(f"\nSINOPSE:\n{synopsis_text}\n")