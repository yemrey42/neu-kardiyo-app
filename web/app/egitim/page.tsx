import type { Metadata } from "next";
import Link from "next/link";
import { PageTitle } from "@/components/PageTitle";
import { educationTools } from "@/lib/content";

export const metadata: Metadata = { title: "Eğitim" };

export default function EducationPage() {
  return (
    <>
      <PageTitle
        title="Eğitim Modülü"
        desc="Etkileşimli simülasyonlar ve görsel hesaplayıcılar. Bilgisayarda en iyi deneyim için geniş ekran önerilir."
      />
      <div className="grid gap-5 sm:grid-cols-2">
        {educationTools.map((t) => (
          <Link
            key={t.slug}
            href={`/egitim/${t.slug}`}
            className="group rounded-2xl border border-slate-200 bg-white p-6 shadow-sm transition hover:-translate-y-1 hover:border-brand hover:shadow-md"
          >
            <p className="text-xs font-medium uppercase tracking-wide text-brand">{t.kind}</p>
            <h2 className="mt-1 text-lg font-semibold">{t.title}</h2>
            <p className="mt-2 text-sm text-slate-600">{t.desc}</p>
            <span className="mt-4 inline-block text-sm font-semibold text-brand group-hover:underline">Aç →</span>
          </Link>
        ))}
      </div>
    </>
  );
}
