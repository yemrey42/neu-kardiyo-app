import type { Metadata } from "next";
import { PageTitle } from "@/components/PageTitle";
import { educationTools } from "@/lib/content";

export const metadata: Metadata = { title: "Eğitim" };

export default function EducationPage() {
  return (
    <>
      <PageTitle
        title="Eğitim Modülü"
        desc="Simülasyonlar, klinik hesaplayıcılar ve eğitim materyalleri. Araçlar mevcut uygulamamızdan aşamalı olarak bu siteye taşınacaktır."
      />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {educationTools.map((t) => (
          <div key={t.title} className="rounded-xl border border-slate-200 bg-white p-5">
            <p className="text-xs font-medium uppercase tracking-wide text-brand">{t.kind}</p>
            <h2 className="mt-1 font-semibold">{t.title}</h2>
            <span className="mt-3 inline-block rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-800">
              Yakında
            </span>
          </div>
        ))}
      </div>
    </>
  );
}
