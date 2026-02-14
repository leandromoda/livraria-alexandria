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
        <header className="border-b bg-white">

          <nav className="max-w-6xl mx-auto px-6 py-4 flex gap-6 text-sm font-medium">

            <a href="/" className="hover:text-blue-600">
              Home
            </a>

            <a href="/listas" className="hover:text-blue-600">
              Listas
            </a>

            <a href="/livros" className="hover:text-blue-600">
              Livros
            </a>

            <a href="/ofertas" className="hover:text-blue-600">
              Ofertas
            </a>

          </nav>

        </header>

        {/* PAGE */}
        <main>
          {children}
        </main>

      </body>
    </html>
  );
}
