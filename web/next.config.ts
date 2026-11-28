import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  poweredByHeader: false,
  // Soru bankası "Asistanlar İçin" bölümüne taşındı; eski bağlantılar çalışmaya devam etsin.
  async redirects() {
    return [{ source: "/soru-bankasi", destination: "/asistan/soru-bankasi", permanent: true }];
  },
};

export default nextConfig;
