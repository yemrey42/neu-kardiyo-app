import Link from "next/link";
import type { Metadata } from "next";
import { PageTitle } from "@/components/PageTitle";
import { bySection, loadQuestionBank } from "@/lib/questionBank";
import { questionToCase } from "@/lib/questionTypes";
import { CaseLibrary } from "./CaseLibrary";

export const metadata: Metadata = { title: "Kliniğimizden Vakalar" };
// Google tablosundan (Fotograflar / Videolar, Drive'daki "Neu vakalar" klasörü) en fazla 5 dakikada bir yenilenir.
export const revalidate = 300;

export default async function CasesPage() {
  const { questions, origin } = await loadQuestionBank();
  const cases = origin === "google" ? bySection(questions, "neu").map(questionToCase).reverse() : [];
  return (
    <>
      <Link href="/asistan" className="mb-3 inline-block text-sm text-brand">← Asistanlar İçin</Link>
      <PageTitle
        title="Kliniğimizden Vakalar"
        desc="Kliniğimizde karşılaştığımız vakaların görüntü ve videoları. Önce kendi yorumunu yap, sonra cevabı ve açıklamayı aç."
      />
      {cases.length ? (
        <CaseLibrary cases={cases} />
      ) : (
        <p className="rounded-2xl border border-slate-200 bg-white p-6 text-sm text-slate-600">Yeni vakalar yakında eklenecek.</p>
      )}
    </>
  );
}
