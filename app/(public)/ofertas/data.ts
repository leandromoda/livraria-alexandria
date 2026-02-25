// app/(public)/ofertas/data.ts
export type Oferta = {
  id: number;
  titulo: string;
  slug: string;
  afiliado_id: string;
  preco: number;
  preco_original: number | null;
  url_afiliada: string;
};

/**
 * Mock de ofertas usado em dev / build local quando useMock = true.
 * Observação: url_afiliada é obrigatória para satisfazer o tipo Oferta.
 */
const ofertasMock: Oferta[] = [
  {
    id: 1,
    titulo: "Exemplo Livro A",
    slug: "exemplo-livro-a",
    afiliado_id: "AMZ-EX1",
    preco: 39.9,
    preco_original: 59.9,
    url_afiliada: "https://example.com/aff?offer=1"
  },
  {
    id: 2,
    titulo: "Exemplo Livro B",
    slug: "exemplo-livro-b",
    afiliado_id: "ML-EX2",
    preco: 29.9,
    preco_original: null,
    url_afiliada: "https://example.com/aff?offer=2"
  },
  {
    id: 3,
    titulo: "Exemplo Livro C",
    slug: "exemplo-livro-c",
    afiliado_id: "AMZ-EX3",
    preco: 49.9,
    preco_original: 69.9,
    url_afiliada: "https://example.com/aff?offer=3"
  }
];

/**
 * getOfertas
 * Se useMock = true retorna os mocks (útil para build / testes).
 * Caso contrário faria fetch real (exemplo usando Supabase).
 */
import { createClient } from "@supabase/supabase-js";

export default async function getOfertas(useMock = true) {
  if (useMock) {
    return ofertasMock;
  }

  const supabase = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_ANON_KEY!
  );

  const { data, error } = await supabase
    .from("ofertas")
    .select("*");

  if (error) {
    // Em produção, trate o erro apropriadamente; aqui devolvemos vazio
    return [];
  }

  // Garantir que cada item tenha url_afiliada (fallback)
  return (data || []).map((o: any) => ({
    id: o.id,
    titulo: o.titulo,
    slug: o.slug,
    afiliado_id: o.afiliado_id,
    preco: o.preco,
    preco_original: o.preco_original ?? null,
    url_afiliada: o.url_afiliada ?? "#"
  })) as Oferta[];
}