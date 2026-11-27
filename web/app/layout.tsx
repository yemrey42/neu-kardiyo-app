import type { Metadata } from "next";
import "./globals.css";
import { SiteHeader } from "@/components/SiteHeader";
import { SiteFooter } from "@/components/SiteFooter";

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "https://neu-cardio.com.tr"),
  title: { default: "NEÜ Kardiyoloji Kliniği", template: "%s | NEÜ Kardiyoloji" },
  description:
    "NEÜ Kardiyoloji Kliniği: klinik haberleri, güncel literatür, eğitim, soru bankası ve klinik çalışmalar.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="tr">
      <body className="flex min-h-screen flex-col">
        <SiteHeader />
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-10">{children}</main>
        <SiteFooter />
      </body>
    </html>
  );
}
