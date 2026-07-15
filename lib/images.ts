// Otimização de imagem do next/image (Vercel) DESLIGADA para todas as capas.
//
// As capas vêm de CDNs externos (covers.openlibrary.org, books.google.com,
// m.media-amazon.com) já como thumbnails no tamanho certo — o otimizador da
// Vercel agregava pouco e consumia toda a cota de transformations do free tier
// (5.000/mês), com ~4.000 capas no catálogo espalhadas por índices, categorias,
// autores e listas. Servindo direto do CDN de origem, o custo de transformations
// cai a ~zero e não há risco de "service disruption" ao estourar a cota.
//
// Todas as chamadas de <Image> usam `unoptimized={!isOptimizableImage(...)}`,
// então retornar sempre `false` aqui desliga a otimização em todo o site sem
// tocar em cada página. Para reativar (ex.: via loader próprio), reintroduzir a
// allowlist de hosts.
export function isOptimizableImage(url: string | null | undefined): boolean {
  void url; // parâmetro mantido p/ a assinatura dos callers; ignorado de propósito
  return false;
}
