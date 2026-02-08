import { ofertasMock } from "./data.mock";
import { createClient } from "@supabase/supabase-js";

type Oferta = {
  id: number;
  titulo: string;
  slug: string;
  preco: number;
  url_afiliada: string;
};

export async function getOfertas(): Promise<Oferta[]> {
  const useMock = process.env.NEXT_PUBLIC_USE_MOCK === "true";

  if (useMock) {
    return ofertasMock;
  }

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
    .order("id", { ascending: false });

  if (error) {
    throw new Error(error.message);
  }

  /**
   * Flatten do JOIN
   */
  const parsed: Oferta[] =
    data?.map((o: any) => ({
      id: o.id,
      preco: o.preco,
      url_afiliada: o.url_afiliada,
      titulo: o.livros?.titulo ?? "Sem título",
      slug: o.livros?.slug ?? "#",
    })) ?? [];

  return parsed;
}
