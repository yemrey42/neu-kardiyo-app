import type { Metadata } from "next";
import { PageTitle } from "@/components/PageTitle";
import { currentUserEmail } from "@/lib/supabaseServer";
import { LoginForm } from "./LoginForm";
import { logout } from "./actions";

export const metadata: Metadata = { title: "Giriş" };
export const dynamic = "force-dynamic";

export default async function LoginPage() {
  const email = await currentUserEmail();
  return (
    <div className="max-w-md">
      <PageTitle title="Ekip Girişi" desc="Klinik çalışmalar ve Asistanlar İçin bölümü için e-posta ve şifrenizle giriş yapın." />
      {email ? (
        <form action={logout} className="space-y-3 rounded-xl border border-slate-200 bg-white p-5 text-sm">
          <p>Giriş yapıldı: <b>{email}</b></p>
          <button className="rounded border px-3 py-1">Çıkış</button>
        </form>
      ) : (
        <LoginForm />
      )}
    </div>
  );
}
