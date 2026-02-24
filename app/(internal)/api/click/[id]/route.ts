export const runtime = "edge";

import { NextResponse } from "next/server";
import { createClient } from "@supabase/supabase-js";

export async function GET(
  request: Request,
  context: { params: { id: string } }
) {
  const offerId = context.params.id;

  const supabase = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!
  );

  /**
   * 1) Buscar oferta + livro
   */
  const { data: oferta, error: ofertaError } =
    await supabase
      .from("ofertas")
      .select("id, livro_id, url_afiliada")
      .eq("id", offerId)
      .single();

  if (ofertaError || !oferta) {
    return new NextResponse("Oferta não encontrada", {
      status: 404,
    });
  }

  /**
   * 2) Metadados
   */
  const userAgent =
    request.headers.get("user-agent") ?? null;

  const referer =
    request.headers.get("referer") ?? null;

  const ip =
    request.headers.get("x-forwarded-for") ??
    "0.0.0.0";

  /**
   * 3) Hash IP (Edge-safe)
   */
  const hashBuffer = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(ip)
  );

  const ipHash = Array.from(
    new Uint8Array(hashBuffer)
  )
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");

  /**
   * 4) Insert tracking
   */
  await supabase.from("oferta_clicks").insert({
    oferta_id: oferta.id,
    livro_id: oferta.livro_id,
    user_agent: userAgent,
    referer: referer,
    ip_hash: ipHash,
  });

  /**
   * 5) Redirect afiliado
   */
  return NextResponse.redirect(
    oferta.url_afiliada,
    302
  );
}