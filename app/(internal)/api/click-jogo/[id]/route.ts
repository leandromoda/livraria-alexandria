export const runtime = "edge";

import { NextRequest, NextResponse } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { urlDeRedirect } from "@/lib/afiliado";

/* Click tracking da Seção Jogos — espelha /api/click/[id] (livros), mas lê a
   tabela `jogos` (oferta embutida no registro) e loga em `jogo_clicks`.
   Rota pública por design: precisa redirecionar sem auth.

   NOTE: o segundo parâmetro é tipado como `any` intencionalmente —
   Next impõe um tipo restrito para handlers dinâmicos; usar `any`
   resolve o erro de build sem alterar a lógica (mesmo padrão da rota de livros). */

export async function GET(
  request: NextRequest,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  context: any
) {

  const { id: jogoId } = await context.params;

  const supabase = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!
  );

  /**
   * 1) Buscar o jogo (oferta embutida)
   */
  const { data: jogo, error: jogoError } = await supabase
    .from("jogos")
    .select("id, url_afiliada")
    .eq("id", jogoId)
    .single();

  if (jogoError || !jogo?.url_afiliada) {
    return new NextResponse("Oferta não encontrada", {
      status: 404,
    });
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
  const { url: destino, humano } = urlDeRedirect(
    jogo.url_afiliada,
    userAgent,
    referer
  );

  // Bot leva redirect igual, mas SEM a tag de afiliado. Ver lib/afiliado.ts:
  // medido em 2026-09-04, 3.182 cliques em 5 dias com 86% sem referer.
  const base = {
    jogo_id: jogo.id,
    user_agent: userAgent,
    referer: referer,
    ip_hash: ipHash,
    utm_source,
    utm_medium,
    utm_campaign,
    session_id,
  };

  // `is_bot` so existe apos a migracao de 2026-09-04. Sem a coluna o PostgREST
  // devolve PGRST204 e o insert INTEIRO se perde — foi assim que 5 meses de
  // dados sumiram em oferta_clicks. Aqui vira retry.
  let { error: trackError } = await supabase
    .from("jogo_clicks")
    .insert({ ...base, is_bot: !humano });

  if (trackError?.code === "PGRST204") {
    console.warn(
      "[click] jogo_clicks sem a coluna is_bot — aplicar " +
        "scripts/sql/2026-09-04_click_is_bot.sql. Gravando sem ela."
    );
    ({ error: trackError } = await supabase.from("jogo_clicks").insert(base));
  }

  if (trackError) {
    console.error(
      `[click] falha ao gravar jogo_clicks (id=${jogo.id}):`,
      trackError.code,
      trackError.message
    );
  }

  /**
   * 5) Redirect afiliado
   */
  return NextResponse.redirect(destino, 302);
}
