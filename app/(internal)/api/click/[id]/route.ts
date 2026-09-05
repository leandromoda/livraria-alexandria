export const runtime = "edge";

import { NextRequest, NextResponse } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { urlDeRedirect } from "@/lib/afiliado";

/* NOTE: o segundo parâmetro é tipado como `any` intencionalmente —
   Next 15 impõe um tipo restrito para handlers dinâmicos; usar `any`
   resolve o erro de build sem alterar a lógica existente. */

export async function GET(
  request: NextRequest,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  context: any
) {

  const { id: offerId } = await context.params;

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

  const requestUrl = new URL(request.url);
  const utm_source   = requestUrl.searchParams.get("utm_source")   ?? null;
  // `utm_medium` NÃO é lido de propósito: a coluna não existe em
  // `oferta_clicks` e mandá-la quebrava o insert inteiro (ver o bloco 4).
  // Para voltar a capturá-la, aplicar antes
  // `scripts/sql/2026-08-30_oferta_clicks_utm_medium.sql`.
  const utm_campaign = requestUrl.searchParams.get("utm_campaign") ?? null;
  const session_id   = requestUrl.searchParams.get("session_id")   ?? null;

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
   *
   * ⚠ ESTE INSERT FALHOU EM SILÊNCIO DE 2026-03-18 A 2026-08-30.
   *
   * A tabela `oferta_clicks` no Supabase NÃO tem a coluna `utm_medium`
   * (as irmãs `jogo_clicks` e `livro_infantil_clicks` têm — e são justamente
   * as duas que continuaram registrando). Mandá-la no payload faz o PostgREST
   * devolver 400 PGRST204 "column not found", a mesma armadilha já documentada
   * para `status_publish` em `autores`/`listas`.
   *
   * O erro não era conferido, então o handler seguia para o redirect 302 e
   * ninguém via nada. Medido em 2026-08-30: a auditoria de conectividade bateu
   * nesta rota às 14:00 e recebeu 302, e nenhuma linha entrou — a tabela
   * seguia com 4 registros, todos de `localhost` em fevereiro.
   *
   * O commit que introduziu `utm_medium` é o `2e1b104` (2026-03-18), intitulado
   * "fix UTM tracking". No mesmo intervalo o GSC registrou **518 cliques** de
   * visitantes reais — tráfego sobre o qual não há um único dado de oferta.
   *
   * Duas mudanças: o payload passa a espelhar o schema real, e a falha passa a
   * aparecer no log da Vercel. O redirect NUNCA é bloqueado por erro de
   * tracking — perder a métrica é ruim, perder o clique do usuário é pior.
   */
  const { url: destino, humano } = urlDeRedirect(
    oferta.url_afiliada,
    userAgent,
    referer
  );

  const base = {
    oferta_id: oferta.id,
    livro_id: oferta.livro_id,
    user_agent: userAgent,
    referer: referer,
    ip_hash: ipHash,
    utm_source,
    utm_campaign,
    session_id,
  };

  // `is_bot` só existe depois da migração de 2026-09-04. Se a coluna não
  // estiver lá, o PostgREST devolve PGRST204 e o insert INTEIRO se perde — foi
  // exatamente assim que 5 meses de dados sumiram. Aqui a perda vira retry:
  // tenta com a coluna, e sem ela se o schema ainda não a tiver.
  let { error: trackError } = await supabase
    .from("oferta_clicks")
    .insert({ ...base, is_bot: !humano });

  if (trackError?.code === "PGRST204") {
    console.warn(
      "[click] oferta_clicks sem a coluna is_bot — aplicar " +
        "scripts/sql/2026-09-04_click_is_bot.sql. Gravando sem ela."
    );
    ({ error: trackError } = await supabase.from("oferta_clicks").insert(base));
  }

  if (trackError) {
    console.error(
      `[click] falha ao gravar oferta_clicks (oferta=${oferta.id}):`,
      trackError.code,
      trackError.message
    );
  }

  /**
   * 5) Redirect afiliado
   *
   * Bot é redirecionado do mesmo jeito — mas SEM a tag. Ver lib/afiliado.ts
   * para a medição que motivou isso (3.182 cliques em 5 dias, 86% sem referer).
   */
  return NextResponse.redirect(destino, 302);
}