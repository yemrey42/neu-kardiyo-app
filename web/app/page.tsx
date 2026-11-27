import Link from "next/link";
import { news, studies, educationTools } from "@/lib/content";
import { JOURNALS } from "@/lib/pubmed";
import { formatDate } from "@/lib/format";
import { Hero } from "@/components/home/Hero";
import { ModuleStory } from "@/components/home/ModuleStory";
import { Reveal } from "@/components/home/Reveal";

const facts = [
  { value: String(JOURNALS.length), label: "dergi her gün otomatik takip ediliyor" },
  { value: String(studies.length), label: "yürüyen klinik çalışma" },
  { value: String(educationTools.length), label: "simülasyon ve hesaplayıcı" },
];

export default function Home() {
  return (
    <div>
      <Hero />

      <section className="py-24 text-center">
        <Reveal>
          <h2 className="mx-auto max-w-3xl text-3xl font-bold tracking-tight text-slate-900 sm:text-5xl">
            Kliniğimizin bilgisi, ekibimiz ve öğrencilerimiz için tek adreste.
          </h2>
        </Reveal>
        <div className="mt-14 grid gap-8 sm:grid-cols-3">
          {facts.map((f, i) => (
            <Reveal key={f.label} delay={i * 0.12}>
              <p className="text-6xl font-bold text-brand">{f.value}</p>
              <p className="mt-2 text-slate-600">{f.label}</p>
            </Reveal>
          ))}
        </div>
      </section>

      <ModuleStory />

      <section className="py-24">
        <Reveal>
          <div className="mb-8 flex items-end justify-between">
            <h2 className="text-3xl font-bold tracking-tight">Klinikten haberler</h2>
            <Link href="/haberler" className="text-sm font-semibold text-brand hover:underline">Tümü →</Link>
          </div>
        </Reveal>
        <div className="grid gap-6 md:grid-cols-2">
          {news.slice(0, 4).map((n, i) => (
            <Reveal key={n.slug} delay={i * 0.1}>
              <Link href={`/haberler/${n.slug}`}
                className="block rounded-2xl border border-slate-200 bg-white p-6 shadow-sm transition hover:-translate-y-1 hover:shadow-md">
                <p className="text-sm text-slate-500">{formatDate(n.date)}</p>
                <h3 className="mt-2 text-xl font-semibold">{n.title}</h3>
                <p className="mt-2 text-slate-600">{n.summary}</p>
              </Link>
            </Reveal>
          ))}
        </div>
      </section>
    </div>
  );
}
