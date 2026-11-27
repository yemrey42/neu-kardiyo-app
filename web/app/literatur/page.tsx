import Link from "next/link";
import type { Metadata } from "next";
import { PageTitle } from "@/components/PageTitle";
import { literature } from "@/lib/content";
import { TOPICS, clinicPublications, latestCardiology, type Article } from "@/lib/pubmed";

export const metadata: Metadata = { title: "Güncel Literatür" };
// Sayfa günde bir kez yeniden oluşturulur; PubMed yanıtları da 24 saat önbellekte kalır.
export const revalidate = 86400;

async function safe(fn: () => Promise<Article[]>) {
  try {
    return { items: await fn(), error: false };
  } catch (e) {
    console.error(e);
    return { items: [] as Article[], error: true };
  }
}

function ArticleList({ items }: { items: Article[] }) {
  return (
    <ul className="divide-y divide-slate-200 rounded-xl border border-slate-200 bg-white">
      {items.map((a) => (
        <li key={a.pmid} className="p-4">
          <a href={a.url} target="_blank" rel="noopener noreferrer" className="font-medium hover:text-brand">
            {a.title}
          </a>
          <p className="mt-1 text-sm text-slate-500">
            <span className="font-medium text-slate-700">{a.journal}</span> · {a.date}
            {a.authors && <> · {a.authors}</>}
          </p>
        </li>
      ))}
    </ul>
  );
}

export default async function LiteraturePage({ searchParams }: { searchParams: Promise<{ konu?: string }> }) {
  const { konu = "tumu" } = await searchParams;
  const [latest, clinic] = await Promise.all([safe(() => latestCardiology(konu)), safe(clinicPublications)]);

  return (
    <div className="space-y-12">
      <PageTitle
        title="Literatürden Güncel Gelişmeler"
        desc="Önde gelen kardiyoloji dergilerinde son 14 günde yayımlanan makaleler PubMed'den her gün otomatik güncellenir."
      />

      {literature.length > 0 && (
        <section>
          <h2 className="mb-4 text-xl font-semibold">Ekibimizin seçtikleri</h2>
          <div className="grid gap-4 md:grid-cols-2">
            {literature.map((l) => (
              <article key={l.title} className="rounded-xl border border-slate-200 bg-white p-5">
                <p className="text-xs font-medium uppercase tracking-wide text-brand">{l.topic}</p>
                <h3 className="mt-1 font-semibold">{l.title}</h3>
                <p className="text-sm text-slate-500">{l.journal} · {l.date}</p>
                <p className="mt-2 text-sm text-slate-600">{l.summary}</p>
              </article>
            ))}
          </div>
        </section>
      )}

      <section>
        <h2 className="mb-4 text-xl font-semibold">Yeni yayınlar</h2>
        <nav className="mb-4 flex flex-wrap gap-2 text-sm">
          {TOPICS.map((t) => (
            <Link
              key={t.slug}
              href={t.slug === "tumu" ? "/literatur" : `/literatur?konu=${t.slug}`}
              className={`rounded-full border px-3 py-1 ${
                t.slug === konu ? "border-brand bg-brand text-white" : "border-slate-300 bg-white hover:border-brand"
              }`}
            >
              {t.label}
            </Link>
          ))}
        </nav>
        {latest.error ? (
          <p className="text-sm text-slate-500">PubMed'e şu an ulaşılamıyor, daha sonra tekrar deneyin.</p>
        ) : latest.items.length === 0 ? (
          <p className="text-sm text-slate-500">Bu konuda son 14 günde yayın bulunamadı.</p>
        ) : (
          <ArticleList items={latest.items} />
        )}
      </section>

      <section>
        <h2 className="mb-4 text-xl font-semibold">Kliniğimizden yayınlar</h2>
        {clinic.error ? (
          <p className="text-sm text-slate-500">PubMed'e şu an ulaşılamıyor.</p>
        ) : clinic.items.length === 0 ? (
          <p className="text-sm text-slate-500">Henüz yayın bulunamadı.</p>
        ) : (
          <ArticleList items={clinic.items} />
        )}
      </section>

      <p className="text-xs text-slate-500">
        Kaynak: PubMed (NCBI). Başlıklar ve künyeler bilgilendirme amaçlıdır; makalelerin tamamı ilgili dergide yer alır.
      </p>
    </div>
  );
}
