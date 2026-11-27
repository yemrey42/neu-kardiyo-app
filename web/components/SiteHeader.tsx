import Link from "next/link";

const nav = [
  { href: "/haberler", label: "Haberler" },
  { href: "/literatur", label: "Literatür" },
  { href: "/egitim", label: "Eğitim" },
  { href: "/soru-bankasi", label: "Soru Bankası" },
  { href: "/calismalar", label: "Klinik Çalışmalar" },
];

export function SiteHeader() {
  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-4 py-4">
        <Link href="/" className="flex items-center gap-2 text-lg font-bold text-brand">
          <span aria-hidden>🫀</span> NEÜ Kardiyoloji
        </Link>
        <nav className="flex flex-wrap gap-4 text-sm font-medium">
          {nav.map((n) => (
            <Link key={n.href} href={n.href} className="hover:text-brand">
              {n.label}
            </Link>
          ))}
          <Link href="/giris" className="rounded bg-brand px-3 py-1 text-white hover:bg-brand-dark">
            Giriş
          </Link>
        </nav>
      </div>
    </header>
  );
}
