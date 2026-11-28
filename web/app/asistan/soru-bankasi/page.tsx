import Link from "next/link";
import type { Metadata } from "next";
import { PageTitle } from "@/components/PageTitle";
import { QuestionBank } from "./QuestionBank";
import { bySection, loadQuestionBank } from "@/lib/questionBank";
import { currentUserEmail } from "@/lib/supabaseServer";
import { AssistantGate } from "@/components/TeamGate";

export const metadata: Metadata = { title: "Teorik Soru Bankası" };
// Girişli sayfa; sorular Google tablosundan en fazla 5 dakikada bir yenilenir (veri önbelleği).

export default async function QuestionBankPage() {
  if (!(await currentUserEmail())) return <AssistantGate next="/asistan/soru-bankasi" title="Teorik Soru Bankası" />;
  const bank = await loadQuestionBank();
  const { origin, notes } = bank;
  const questions = bySection(bank.questions, "theory");
  const cats = new Set(questions.map((q) => q.category)).size;
  return (
    <>
      <Link href="/asistan" className="mb-3 inline-block text-sm text-brand">← Asistanlar İçin</Link>
      <PageTitle
        title="Teorik Soru Bankası"
        desc={`${questions.length} soru, ${cats} konu. Pratikte kalp modelinden yapı seçerek çöz, sınavda süreye karşı yarış, seride rekorunu kır.`}
      />
      {origin === "sample" && (
        <p className="mb-6 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          Soru tablosuna şu an ulaşılamadı; aşağıda örnek sorular gösteriliyor.
          {notes.length > 0 && <span className="mt-1 block text-xs opacity-80">Sebep: {notes.join(" ")}</span>}
        </p>
      )}
      <QuestionBank questions={questions} />
      {origin === "google" && notes.length > 0 && (
        <details className="mt-10 text-xs text-slate-500">
          <summary className="cursor-pointer">Tablo notları ({notes.length})</summary>
          <ul className="mt-2 list-disc pl-5">
            {notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </details>
      )}
    </>
  );
}
