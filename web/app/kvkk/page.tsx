import type { Metadata } from "next";
import { PageTitle } from "@/components/PageTitle";

export const metadata: Metadata = { title: "KVKK Aydınlatma Metni" };

export default function KvkkPage() {
  return (
    <div className="max-w-3xl space-y-4 leading-relaxed">
      <PageTitle title="KVKK Aydınlatma Metni" />
      <p className="rounded bg-amber-50 p-4 text-sm text-amber-900">
        Taslak: Bu metin kurumun hukuk birimi / veri sorumlusu tarafından onaylanmadan yayına alınmamalıdır.
      </p>
      <h2 className="text-lg font-semibold">Veri sorumlusu</h2>
      <p>[Kurum adı ve iletişim bilgileri]</p>
      <h2 className="text-lg font-semibold">İşlenen veriler</h2>
      <p>
        Site ziyaretçilerinden zorunlu çerezler dışında kişisel veri toplanmaz. Ekip üyelerinin kurumsal e-posta
        adresi yalnızca giriş için işlenir. Klinik çalışma modülünde hastalara ait kimliği belirleyici hiçbir bilgi
        tutulmaz; veriler çalışmaya özel takma kodlarla, etik kurul onayı kapsamında kaydedilir.
      </p>
      <h2 className="text-lg font-semibold">Saklama yeri</h2>
      <p>Veriler Avrupa Birliği (Frankfurt) bölgesindeki sunucularda şifreli olarak saklanır.</p>
      <h2 className="text-lg font-semibold">Haklarınız</h2>
      <p>KVKK m.11 kapsamındaki taleplerinizi [iletişim adresi] üzerinden iletebilirsiniz.</p>
    </div>
  );
}
