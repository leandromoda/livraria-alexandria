export const runtime = "edge";

import "./globals.css";

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="pt-BR">
      <body>

        {/* =========================
            NAVBAR GLOBAL
        ========================== */}
        <header className="border-b bg-gray-900 text-white">

          <nav className="max-w-6xl mx-auto px-6 py-4 flex flex-wrap gap-6 text-sm font-medium">

            {/* PRINCIPAL */}
            <a href="/" className="hover:text-yellow-400">
              Home
            </a>

            <a href="/listas" className="hover:text-yellow-400">
              Listas
            </a>

            <a href="/livros" className="hover:text-yellow-400">
              Livros
            </a>

            <a href="/ofertas" className="hover:text-yellow-400">
              Ofertas
            </a>

            {/* INSTITUCIONAL */}
            <a href="/sobre" className="hover:text-yellow-400">
              Sobre
            </a>

            <a href="/contato" className="hover:text-yellow-400">
              Contato
            </a>

            <a href="/privacidade" className="hover:text-yellow-400">
              Privacidade
            </a>

            <a href="/termos" className="hover:text-yellow-400">
              Termos
            </a>

          </nav>

        </header>

        {/* PAGE */}
        <main>
          {children}
        </main>

        {/* =========================
            FOOTER INSTITUCIONAL
        ========================== */}
        <footer className="border-t mt-16 bg-gray-50">

          <div className="max-w-6xl mx-auto px-6 py-10 text-sm text-gray-600">

            {/* LINKS */}
            <div className="flex flex-wrap gap-6 mb-6">

              <a href="/sobre" className="hover:text-blue-600">
                Sobre
              </a>

              <a href="/contato" className="hover:text-blue-600">
                Contato
              </a>

              <a href="/privacidade" className="hover:text-blue-600">
                Política de Privacidade
              </a>

              <a href="/termos" className="hover:text-blue-600">
                Termos de Uso
              </a>

            </div>

            {/* DISCLOSURE AFILIADO */}
            <p className="mb-4">
              Este site participa de programas de afiliados. Alguns links podem
              gerar comissão sem custo adicional ao usuário.
            </p>

            {/* COPYRIGHT */}
            <p>
              © {new Date().getFullYear()} Livraria Alexandria — Todos os direitos reservados.
            </p>

          </div>

        </footer>

      </body>
    </html>
  );
}