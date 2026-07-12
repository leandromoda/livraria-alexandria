"use client";

import { useState } from "react";
import Image from "next/image";
import { isOptimizableImage } from "@/lib/images";

const PAGE_SIZE = 48;

const MARKETPLACE_LABELS: Record<string, string> = {
  amazon: "Amazon",
  mercadolivre: "Mercado Livre",
  mercado_livre: "Mercado Livre",
};

function formatPrice(value: unknown): string | null {
  const num = Number(value);
  if (!value || num === 0 || isNaN(num)) return null;
  return num.toLocaleString("pt-BR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export type OfertaItem = {
  id: string;
  preco: number | null;
  marketplace: string;
  livros: {
    titulo: string;
    slug: string;
    autor: string | null;
    imagem_url: string | null;
  };
};

// Paginação client-side: a lista completa (~3.500 ofertas) vinha inteira no DOM,
// disparando milhares de imagens e um HTML gigante. Aqui renderizamos em janelas
// de 48 com "carregar mais" — o dado já chega cacheado do server (ISR).
export default function OfertasList({ ofertas }: { ofertas: OfertaItem[] }) {
  const [visible, setVisible] = useState(PAGE_SIZE);
  const janela = ofertas.slice(0, visible);

  return (
    <>
      <div className="space-y-4">
        {janela.map((o) => {
          const price = formatPrice(o.preco);
          return (
            <div
              key={o.id}
              className="flex items-center gap-5 bg-white border border-[#E6DED3] rounded-xl px-6 py-5 hover:border-[#C9A84C] hover:shadow-sm transition-all"
            >

              {/* Capa */}
              {o.livros.imagem_url ? (
                <Image
                  src={o.livros.imagem_url}
                  alt={o.livros.titulo}
                  width={48}
                  height={64}
                  unoptimized={!isOptimizableImage(o.livros.imagem_url)}
                  className="flex-shrink-0 w-12 h-16 object-cover rounded border border-[#E6DED3]"
                />
              ) : (
                <div className="flex-shrink-0 w-12 h-16 rounded bg-[#4A1628] flex items-center justify-center">
                  <span className="text-[#C9A84C] text-base font-serif">A</span>
                </div>
              )}

              {/* Dados */}
              <div className="flex-1 min-w-0">
                <a
                  href={`/livros/${o.livros.slug}`}
                  className="block font-serif font-semibold text-base text-[#0D1B2A] leading-snug hover:text-[#4A1628] transition-colors"
                >
                  {o.livros.titulo}
                </a>

                {o.livros.autor && (
                  <p className="text-sm text-[#4A4A4A] mt-0.5">
                    por {o.livros.autor}
                  </p>
                )}

                <span className="text-xs text-[#7B5E3A] bg-[#F5F0E8] border border-[#E6DED3] px-2.5 py-0.5 rounded-full mt-2 inline-block">
                  {MARKETPLACE_LABELS[o.marketplace] ?? o.marketplace}
                </span>
              </div>

              {/* Preço + CTA */}
              <div className="flex-shrink-0 text-right">
                {price ? (
                  <p className="text-xl font-serif font-semibold text-[#4A1628] mb-2">
                    R$ {price}
                  </p>
                ) : (
                  <p className="text-sm text-[#7B5E3A] mb-2">
                    Consulte o site
                  </p>
                )}

                <a
                  href={`/api/click/${o.id}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-block px-4 py-2 bg-[#C9A84C] text-[#4A1628] text-xs font-semibold rounded-lg hover:bg-[#e0bc5e] transition-colors"
                >
                  Ver oferta →
                </a>
              </div>

            </div>
          );
        })}
      </div>

      {/* Carregar mais */}
      {janela.length < ofertas.length && (
        <div className="pt-6 text-center">
          <button
            type="button"
            onClick={() => setVisible((v) => v + PAGE_SIZE)}
            className="px-5 py-2.5 border border-[#C9A84C] text-[#4A1628] text-sm font-semibold rounded-lg hover:bg-[#C9A84C] transition-colors"
          >
            Carregar mais ({ofertas.length - janela.length} restantes)
          </button>
        </div>
      )}
    </>
  );
}
