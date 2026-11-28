import { LoginForm } from "@/app/giris/LoginForm";

// Girişsiz ziyaretçiye çalışma adı, özeti veya bağlantısı gösterilmez; yalnızca giriş formu.
export function TeamGate({ next }: { next: string }) {
  return (
    <div className="grid gap-8 md:grid-cols-[1fr_auto] md:items-start">
      <div className="max-w-xl">
        <h1 className="text-3xl font-bold text-slate-900">Klinik Çalışmalar</h1>
        <p className="mt-2 text-slate-600">
          Kliniğimizde yürütülen çalışmaların listesi, ayrıntıları ve veri girişi yalnızca yetkili araştırma
          ekibine açıktır. Devam etmek için ekip e-postanız ve şifrenizle giriş yapın.
        </p>
        <p className="mt-4 text-sm text-slate-500">
          Hesabınız yoksa çalışma sorumlusundan erişim isteyin. Sitede yalnızca anonimleştirilmiş veri tutulur.
        </p>
      </div>
      <LoginForm next={next} />
    </div>
  );
}
