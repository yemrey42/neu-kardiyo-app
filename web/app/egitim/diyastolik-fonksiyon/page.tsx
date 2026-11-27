import type { Metadata } from "next";
import Link from "next/link";
import { PageTitle } from "@/components/PageTitle";
import { DiastolicTool } from "./DiastolicTool";

export const metadata: Metadata = { title: "Diyastolik Fonksiyon" };

export default function DiastolicPage() {
  return (
    <>
      <Link href="/egitim" className="text-sm text-brand">← Eğitim</Link>
      <div className="mt-4">
        <PageTitle
          title="Diyastolik Fonksiyon"
          desc="Ekodaki ölçümlerinizi girin; dolum basıncı ve evre anında, Doppler çizimleri ve kalp şeması üzerinde görünsün. Eksik parametrede de karar vermenize yardım eder."
        />
      </div>
      <DiastolicTool />
    </>
  );
}
