import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { educationTools } from "@/lib/content";
import { SimFrame } from "./SimFrame";

const frameTools = educationTools.filter((t) => t.file);

export function generateStaticParams() {
  return frameTools.map((t) => ({ slug: t.slug }));
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  return { title: frameTools.find((t) => t.slug === slug)?.title ?? "Eğitim" };
}

export default async function ToolPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const tool = frameTools.find((t) => t.slug === slug);
  if (!tool?.file) notFound();
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Link href="/egitim" className="text-sm text-brand">← Eğitim</Link>
        <a href={tool.file} target="_blank" rel="noopener" className="text-sm text-slate-500 hover:text-brand">
          Tam ekran aç ↗
        </a>
      </div>
      <SimFrame src={tool.file} title={tool.title} />
    </div>
  );
}
