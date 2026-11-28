import Link from "next/link";
import type { Metadata } from "next";
import { PageTitle } from "@/components/PageTitle";
import { CASE_HEADERS, loadCases } from "@/lib/questionBank";
import { CaseLibrary } from "./CaseLibrary";

export const metadata: Metadata = { title: "Kliniğimizden Vakalar" };
// Vakalar Google tablosundan en fazla 5 dakikada bir yenilenir.
export const revalidate = 300;

export default async function CasesPage() {
  const { cases, note } = await loadCases();
  return (
    <>
      <Link href="/asistan" className="mb-3 inline-block text-sm text-brand">← Asistanlar İçin</Link>
      <PageTitle
        title="Kliniğimizden Vakalar"
        desc="Görüntüye bak, öyküyü oku, cevabını düşün; sonra açıklamayla karşılaştır."
      />
      {cases.length ? (
        <CaseLibrary cases={cases} />
      ) : (
        <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-6 text-sm text-slate-600">
          <p className="font-medium text-slate-900">Henüz yayınlanmış vaka yok.</p>
          {note && <p className="mt-1 text-xs text-slate-500">Durum: {note}</p>}
          <details className="mt-4">
            <summary className="cursor-pointer text-brand">Vaka nasıl eklenir?</summary>
            <ol className="mt-2 list-decimal space-y-1 pl-5">
              <li>Görüntü ve videoları soru bankasının Drive klasörüne (ya da içindeki &quot;Vakalar&quot; klasörüne) yükleyin.</li>
              <li>
                Soru tablosunda <b>Vakalar</b> adlı sekmenin ilk satırına şu başlıkları yazın:{" "}
                <code className="rounded bg-slate-100 px-1">{CASE_HEADERS.join(" | ")}</code>
              </li>
              <li>Her vaka bir satır: Dosyalar kolonuna dosya adlarını (ör. vaka1.mp4, vaka1-tee.png) yazın, Aktif = TRUE yapın.</li>
            </ol>
          </details>
        </div>
      )}
    </>
  );
}
