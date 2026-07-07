import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

function normalizeSlug(pathname: string): string {
  // Remove combining diacritical marks (accents) from slug segments
  return pathname.normalize("NFD").replace(/[̀-ͯ]/g, "");
}

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const normalized = normalizeSlug(pathname);

  if (normalized !== pathname) {
    const url = request.nextUrl.clone();
    url.pathname = normalized;
    return NextResponse.redirect(url, { status: 301 });
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/livros/:path*",
    "/listas/:path*",
    "/autores/:path*",
    "/categorias/:path*",
  ],
};
