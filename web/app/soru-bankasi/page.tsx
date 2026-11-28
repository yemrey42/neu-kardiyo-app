import type { Metadata } from "next";
import { PageTitle } from "@/components/PageTitle";
import { QuestionBank } from "./QuestionBank";
import { loadQuestionBank } from "@/lib/questionBank";

export const metadata: Metadata = { title: "Soru Bankası" };
// Sorular Google tablosundan en fazla 5 dakikada bir yenilenir.
export const revalidate = 300;

export default async function QuestionBankPage() {
  const { questions, origin, notes } = await loadQuestionBank();
  const cats = new Set(questions.map((q) => q.category)).size;
  return (
    <>
      <PageTitle
        title="Kardiyoloji Soru Bankası"
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
