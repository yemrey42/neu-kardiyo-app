import Link from "next/link";
import { news } from "@/lib/content";
import { formatDate } from "@/lib/format";

const modules = [
  { href: "/haberler", title: "Klinik Haberleri", desc: "Duyurular, toplantılar ve klinikten gelişmeler." },
  { href: "/literatur", title: "Güncel Literatür", desc: "Önemli yayınların kısa özetleri ve kılavuz güncellemeleri." },
  { href: "/egitim", title: "Eğitim", desc: "Simülasyonlar, hesaplayıcılar ve eğitim materyalleri." },
  { href: "/soru-bankasi", title: "Soru Bankası", desc: "Kategorilere ayrılmış kardiyoloji soruları ve açıklamaları." },
  { href: "/calismalar", title: "Klinik Çalışmalar", desc: "Yürüyen çalışmalar ve yetkili ekip için anonim veri girişi." },
];

export default function Home() {
  return (
    <div className="space-y-14">
      <section className="rounded-2xl bg-gradient-to-br from-brand to-brand-dark px-8 py-14 text-white">
        <h1 className="text-4xl font-bold">NEÜ Kardiyoloji Kliniği</h1>
        <p className="mt-4 max-w-2xl text-lg text-red-50">
          Klinik içi haberler, güncel literatür, eğitim içerikleri ve kliniğimizde yürütülen çalışmalar tek yerde.
        </p>
      </section>

      <section>
        <h2 className="mb-4 text-xl font-semibold">Modüller</h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {modules.map((m) => (
            <Link
              key={m.href}
              href={m.href}
              className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm transition hover:border-brand"
            >
              <h3 className="font-semibold text-slate-900">{m.title}</h3>
              <p className="mt-1 text-sm text-slate-600">{m.desc}</p>
            </Link>
          ))}
        </div>
      </section>

      <section>
        <h2 className="mb-4 text-xl font-semibold">Son Haberler</h2>
        <ul className="space-y-3">
          {news.slice(0, 3).map((n) => (
            <li key={n.slug}>
              <Link href={`/haberler/${n.slug}`} className="hover:text-brand">
                <span className="text-sm text-slate-500">{formatDate(n.date)}</span> · {n.title}
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
