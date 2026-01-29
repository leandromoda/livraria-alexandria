export default function Home() {
  return (
    <main className="max-w-5xl mx-auto px-6 py-12">
      
      <header className="mb-12">
        <h1 className="text-4xl font-bold mb-4">
          Livraria Alexandria
        </h1>

        <p className="text-lg text-gray-600">
          Catálogo inteligente de livros para quem quer escolher melhor,
          comparar opções e comprar com confiança.
        </p>
      </header>

      <section className="mb-12">
        <h2 className="text-2xl font-semibold mb-4">
          O que você encontra aqui
        </h2>

        <ul className="list-disc pl-6 space-y-2 text-gray-700">
          <li>Listas curadas por tema e objetivo</li>
          <li>Páginas individuais de livros</li>
          <li>Comparação de edições e preços</li>
          <li>Links para compra nos principais marketplaces</li>
        </ul>
      </section>

      <section className="mb-12">
        <h2 className="text-2xl font-semibold mb-4">
          Comece explorando
        </h2>

        <div className="flex flex-col gap-4">
          <a
            href="/listas"
            className="text-blue-600 hover:underline"
          >
            → Ver listas de livros
          </a>

          <a
            href="/livros"
            className="text-blue-600 hover:underline"
          >
            → Explorar livros
          </a>
        </div>
      </section>

      <footer className="border-t pt-6 text-sm text-gray-500">
        <p>
          Este site pode conter links afiliados. Podemos receber comissões
          por compras realizadas através deles, sem custo adicional para você.
        </p>
      </footer>

    </main>
  );
}
