import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { imagingModules } from "@/lib/content";
import { SimFrame } from "@/app/egitim/[slug]/SimFrame";

export function generateStaticParams() {
  return imagingModules.map((m) => ({ slug: m.slug }));
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  return { title: imagingModules.find((m) => m.slug === slug)?.title ?? "Görüntüleme" };
}

export default async function ImagingModulePage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const mod = imagingModules.find((m) => m.slug === slug);
  if (!mod?.file) notFound();
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Link href="/asistan/goruntuleme" className="text-sm text-brand">
          ← Görüntüleme
        </Link>
        <a href={mod.file} target="_blank" rel="noopener" className="text-sm text-slate-500 hover:text-brand">
          Tam ekran aç ↗
        </a>
      </div>
      <SimFrame src={mod.file} title={mod.title} />
    </div>
  );
}
