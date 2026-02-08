import { NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const parts = url.pathname.split("/");

  const id = parts.at(-1);

  if (!id || id === "click") {
    return NextResponse.json(
      {
        error: "id ausente",
        pathname: url.pathname,
      },
      { status: 400 }
    );
  }

  return NextResponse.redirect(
    `https://www.amazon.com.br/dp/${id}`,
    302
  );
}
