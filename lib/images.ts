// Otimização de imagem do next/image (Vercel) DESLIGADA para todas as capas.
//
// O motivo continua válido: o otimizador consumia toda a cota de transformations
// do free tier (5.000/mês), com ~4.600 capas espalhadas por índices, categorias,
// autores e listas. Servindo direto do CDN de origem, o custo cai a ~zero e não
// há risco de "service disruption" ao estourar a cota.
//
// ⚠️ CORREÇÃO (medido em 2026-08-26): estava escrito aqui que as capas vêm dos
// CDNs "já como thumbnails no tamanho certo". **Isso era falso para 1.294
// delas.** `scripts/steps/covers.py` reescrevia a URL do Google Books para
// `zoom=0` (resolução CHEIA) achando que `zoom=1` era "zoom baixo": 1.294 das
// 2.137 capas do Google Books (60%), e 28% de todas as 4.609 publicadas,
// serviam centenas de KB — uma delas 593 KB — para um slot de 176×256 px que
// ainda por cima tem `priority` (elemento de LCP da página de livro).
//
// Corrigido na ORIGEM, sem religar o otimizador: o zoom virou `2` em
// `covers.py` (~40 KB) e `tools/backfill_zoom_capas.py` reescreveu o passivo.
// Amostra de 14 capas por host, mesma data:
//
//   books.google.com        0,83 s | 172 KB de média (antes do fix)
//   covers.openlibrary.org  2,09 s |  36 KB
//
// O OpenLibrary (2.472 capas, 54%) segue lento por outra razão — dois redirects
// para dentro do archive.org —, que o tamanho não resolve. Segue em aberto.
//
// Todas as chamadas de <Image> usam `unoptimized={!isOptimizableImage(...)}`,
// então retornar sempre `false` aqui desliga a otimização em todo o site sem
// tocar em cada página. Para reativar (ex.: via loader próprio), reintroduzir a
// allowlist de hosts.
export function isOptimizableImage(url: string | null | undefined): boolean {
  void url; // parâmetro mantido p/ a assinatura dos callers; ignorado de propósito
  return false;
}
