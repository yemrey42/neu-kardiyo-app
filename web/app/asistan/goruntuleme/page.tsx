import Link from "next/link";
import type { Metadata } from "next";
import { PageTitle } from "@/components/PageTitle";
import { imagingModules } from "@/lib/content";

export const metadata: Metadata = { title: "Görüntüleme" };

export default function ImagingPage() {
  return (
    <>
      <Link href="/asistan" className="text-sm text-brand">
        ← Asistanlar İçin
      </Link>
      <PageTitle title="Görüntüleme" desc="Ekokardiyografi ve diğer görüntüleme yöntemleri için eğitim modülleri." />
      <div className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">
        {imagingModules.map((m) => (
          <Link
            key={m.slug}
            href={`/asistan/goruntuleme/${m.slug}`}
            className="group rounded-2xl border border-slate-200 bg-white p-6 transition hover:-translate-y-0.5 hover:border-brand hover:shadow-md"
          >
            <p className="text-xs font-medium uppercase tracking-wide text-emerald-700">{m.kind}</p>
            <h2 className="mt-1 text-xl font-semibold text-slate-900">{m.title}</h2>
            <p className="mt-1 text-slate-600">{m.desc}</p>
            <span className="mt-4 inline-block text-sm font-medium text-brand">Aç →</span>
          </Link>
        ))}
      </div>
    </>
  );
}
