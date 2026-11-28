import Link from "next/link";
import { notFound } from "next/navigation";
import { studies } from "@/lib/content";
import { currentUserEmail } from "@/lib/supabaseServer";
import { TeamGate } from "@/components/TeamGate";

export const dynamic = "force-dynamic";

export default async function StudyDetail({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  // Girişsiz ziyaretçi, adresin geçerli bir çalışma olup olmadığını da öğrenmez.
  if (!(await currentUserEmail())) return <TeamGate next={`/calismalar/${slug}`} />;
  const study = studies.find((s) => s.slug === slug);
  if (!study) notFound();

  return (
    <div className="max-w-3xl space-y-6">
      <Link href="/calismalar" className="text-sm text-brand">← Tüm çalışmalar</Link>
      <h1 className="text-3xl font-bold">{study.title}</h1>
      <p className="text-slate-600">{study.summary}</p>

      <dl className="grid grid-cols-2 gap-4 rounded-xl border border-slate-200 bg-white p-5 text-sm">
        <dt className="text-slate-500">Alan</dt><dd>{study.area}</dd>
        <dt className="text-slate-500">Durum</dt><dd>{study.status}</dd>
        {study.ethicsApprovalNo && (<><dt className="text-slate-500">Etik kurul onay no</dt><dd>{study.ethicsApprovalNo}</dd></>)}
      </dl>

      <section className="rounded-xl bg-amber-50 p-5 text-sm text-amber-900">
        <h2 className="font-semibold">Katılımcılar için bilgilendirme</h2>
        <p className="mt-1">
          Bu bölümde çalışmanın amacı, kimlerin katılabileceği, gönüllülük esası ve verilerin nasıl korunduğu
          etik kurulun onayladığı metinle birebir aynı olacak şekilde yayımlanacaktır.
        </p>
      </section>

      <Link
        href={`/calismalar/${study.slug}/veri-girisi`}
        className="inline-block rounded bg-brand px-4 py-2 text-white hover:bg-brand-dark"
      >
        Veri girişi (yetkili ekip)
      </Link>
    </div>
  );
}
