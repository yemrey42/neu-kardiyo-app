import type { Metadata } from "next";
import { PageTitle } from "@/components/PageTitle";
import { Quiz } from "./Quiz";
import { sampleQuestions } from "@/lib/content";

export const metadata: Metadata = { title: "Soru Bankası" };

export default function QuestionBankPage() {
  return (
    <>
      <PageTitle
        title="Kardiyoloji Soru Bankası"
        desc="Kategorilere göre sorular, anında geri bildirim ve açıklamalar. Fotoğraflı ve videolu testler sonraki aşamada eklenecek."
      />
      <Quiz questions={sampleQuestions} />
    </>
  );
}
