import "./globals.css";
import Header from "./_components/Header";
import Link from "next/link";
import type { Metadata } from "next";
import { Analytics } from "@vercel/analytics/next";

export const metadata: Metadata = {
  title: {
    default: "Livraria Alexandria",
    template: "%s | Livraria Alexandria",
  },
  description:
    "Descubra livros, listas editoriais e as melhores ofertas em literatura nacional e internacional.",
  metadataBase: new URL("https://livrariaalexandria.com.br"),
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="pt-BR">
      <body className="bg-[#F5F0E8] text-[#0D1B2A]">

        <Header />

        {/* PAGE */}
        <main className="max-w-6xl mx-auto px-6 py-12">
          {children}
        </main>

        {/* FOOTER */}
        <footer className="border-t border-[#E6DED3] mt-20 bg-[#F5F0E8]">

          <div className="max-w-6xl mx-auto px-6 py-12 text-sm text-[#4A4A4A]">

            <div className="flex flex-wrap justify-center gap-6 mb-8">

              <Link href="/sobre" className="hover:text-[#8B1A1A] transition-colors">
                Sobre
              </Link>

              <Link href="/contato" className="hover:text-[#8B1A1A] transition-colors">
                Contato
              </Link>

              <Link href="/privacidade" className="hover:text-[#8B1A1A] transition-colors">
                Política de Privacidade
              </Link>

              <Link href="/termos" className="hover:text-[#8B1A1A] transition-colors">
                Termos de Uso
              </Link>

            </div>

            <p className="text-center mb-6 max-w-2xl mx-auto">
              Este site participa de programas de afiliados. Alguns links podem
              gerar comissão sem custo adicional ao usuário.
            </p>

            <p className="text-center text-xs text-[#7B5E3A]">
              © {new Date().getFullYear()} Livraria Alexandria — Todos os direitos reservados.
            </p>

          </div>

        </footer>

        <Analytics />
      </body>
    </html>
  );
}
