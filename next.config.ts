import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  images: {
    // Hosts reais das capas no catálogo (levantados via query ao Supabase):
    // covers.openlibrary.org (~2450) e books.google.com (~1580) dominam;
    // m.media-amazon.com aparece pontualmente. Qualquer host fora desta lista
    // é renderizado com `unoptimized` (ver lib/images.ts) para não quebrar o
    // render — o otimizador do next/image lança erro em host não configurado.
    remotePatterns: [
      { protocol: "https", hostname: "covers.openlibrary.org" },
      { protocol: "https", hostname: "books.google.com" },
      { protocol: "https", hostname: "m.media-amazon.com" },
    ],
  },
  async rewrites() {
    // O Catálogo de Arte Greco-Romana é um projeto separado, publicado na
    // Vercel, servido aqui como página anexa em /catalogo. Ele gera todas as
    // URLs internas já com esse prefixo, então o caminho passa inteiro.
    return [
      {
        source: "/catalogo",
        destination: "https://catalogoartegrecoromana.vercel.app/catalogo",
      },
      {
        source: "/catalogo/:path*",
        destination: "https://catalogoartegrecoromana.vercel.app/catalogo/:path*",
      },
    ];
  },
  async redirects() {
    return [
      {
        source: "/:path*",
        has: [{ type: "host", value: "www.livrariaalexandria.com.br" }],
        destination: "https://livrariaalexandria.com.br/:path*",
        permanent: true,
      },
    ];
  },
};

export default nextConfig;
