// Hosts cujas imagens o next/image pode otimizar (devem casar com
// `images.remotePatterns` em next.config.ts). Capas de outros hosts são
// renderizadas com `unoptimized` para evitar o erro de "hostname not
// configured" — que quebraria o render da página, não só a imagem.
const OPTIMIZABLE_IMAGE_HOSTS = new Set([
  "covers.openlibrary.org",
  "books.google.com",
  "m.media-amazon.com",
]);

/**
 * true se a URL pode passar pelo otimizador do next/image (host na allowlist).
 * URLs nulas/inválidas retornam false.
 */
export function isOptimizableImage(url: string | null | undefined): boolean {
  if (!url) return false;
  try {
    return OPTIMIZABLE_IMAGE_HOSTS.has(new URL(url).host);
  } catch {
    return false;
  }
}
