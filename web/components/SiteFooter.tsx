import Link from "next/link";

export function SiteFooter() {
  return (
    <footer className="mt-16 border-t border-slate-200 bg-white">
      <div className="mx-auto flex max-w-6xl flex-wrap justify-between gap-4 px-4 py-6 text-sm text-slate-500">
        <p>© {new Date().getFullYear()} NEÜ Kardiyoloji Kliniği</p>
        <div className="flex gap-4">
          <Link href="/kvkk" className="hover:text-brand">KVKK Aydınlatma Metni</Link>
        </div>
        <p className="w-full text-xs">
          Bu sitedeki içerikler sağlık profesyonellerine yönelik eğitim amaçlıdır; tıbbi tavsiye yerine geçmez.
        </p>
      </div>
    </footer>
  );
}
