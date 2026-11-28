import Link from "next/link";
import type { Metadata } from "next";
import { PageTitle } from "@/components/PageTitle";
import { QuestionBank } from "../soru-bankasi/QuestionBank";
import { bySection, loadQuestionBank } from "@/lib/questionBank";

export const metadata: Metadata = { title: "Doppler Hemodinami Soruları" };
// Google tablosundan (Fotograflar / Videolar, Drive'daki "doppler hemodinami" klasörü) en fazla 5 dakikada bir yenilenir.
export const revalidate = 300;

export default async function DopplerPage() {
  const { questions: all, origin } = await loadQuestionBank();
  const questions = origin === "google" ? bySection(all, "doppler") : [];
  return (
    <>
      <Link href="/asistan" className="mb-3 inline-block text-sm text-brand">← Asistanlar İçin</Link>
      <PageTitle
        title="Doppler Hemodinami Soruları"
        desc={`${questions.length} görüntülü soru. Doppler kayıtlarını yorumla, açıklamayla karşılaştır.`}
      />
      <aside className="mb-6 flex gap-3 rounded-2xl border border-sky-200 bg-sky-50 p-4 text-sm text-sky-950">
        <span aria-hidden className="text-lg leading-none">📖</span>
        <p>
          Bu bölümdeki görseller şu kitaptan alıntılanmıştır ve yalnızca eğitim amacıyla kullanılmaktadır:{" "}
          <cite className="not-italic">
            Argulian E, Soliman-Aboumarie H (ed.). <i>Clinical Applications of Echo Doppler Haemodynamics.</i> Academic Press
            (Elsevier); 2025.
          </cite>{" "}
          Her sorunun açıklamasında ilgili bölüm ve şekil belirtilmiştir.
        </p>
      </aside>
      {questions.length ? (
        <QuestionBank questions={questions} atlas={false} />
      ) : (
        <p className="rounded-2xl border border-slate-200 bg-white p-6 text-sm text-slate-600">Sorular şu anda yüklenemedi.</p>
      )}
    </>
  );
}
