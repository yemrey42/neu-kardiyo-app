import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { imagingModules } from "@/lib/content";
import { SimFrame } from "@/app/egitim/[slug]/SimFrame";
import { currentUserEmail } from "@/lib/supabaseServer";
import { AssistantGate } from "@/components/TeamGate";

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  return { title: imagingModules.find((m) => m.slug === slug)?.title ?? "Ekokardiyografi Odası" };
}

export default async function ImagingModulePage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const mod = imagingModules.find((m) => m.slug === slug);
  if (!mod?.file) notFound();
  if (!(await currentUserEmail())) return <AssistantGate next={`/asistan/eko-odasi/${slug}`} title={mod.title} />;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Link href="/asistan/eko-odasi" className="text-sm text-brand">
          ← Ekokardiyografi Odası
        </Link>
        <a href={mod.file} target="_blank" rel="noopener" className="text-sm text-slate-500 hover:text-brand">
          Tam ekran aç ↗
        </a>
      </div>
      <SimFrame src={mod.file} title={mod.title} />
    </div>
  );
}
