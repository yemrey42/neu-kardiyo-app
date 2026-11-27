import Link from "next/link";
import type { Metadata } from "next";
import { PageTitle } from "@/components/PageTitle";
import { news } from "@/lib/content";
import { formatDate } from "@/lib/format";

export const metadata: Metadata = { title: "Haberler" };

export default function NewsPage() {
  return (
    <>
      <PageTitle title="Klinik Haberleri" desc="Kliniğimizden duyurular ve gelişmeler." />
      <div className="space-y-4">
        {news.map((n) => (
          <article key={n.slug} className="rounded-xl border border-slate-200 bg-white p-5">
            <p className="text-sm text-slate-500">{formatDate(n.date)}</p>
            <h2 className="mt-1 text-lg font-semibold">
              <Link href={`/haberler/${n.slug}`} className="hover:text-brand">{n.title}</Link>
            </h2>
            <p className="mt-1 text-slate-600">{n.summary}</p>
          </article>
        ))}
      </div>
    </>
  );
}
