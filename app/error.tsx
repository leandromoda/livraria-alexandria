"use client";

import { useEffect } from "react";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="min-h-[40vh] flex flex-col items-center justify-center text-center px-4 py-16">
      <div className="w-16 h-16 rounded-full bg-[#4A1628] flex items-center justify-center mb-6">
        <span className="text-[#C9A84C] text-2xl font-serif">A</span>
      </div>
      <h2 className="text-2xl font-serif font-semibold text-[#0D1B2A] mb-3">
        Algo deu errado
      </h2>
      <p className="text-sm text-[#4A4A4A] mb-8 max-w-sm">
        Não foi possível carregar esta página. Tente novamente em alguns instantes.
      </p>
      <button
        onClick={reset}
        className="px-5 py-2.5 bg-[#C9A84C] text-[#4A1628] text-sm font-semibold rounded-lg hover:bg-[#e0bc5e] transition-colors"
      >
        Tentar novamente
      </button>
    </div>
  );
}
