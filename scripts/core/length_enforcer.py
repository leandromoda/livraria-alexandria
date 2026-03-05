# ======================================================
# SYNOPSIS LENGTH ENFORCER
# Deterministic expansion without LLM
# ======================================================

MIN_WORDS = 90
MAX_WORDS = 160


def word_count(text: str) -> int:
    return len(text.split())


def _sentence_context(contexto):
    if not contexto:
        return ""
    return f"A narrativa se desenvolve em um contexto caracterizado por {contexto}."


def _sentence_situation(situacao):
    if not situacao:
        return ""
    return f"No centro da história está a situação em que {situacao}."


def _sentence_scope(escopo):
    if not escopo:
        return ""
    return f"O enredo retrata aspectos da experiência descrita como {escopo}."


def _sentence_themes(temas):
    if not temas:
        return ""
    temas_texto = ", ".join(temas)
    return f"Entre os temas presentes destacam-se {temas_texto}."


def _sentence_closure():
    return (
        "Ao apresentar esse cenário, a obra oferece uma visão sensível das "
        "dificuldades enfrentadas nesse ambiente e das formas de resistência "
        "que emergem diante das adversidades."
    )


def expand_synopsis(original, context):

    partes = [original]

    partes.append(_sentence_context(context.get("contexto")))
    partes.append(_sentence_situation(context.get("situacao_central")))
    partes.append(_sentence_scope(context.get("escopo_narrativo")))
    partes.append(_sentence_themes(context.get("temas")))
    partes.append(_sentence_closure())

    expanded = " ".join([p for p in partes if p])

    return expanded


def enforce_length(synopsis: str, context: dict) -> str:

    wc = word_count(synopsis)

    if wc >= MIN_WORDS:
        return synopsis

    expanded = expand_synopsis(synopsis, context)

    if word_count(expanded) > MAX_WORDS:
        expanded = " ".join(expanded.split()[:MAX_WORDS])

    return expanded