export const runtime = "edge";

export const metadata = {
  title: "Termos de Uso | Livraria Alexandria",
  description:
    "Termos de Uso da Livraria Alexandria — condições para navegação e utilização da plataforma.",
};

export default function TermosPage() {
  return (
    <div className="max-w-4xl mx-auto px-6 py-16">

      <h1 className="text-3xl font-bold mb-6">
        Termos de Uso
      </h1>

      <p className="mb-4">
        Ao acessar e utilizar a Livraria Alexandria, o usuário concorda com
        os presentes Termos de Uso e com a Política de Privacidade.
      </p>

      <h2 className="text-xl font-semibold mt-8 mb-3">
        Natureza do serviço
      </h2>

      <p className="mb-4">
        A Livraria Alexandria é uma plataforma digital de organização e
        apresentação de livros, listas temáticas e ofertas disponíveis em
        marketplaces parceiros. Não realizamos vendas diretas nem processamos
        pagamentos.
      </p>

      <h2 className="text-xl font-semibold mt-8 mb-3">
        Links externos
      </h2>

      <p className="mb-4">
        O site pode conter links para plataformas externas. Não nos
        responsabilizamos por políticas, preços, disponibilidade ou práticas
        adotadas por terceiros.
      </p>

      <h2 className="text-xl font-semibold mt-8 mb-3">
        Propriedade intelectual
      </h2>

      <p className="mb-4">
        A estrutura do site, organização das listas e conteúdos originais são
        protegidos por direitos autorais. É vedada a reprodução integral do
        conteúdo sem autorização.
      </p>

      <h2 className="text-xl font-semibold mt-8 mb-3">
        Limitação de responsabilidade
      </h2>

      <p className="mb-4">
        A plataforma busca manter informações atualizadas, porém não garante
        a ausência de erros ou alterações realizadas pelos marketplaces.
      </p>

      <h2 className="text-xl font-semibold mt-8 mb-3">
        Contato
      </h2>

      <p>
        Para questões relacionadas a estes termos, entre em contato pelo e-mail:
        contato@livrariaalexandria.com.br
      </p>

    </div>
  );
}