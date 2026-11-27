import type { Metadata } from "next";
import { PageTitle } from "@/components/PageTitle";

export const metadata: Metadata = { title: "Giriş" };

export default function LoginPage() {
  return (
    <div className="max-w-md">
      <PageTitle title="Ekip Girişi" desc="Soru bankası istatistikleri, akademik takip ve veri girişi için." />
      <form className="space-y-4 rounded-xl border border-slate-200 bg-white p-6">
        <label className="block text-sm">
          Kurumsal e-posta
          <input type="email" disabled placeholder="ad.soyad@..." className="mt-1 block w-full rounded border px-3 py-2" />
        </label>
        <button disabled className="w-full rounded bg-brand px-4 py-2 text-white opacity-60">
          Giriş bağlantısı gönder
        </button>
        <p className="text-xs text-slate-500">
          Supabase bağlandığında e-posta ile şifresiz giriş (magic link) aktif olacaktır.
        </p>
      </form>
    </div>
  );
}
