import { supabase } from "@/lib/supabase";
import { NextResponse, type NextRequest } from "next/server";

export async function GET(request: NextRequest) {
  const { data } = await supabase.from("livros").select("slug");

  if (!data || data.length === 0) {
    return NextResponse.redirect(new URL("/livros", request.url));
  }

  const random = data[Math.floor(Math.random() * data.length)];
  return NextResponse.redirect(new URL(`/livros/${random.slug}`, request.url));
}
