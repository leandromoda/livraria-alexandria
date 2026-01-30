type LivroPageProps = {
  params: {
    slug: string;
  };
};

export default function LivroPage({ params }: LivroPageProps) {
  const livro = {
    titulo: "Livro de Exemplo",
    autor: "Autor Desconhecido",
    descricao:
      "Esta é uma página de livro gerada dinamicamente a partir do slug da URL.",
  };

  return (
    <main className="max-w-4xl mx-auto px-6 py-12">
      <h1 className="text-3xl font-bold mb-2">
        {livro.titulo}
      </h1>

      <p className="text-gray-600 mb-6">
        por {livro.autor}
      </p>

      <p className="text-lg mb-8">
        {livro.descricao}
      </p>

      <div className="border-t pt-6">
        <p className="text-sm text-gray-500 mb-4">
          URL acessada:
        </p>
        <code className="bg-gray-100 px-3 py-2 rounded">
          {params.slug}
        </code>
      </div>
    </main>
  );
}
