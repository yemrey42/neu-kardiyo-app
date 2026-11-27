import Link from "next/link";
import { notFound } from "next/navigation";
import { studies } from "@/lib/content";
import { getFormSpec, groupBySection } from "@/lib/studyForms";
import { studySheetConfig } from "@/lib/studyConfig";
import { hasSession } from "@/lib/dataEntryAuth";
import { LoginForm } from "./LoginForm";
import { StudyForm } from "./StudyForm";
import { logout } from "./actions";

export const dynamic = "force-dynamic";

// Veriler şimdilik Google Sheets'e yazılır (Streamlit ile aynı tablo, ayrı "WEB - ..." sekmeleri).
// Kurallar:
//  - Ad, soyad, TC kimlik no, telefon, dosya/protokol numarası GİRİLMEZ.
//  - Hasta yalnızca çalışmaya özel takma kodla (ör. HT-001) tanımlanır;
//    kod-hasta eşleştirme listesi sitede değil, sorumlu araştırmacıda tutulur.
//  - Etik kurul onay numarası girilmemiş çalışmada veri girişi kapalıdır.
export default async function DataEntry({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const study = studies.find((s) => s.slug === slug);
  const spec = getFormSpec(slug);
  const cfg = studySheetConfig[slug];
  if (!study || !spec || !cfg) notFound();

  const ethicsOk = Boolean(study.ethicsApprovalNo);
  const loggedIn = await hasSession();

  return (
    <div className="space-y-6">
      <Link href={`/calismalar/${study.slug}`} className="text-sm text-brand">← {study.title}</Link>
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-2xl font-bold">Veri Girişi: {study.title}</h1>
        {loggedIn && (
          <form action={logout.bind(null, slug)}>
            <button className="text-sm text-slate-500 underline">Çıkış</button>
          </form>
        )}
      </div>

      <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
        <ul className="list-disc space-y-1 pl-5">
          <li>Yalnızca anonim veri: ad, TC kimlik no, telefon, dosya numarası <b>girilmez</b>.</li>
          <li>Hasta, çalışmaya özel kodla tanımlanır ({cfg.codePrefix}-001 gibi). Eşleştirme listesi sorumlu araştırmacıdadır.</li>
          <li>Etik kurul onay no: {study.ethicsApprovalNo ?? <b>girilmedi, veri girişi kapalı</b>}</li>
        </ul>
      </div>

      {!ethicsOk ? null : !loggedIn ? (
        <LoginForm slug={slug} />
      ) : (
        <StudyForm slug={slug} spec={spec} sections={groupBySection(spec)} codePrefix={cfg.codePrefix} />
      )}
    </div>
  );
}
