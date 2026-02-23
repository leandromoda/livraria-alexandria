export const runtime = "edge";

export const metadata = {
  title: "Sobre | Livraria Alexandria",
  description:
    "Conheça a Livraria Alexandria — plataforma digital para descoberta de livros, organização por temas e comparação de ofertas.",
};

export default function SobrePage() {
  return (
    <div className="max-w-4xl mx-auto px-6 py-16">

      <h1 className="text-3xl font-bold mb-6">
        Sobre a Livraria Alexandria
      </h1>

      <p className="mb-4">
        A Livraria Alexandria é uma plataforma digital voltada à organização
        e apresentação de livros disponíveis no mercado. O site reúne títulos
        em listas temáticas, categorias estruturadas e páginas individuais
        para facilitar a navegação e comparação.
      </p>

      <p className="mb-4">
        Nosso objetivo é oferecer uma estrutura clara para que leitores possam
        explorar obras por assunto, autor ou contexto, encontrando opções
        disponíveis em diferentes marketplaces.
      </p>

      <p className="mb-4">
        O site participa de programas de afiliados. Ao acessar ofertas por
        meio de nossos links, podemos receber uma comissão sem qualquer custo
        adicional ao usuário.
      </p>

      <p>
        A plataforma está em constante evolução, ampliando a base de títulos
        e aprimorando sua organização para melhorar a experiência de busca e
        descoberta de livros.
      </p>

    </div>
  );
}