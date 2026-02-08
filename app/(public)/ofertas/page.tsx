"use client";

import { useEffect, useState } from "react";
import { createClient } from "@supabase/supabase-js";

type Oferta = {
  id: number;
  titulo: string;
  slug: string;
  preco: number;
  url_afiliada: string;
};

export default function OfertasPage() {
  const [data, setData] = useState<Oferta[]>([]);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const supabase = createClient(
          process.env.NEXT_PUBLIC_SUPABASE_URL!,
          process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
        );

        const { data, error } = await supabase
          .from("ofertas")
          .select(`
            id,
            preco,
            url_afiliada,
            livros (
              titulo,
              slug
            )
          `)
          .eq("ativa", true);

        if (error) throw error;

        const parsed: Oferta[] =
          data?.map((o: any) => ({
            id: o.id,
            titulo: o.livros.titulo,
            slug: o.livros.slug,
            preco: o.preco,
            url_afiliada: o.url_afiliada,
          })) ?? [];

        setData(parsed);
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
      <h1 className="text-3xl font-bold">
        Ofertas de Livros
      </h1>

      <ul className="space-y-4">
        {data.map((o) => (
          <li
            key={o.id}
            className="border p-4 rounded-lg"
          >
            {/* Link interno → Livro */}
            <a
              href={`/livros/${o.slug}`}
              className="text-lg font-semibold text-blue-600 hover:underline block"
            >
              {o.titulo}
            </a>

            <p className="text-gray-700">
              R$ {o.preco}
            </p>

            {/* Link afiliado */}
            <a
              href={o.url_afiliada}
              target="_blank"
              className="text-sm text-green-600 hover:underline"
            >
              Ver oferta →
            </a>
          </li>
        ))}
      </ul>
    </main>
  );
}
