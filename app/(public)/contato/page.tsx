export const runtime = "edge";

export const metadata = {
  title: "Contato | Livraria Alexandria",
  description:
    "Entre em contato com a Livraria Alexandria para dúvidas, sugestões ou assuntos relacionados ao site.",
};

export default function ContatoPage() {
  return (
    <div className="max-w-4xl mx-auto px-6 py-16">

      <h1 className="text-3xl font-bold mb-6">
        Contato
      </h1>

      <p className="mb-4">
        Para dúvidas, sugestões ou comunicações relacionadas ao conteúdo do site,
        utilize o canal abaixo.
      </p>

      <p className="mb-4">
        E-mail: contato@livrariaalexandria.com
      </p>

      <p className="mb-4">
        Respondemos o mais breve possível em dias úteis.
      </p>

      <p>
        Este canal não realiza vendas nem atendimento pós-compra. Para questões
        relacionadas a pedidos, pagamentos ou entrega, entre em contato
        diretamente com o marketplace onde a compra foi realizada.
      </p>

    </div>
  );
}