import Link from "next/link";
import type { Metadata } from "next";
import { PageTitle } from "@/components/PageTitle";
import { studies, academicTracking } from "@/lib/content";

export const metadata: Metadata = { title: "Klinik Çalışmalar" };

export default function StudiesPage() {
  return (
    <>
      <PageTitle
        title="Klinik Çalışmalar"
        desc="Kliniğimizde yürütülen çalışmalar. Veri girişi yalnızca yetkili araştırma ekibine açıktır ve yalnızca anonimleştirilmiş veri kabul eder."
      />
      <div className="grid gap-4 md:grid-cols-2">
        {studies.map((s) => (
          <Link
            key={s.slug}
            href={`/calismalar/${s.slug}`}
            className="rounded-xl border border-slate-200 bg-white p-5 hover:border-brand"
          >
            <p className="text-xs font-medium uppercase tracking-wide text-brand">{s.area}</p>
            <h2 className="mt-1 font-semibold">{s.title}</h2>
            <p className="mt-1 text-sm text-slate-600">{s.summary}</p>
            <p className="mt-3 text-xs text-slate-500">
              Durum: {s.status} · Etik kurul: {s.ethicsApprovalNo ?? "onay no girilmedi"}
            </p>
          </Link>
        ))}
      </div>

      <h2 className="mt-12 mb-4 text-xl font-semibold">Akademik Takip (ekip içi)</h2>
      <div className="grid gap-4 md:grid-cols-3">
        {academicTracking.map((a) => (
          <div key={a.title} className="rounded-xl border border-dashed border-slate-300 bg-white p-5">
            <h3 className="font-semibold">{a.title}</h3>
            <p className="mt-1 text-sm text-slate-600">{a.desc}</p>
            <p className="mt-2 text-xs text-slate-500">Giriş yapan ekip üyelerine açılacak.</p>
          </div>
        ))}
      </div>
    </>
  );
}
