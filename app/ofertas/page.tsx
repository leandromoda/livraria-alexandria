"use client";

import { useEffect, useState } from "react";
import { getOfertas } from "./data";

type Oferta = {
  id: number;
  titulo: string;
  slug: string;
  afiliado_id: string;
  preco: number;
  preco_original: number | null;
};

export default function OfertasPage() {
  const [data, setData] = useState<Oferta[]>([]);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const result = await getOfertas();
        setData(result as Oferta[]);
      } catch (e: any) {
        setErro(e.message);
      }
    }

    load();
  }, []);

  if (erro) return <pre>{erro}</pre>;
  if (!data.length) return <p>Carregando ofertas…</p>;

  return (
    <main className="max-w-3xl mx-auto px-6 py-10 space-y-6">
      <h1 className="text-3xl font-bold">Ofertas de Livros</h1>

      <ul className="space-y-3">
        {data.map((o) => (
          <li key={o.id}>
            <a
              href={`/api/click/${o.afiliado_id}`}
              className="text-blue-600 hover:underline"
            >
              {o.titulo} — R$ {o.preco}
            </a>
          </li>
        ))}
      </ul>
    </main>
  );
}
