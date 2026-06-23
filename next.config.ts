import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  eslint: {
    ignoreDuringBuilds: true,
  },
  async redirects() {
    return [
      {
        source: "/:path*",
        has: [{ type: "host", value: "www.livrariaalexandria.com.br" }],
        destination: "https://livrariaalexandria.com.br/:path*",
        permanent: true,
      },
    ];
  },
};

export default nextConfig;
