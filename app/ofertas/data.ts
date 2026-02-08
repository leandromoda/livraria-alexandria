import { ofertasMock } from "./data.mock";
import { createClient } from "@supabase/supabase-js";

type Oferta = {
  id: number;
  titulo: string;
  slug: string;
  preco: number;
  preco_original: number | null;
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
    .select("id, titulo, slug, preco, preco_original")
    .order("updated_at", { ascending: false });

  if (error) {
    throw new Error(error.message);
  }

  return data ?? [];
}
