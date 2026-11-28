import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  poweredByHeader: false,
  // Soru bankası "Asistanlar İçin" bölümüne taşındı; eski bağlantılar çalışmaya devam etsin.
  async redirects() {
    return [
      { source: "/soru-bankasi", destination: "/asistan/soru-bankasi", permanent: true },
      { source: "/asistan/goruntuleme/:path*", destination: "/asistan/eko-odasi/:path*", permanent: true },
    ];
  },
};

export default nextConfig;
