import type { Metadata } from "next";
import { PageTitle } from "@/components/PageTitle";
import { literature } from "@/lib/content";

export const metadata: Metadata = { title: "Güncel Literatür" };

export default function LiteraturePage() {
  return (
    <>
      <PageTitle
        title="Literatürden Güncel Gelişmeler"
        desc="Ekibimizin seçtiği önemli yayınlar, kılavuz güncellemeleri ve kısa yorumlar."
      />
      <div className="grid gap-4 md:grid-cols-2">
        {literature.map((l) => (
          <article key={l.title} className="rounded-xl border border-slate-200 bg-white p-5">
            <p className="text-xs font-medium uppercase tracking-wide text-brand">{l.topic}</p>
            <h2 className="mt-1 font-semibold">{l.title}</h2>
            <p className="text-sm text-slate-500">{l.journal} · {l.date}</p>
            <p className="mt-2 text-sm text-slate-600">{l.summary}</p>
          </article>
        ))}
      </div>
    </>
  );
}
