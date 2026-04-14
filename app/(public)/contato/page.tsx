import ContatoForm from "@/app/_components/ContatoForm";

export const metadata = {
  title: "Contato | Livraria Alexandria",
  description:
    "Entre em contato com a Livraria Alexandria para dúvidas, sugestões ou assuntos relacionados ao site.",
};

export default function ContatoPage() {
  return (
    <div className="max-w-2xl mx-auto px-6 py-16">

      <h1 className="text-3xl font-serif font-semibold text-[#0D1B2A] mb-4">
        Contato
      </h1>

      <p className="text-[#4A4A4A] mb-4">
        Para dúvidas ou sugestões sobre o conteúdo do site, preencha o
        formulário abaixo. Respondemos em dias úteis.
      </p>

      <p className="text-sm text-[#7B5E3A] mb-8">
        Este canal não realiza vendas nem atendimento pós-compra. Para questões
        relacionadas a pedidos, pagamentos ou entrega, entre em contato
        diretamente com o marketplace onde a compra foi realizada.
      </p>

      <ContatoForm />

    </div>
  );
}
