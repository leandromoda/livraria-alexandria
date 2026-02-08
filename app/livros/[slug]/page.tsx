export const runtime = "edge";

import { notFound } from "next/navigation";
import { supabase } from "@/lib/supabase";

type PageProps = {
  params: {
    slug: string;
  };
};

export default async function LivroPage({ params }: PageProps) {
  const { slug } = params;

  const { data, error } = await supabase
    .from("livros")
    .select("*")
    .eq("slug", slug);

  if (error) {
    return <pre>{JSON.stringify(error, null, 2)}</pre>;
  }

  if (!data || data.length === 0) {
    return (
      <pre>
        Nenhum livro encontrado para slug:
        {"\n"}
        {slug}
      </pre>
    );
  }

  const livro = data[0];

  return (
    <main className="p-10">
      <h1>{livro.titulo}</h1>
      <p>{livro.slug}</p>
    </main>
  );
}
