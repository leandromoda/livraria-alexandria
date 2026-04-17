from steps.offer_resolver import inject_ml_affiliate

# Caso 1: URL ML sem parâmetros — deve injetar matt_word e matt_tool
url_sem_params = "https://lista.mercadolivre.com.br/dom-casmurro"
resultado = inject_ml_affiliate(url_sem_params)
assert "matt_word=leandro_moda" in resultado, f"matt_word ausente: {resultado}"
assert "matt_tool=45905535" in resultado, f"matt_tool ausente: {resultado}"
print(f"[OK] URL sem params -> {resultado}")

# Caso 2: URL ML já com parâmetros — deve retornar sem duplicar
url_com_params = "https://lista.mercadolivre.com.br/dom-casmurro?matt_word=leandro_moda&matt_tool=45905535"
resultado2 = inject_ml_affiliate(url_com_params)
assert resultado2 == url_com_params, f"URL modificada indevidamente: {resultado2}"
assert resultado2.count("matt_tool") == 1, f"Parâmetro duplicado: {resultado2}"
print(f"[OK] URL já com params -> idempotente")

# Caso 3: URL Amazon — não deve ser alterada
url_amazon = "https://www.amazon.com.br/s?k=dom+casmurro"
resultado3 = inject_ml_affiliate(url_amazon)
assert resultado3 == url_amazon, f"URL Amazon modificada indevidamente: {resultado3}"
assert "matt_tool" not in resultado3, f"Parâmetro ML injetado em URL Amazon: {resultado3}"
print(f"[OK] URL Amazon -> não afetada")

print("\nTodos os testes passaram.")
