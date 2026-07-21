export const runtime = "edge";

import { NextRequest, NextResponse } from "next/server";
import { createClient } from "@supabase/supabase-js";

/* Click tracking da seção Livros Infantis — espelha /api/click/[id] (livros) e
   /api/click-jogo/[id], mas lê `livros_infantis` (oferta embutida no registro)
   e loga em `livro_infantil_clicks`. Rota pública por design: precisa
   redirecionar sem auth.

   NOTE: o segundo parâmetro é tipado como `any` intencionalmente — Next impõe
   um tipo restrito para handlers dinâmicos (mesmo padrão das outras rotas). */

export async function GET(
  request: NextRequest,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  context: any
) {

  const { id: livroId } = await context.params;

  const supabase = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!
  );

  /**
   * 1) Buscar o livro (oferta embutida)
   */
  const { data: livro, error } = await supabase
    .from("livros_infantis")
    .select("id, url_afiliada")
    .eq("id", livroId)
    .single();

  if (error || !livro?.url_afiliada) {
    return new NextResponse("Oferta não encontrada", { status: 404 });
  }

  /**
   * 2) Metadados
   */
  const userAgent = request.headers.get("user-agent") ?? null;
  const referer = request.headers.get("referer") ?? null;
  const ip = request.headers.get("x-forwarded-for") ?? "0.0.0.0";

  const requestUrl = new URL(request.url);
  const utm_source   = requestUrl.searchParams.get("utm_source")   ?? null;
  const utm_medium   = requestUrl.searchParams.get("utm_medium")   ?? null;
  const utm_campaign = requestUrl.searchParams.get("utm_campaign") ?? null;
  const session_id   = requestUrl.searchParams.get("session_id")   ?? null;

  /**
   * 3) Hash IP (Edge-safe)
   */
  const hashBuffer = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(ip)
  );

  const ipHash = Array.from(new Uint8Array(hashBuffer))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");

  /**
   * 4) Insert tracking
   */
  await supabase.from("livro_infantil_clicks").insert({
    livro_infantil_id: livro.id,
    user_agent: userAgent,
    referer: referer,
    ip_hash: ipHash,
    utm_source,
    utm_medium,
    utm_campaign,
    session_id,
  });

  /**
   * 5) Redirect afiliado
   */
  return NextResponse.redirect(livro.url_afiliada, 302);
}
