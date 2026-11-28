import { LoginForm } from "@/app/giris/LoginForm";

const STUDIES = {
  title: "Klinik Çalışmalar",
  text: "Kliniğimizde yürütülen çalışmaların listesi, ayrıntıları ve veri girişi yalnızca yetkili araştırma ekibine açıktır. Devam etmek için ekip e-postanız ve şifrenizle giriş yapın.",
  note: "Hesabınız yoksa çalışma sorumlusundan erişim isteyin. Sitede yalnızca anonimleştirilmiş veri tutulur.",
};

// Girişsiz ziyaretçiye korunan içerik gösterilmez; yalnızca başlık ve giriş formu.
export function TeamGate({
  next,
  title = STUDIES.title,
  text = STUDIES.text,
  note = STUDIES.note,
}: {
  next: string;
  title?: string;
  text?: string;
  note?: string;
}) {
  return (
    <div className="grid gap-8 md:grid-cols-[1fr_auto] md:items-start">
      <div className="max-w-xl">
        <h1 className="text-3xl font-bold text-slate-900">{title}</h1>
        <p className="mt-2 text-slate-600">{text}</p>
        {note && <p className="mt-4 text-sm text-slate-500">{note}</p>}
      </div>
      <LoginForm next={next} />
    </div>
  );
}

/** Asistanlar İçin bölümündeki girişli sayfalar için. */
export function AssistantGate({ next, title }: { next: string; title: string }) {
  return (
    <TeamGate
      next={next}
      title={title}
      text="Bu bölüm kliniğimizin asistan ve hekimlerine açıktır. Devam etmek için e-postanız ve şifrenizle giriş yapın."
      note="Hesabınız yoksa klinik sorumlusundan erişim isteyin."
    />
  );
}
