import { NextResponse } from "next/server";
import { createClient } from "@supabase/supabase-js";

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;

  const supabase = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
  );

  /**
   * Buscar oferta
   */
  const { data: oferta, error: ofertaError } =
    await supabase
      .from("ofertas")
      .select("id, url_afiliada")
      .eq("id", id)
      .single();

  console.log("Oferta:", oferta);
  console.log("Oferta error:", ofertaError);

  if (ofertaError || !oferta) {
    return new NextResponse("Oferta não encontrada", {
      status: 404,
    });
  }

  /**
   * Insert click
   */
  const { data: click, error: clickError } =
    await supabase.from("clicks").insert({
      oferta_id: oferta.id,
      user_agent: req.headers.get("user-agent"),
    });

  console.log("Click insert:", click);
  console.log("Click error:", clickError);

  return NextResponse.redirect(oferta.url_afiliada);
}
