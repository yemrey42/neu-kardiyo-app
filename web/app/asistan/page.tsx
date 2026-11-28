import Link from "next/link";
import type { Metadata } from "next";
import { PageTitle } from "@/components/PageTitle";
import { currentUserEmail } from "@/lib/supabaseServer";

export const metadata: Metadata = { title: "Asistanlar İçin" };

const sections = [
  {
    href: "/asistan/soru-bankasi",
    title: "Teorik Soru Bankası",
    accent: "bg-violet-50 text-violet-700",
    icon: <path d="M9 11l3 3L22 4M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />,
  },
  {
    href: "/asistan/doppler",
    locked: true,
    title: "Doppler Hemodinami",
    accent: "bg-sky-50 text-sky-700",
    icon: <path d="M2 16h3l2-8 3 12 3-14 3 10 2-4h4" />,
  },
  {
    href: "/asistan/eko-odasi",
    locked: true,
    title: "Ekokardiyografi Odası",
    accent: "bg-emerald-50 text-emerald-700",
    icon: (
      <>
        <path d="M12 3a9 9 0 0 0-9 9h18a9 9 0 0 0-9-9z" />
        <path d="M12 12L7 6M12 12l5-6M3 12v2a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-2" />
      </>
    ),
  },
  {
    href: "/asistan/vakalar",
    title: "Kliniğimizden Vakalar",
    accent: "bg-red-50 text-brand",
    icon: (
      <>
        <rect x="3" y="5" width="18" height="14" rx="2" />
        <circle cx="9" cy="11" r="2" />
        <path d="M21 16l-5-5-9 8" />
      </>
    ),
  },
];

export default async function AssistantsPage() {
  const signedIn = !!(await currentUserEmail());
  return (
    <>
      <PageTitle title="Asistanlar İçin" desc="Kardiyoloji asistanlarımız için çalışma ve vaka tartışma alanı." />
      <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-4">
        {sections.map((s) => (
          <Link key={s.href} href={s.href} className="group rounded-2xl border border-slate-200 bg-white p-6 transition hover:-translate-y-0.5 hover:border-brand hover:shadow-md">
            <span className={`inline-flex h-12 w-12 items-center justify-center rounded-xl ${s.accent}`}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" className="h-6 w-6" aria-hidden>
                {s.icon}
              </svg>
            </span>
            <h2 className="mt-4 text-xl font-semibold text-slate-900">{s.title}</h2>
            <span className="mt-4 inline-block text-sm font-medium text-brand">
              {s.locked && !signedIn ? "🔒 Giriş yaparak aç →" : "Aç →"}
            </span>
          </Link>
        ))}
      </div>
    </>
  );
}
