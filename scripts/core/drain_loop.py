"""Espera produtiva do loop multijanela (opção G) — lógica pura e testável.

Mora fora do `main.py` de propósito: lá o módulo arrasta ~40 steps (e com eles
`requests`/`dotenv`), o que tornaria um teste de CI frágil. Aqui só entra
stdlib, e todas as dependências (relógio, sono, autopilot, janela de sessão)
entram por parâmetro — ver `tests/test_drain_loop.py`.
"""

# Intervalo entre re-checagens quando o não-LLM está seco. Mesma ideia do
# REPAIR_SAFETY_EVERY em steps/autopilot.py: cobrir trabalho que apareça no meio
# da espera, sem repetir um no-op de minuto em minuto.
DRENO_SAFETY_S = 1800          # 30 min

# Teto de cada soneca — mantém a re-checagem da janela de sessão responsiva.
NAP_MAX_S = 300                # 5 min


def drenar_ate_reset(*, autopilot_run, count_pending, session_window,
                     log, sleep, monotonic,
                     dreno_safety_s=DRENO_SAFETY_S, nap_max_s=NAP_MAX_S):
    """Drena o não-LLM enquanto a sessão PRO está em cooldown.

    `autopilot_run()` JÁ roda até exaurir por conta própria (guards de
    no-progresso / bottleneck de QG). Quando ele volta sem ter gerado progresso,
    o não-LLM está seco: re-invocá-lo 5 min depois refaz exatamente o mesmo
    trabalho nulo — e pior, cada invocação nova ZERA os guards internos
    (`step_sem_progresso`, `ciclos_sem_qg_avanco`), então eles nunca acumulam
    entre chamadas e nunca encurtam a repetição.

    Medido nos 5 logs substanciais de 2026-07-23..07-30 (n=469.695 linhas;
    contagem por `List Composer finalizado` / `QUALITY GATE END` /
    `[AUTOPILOT] Ciclo 1`): 93 invocações do autopilot produziram 732 passes de
    list_composer para 21 listas criadas (97% dos passes sem saída) e 320 passes
    de quality_gate. Só LISTAS+QUALITY somaram 430.072 linhas = 91,6% de tudo
    que foi escrito. O caso mais limpo é pipeline_2026-07-30_15-35-57 (3h50m):
    16 invocações, 168 passes de list_composer, 0 listas criadas, 0 aprovados.

    Correção: só re-invocar o autopilot se a invocação anterior reduziu
    `count_pending()`. Seco, apenas dormimos o cooldown, re-checando a cada
    `dreno_safety_s`.

    Devolve o motivo da saída: "quota_restaurada" ou "reset_atingido".
    """
    drenar = True
    proxima_checagem = 0.0

    while True:
        if drenar:
            pend_pre = count_pending()
            autopilot_run()
            pend_pos = count_pending()

            if pend_pos >= pend_pre:
                drenar = False
                proxima_checagem = monotonic() + dreno_safety_s
                log(f"[G] Não-LLM seco (pendente {pend_pre:,} → {pend_pos:,}); "
                    f"suspendendo o dreno e apenas aguardando o reset "
                    f"(re-checagem em {dreno_safety_s // 60} min).")
        elif monotonic() >= proxima_checagem:
            drenar = True            # re-checa se surgiu trabalho novo
            continue

        w = session_window()
        if not w.get("in_cooldown"):
            return "quota_restaurada"

        secs = max(0, int(w.get("seconds_until_reset", 0)))
        nap = min(nap_max_s, secs)
        if nap <= 0:
            return "reset_atingido"

        log(f"[G] Backlog não-LLM drenado; aguardando reset da sessão "
            f"(~{secs // 60} min restantes)…")
        sleep(nap)
