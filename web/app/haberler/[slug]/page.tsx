import { notFound } from "next/navigation";
import Link from "next/link";
import { news } from "@/lib/content";
import { formatDate } from "@/lib/format";

export function generateStaticParams() {
  return news.map((n) => ({ slug: n.slug }));
}

export default async function NewsDetail({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const item = news.find((n) => n.slug === slug);
  if (!item) notFound();
  return (
    <article className="max-w-3xl">
      <Link href="/haberler" className="text-sm text-brand">← Tüm haberler</Link>
      <h1 className="mt-4 text-3xl font-bold">{item.title}</h1>
      <p className="mt-1 text-sm text-slate-500">{formatDate(item.date)}</p>
      <p className="mt-6 leading-relaxed">{item.body}</p>
    </article>
  );
}
