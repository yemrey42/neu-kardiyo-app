import Link from "next/link";
import { notFound } from "next/navigation";
import { studies } from "@/lib/content";

export function generateStaticParams() {
  return studies.map((s) => ({ slug: s.slug }));
}

// İskelet: gerçek form, Supabase oturumu + rol kontrolü (araştırmacı) eklendiğinde açılacak.
// Kurallar (supabase/schema.sql içindeki RLS ile de zorunlu):
//  - Ad, soyad, TC kimlik no, telefon, dosya/protokol numarası GİRİLMEZ.
//  - Hasta yalnızca çalışmaya özel takma kodla (ör. HT-001) tanımlanır;
//    kod-hasta eşleştirme listesi sitede değil, sorumlu araştırmacıda tutulur.
//  - Etik kurul onay numarası girilmemiş çalışmada veri girişi kapalıdır.
//  - Her kayıt/düzenleme/silme işlemi denetim kaydına (audit_log) yazılır.
export default async function DataEntry({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const study = studies.find((s) => s.slug === slug);
  if (!study) notFound();

  const ethicsOk = Boolean(study.ethicsApprovalNo);

  return (
    <div className="max-w-3xl space-y-6">
      <Link href={`/calismalar/${study.slug}`} className="text-sm text-brand">← {study.title}</Link>
      <h1 className="text-2xl font-bold">Veri Girişi: {study.title}</h1>

      <div className="rounded-xl border border-slate-200 bg-white p-5 text-sm">
        <h2 className="font-semibold">Erişim koşulları</h2>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          <li>Giriş yapmış ve bu çalışmaya <b>araştırmacı</b> rolüyle eklenmiş olmak</li>
          <li>Etik kurul onay numarasının sisteme girilmiş olması {ethicsOk ? "✅" : "❌"}</li>
          <li>Yalnızca anonim veri: kimlik bilgisi, telefon, dosya numarası girilmez</li>
        </ul>
      </div>

      <form className="space-y-4 rounded-xl border border-dashed border-slate-300 bg-white p-5 opacity-60" aria-disabled>
        <p className="text-sm font-medium">Form önizlemesi (henüz aktif değil)</p>
        <label className="block text-sm">
          Katılımcı kodu
          <input disabled placeholder="ör. HT-001" className="mt-1 block w-full rounded border px-3 py-2" />
        </label>
        <label className="block text-sm">
          Ziyaret
          <select disabled className="mt-1 block w-full rounded border px-3 py-2">
            <option>Başlangıç</option>
            <option>1. ay</option>
            <option>6. ay</option>
          </select>
        </label>
        <label className="block text-sm">
          Yaş aralığı
          <input disabled placeholder="ör. 60-64" className="mt-1 block w-full rounded border px-3 py-2" />
        </label>
        <p className="text-xs text-slate-500">
          Çalışmaya özgü alanlar (ör. EKG, eko parametreleri) mevcut uygulamadaki formlardan uyarlanacak.
        </p>
      </form>
    </div>
  );
}
