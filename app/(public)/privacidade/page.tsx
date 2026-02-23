export const runtime = "edge";

export const metadata = {
  title: "Política de Privacidade | Livraria Alexandria",
  description:
    "Política de Privacidade da Livraria Alexandria — informações sobre coleta, uso e proteção de dados.",
};

export default function PrivacidadePage() {
  return (
    <div className="max-w-4xl mx-auto px-6 py-16">

      <h1 className="text-3xl font-bold mb-6">
        Política de Privacidade
      </h1>

      <p className="mb-4">
        A Livraria Alexandria respeita a privacidade dos usuários e se
        compromete com a proteção dos dados pessoais coletados durante a
        navegação no site.
      </p>

      <h2 className="text-xl font-semibold mt-8 mb-3">
        Coleta de informações
      </h2>

      <p className="mb-4">
        Podemos coletar dados de navegação, como páginas acessadas, cliques
        em links e interações com conteúdos, com a finalidade de análise
        estatística e melhoria da experiência do usuário.
      </p>

      <h2 className="text-xl font-semibold mt-8 mb-3">
        Uso de cookies
      </h2>

      <p className="mb-4">
        Utilizamos cookies para personalização de conteúdo, análise de tráfego
        e funcionamento adequado da plataforma. O usuário pode desativar os
        cookies nas configurações do navegador.
      </p>

      <h2 className="text-xl font-semibold mt-8 mb-3">
        Links de afiliados
      </h2>

      <p className="mb-4">
        O site participa de programas de afiliados. Ao acessar marketplaces
        por meio de nossos links, identificadores podem ser utilizados para
        rastrear comissões de indicação, sem custo adicional ao usuário.
      </p>

      <h2 className="text-xl font-semibold mt-8 mb-3">
        Compartilhamento de dados
      </h2>

      <p className="mb-4">
        Não vendemos nem compartilhamos dados pessoais com terceiros,
        exceto quando necessário para funcionamento técnico da plataforma
        ou cumprimento de obrigações legais.
      </p>

      <h2 className="text-xl font-semibold mt-8 mb-3">
        Contato
      </h2>

      <p>
        Em caso de dúvidas sobre esta política, entre em contato pelo e-mail:
        contato@livrariaalexandria.com.br
      </p>

    </div>
  );
}