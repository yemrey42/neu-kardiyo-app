// Örnek içerik. Supabase bağlandığında bu veriler veritabanından okunacak
// (bkz. supabase/schema.sql). Şimdilik iskeletin görünmesi için statik tutuluyor.

export type NewsItem = {
  slug: string;
  title: string;
  date: string; // ISO
  summary: string;
  body: string;
};

export const news: NewsItem[] = [
  {
    slug: "web-sitemiz-yayinda",
    title: "Klinik web sitemiz hazırlanıyor",
    date: "2026-11-27",
    summary: "Haberler, literatür, eğitim, soru bankası ve klinik çalışmalar tek çatı altında.",
    body:
      "NEÜ Kardiyoloji Kliniği'nin yeni web sitesi hazırlık aşamasındadır. Klinik içi duyurular, eğitim içerikleri ve yürütülen çalışmalar bu sitede yer alacaktır.",
  },
  {
    slug: "haftalik-egitim-programi",
    title: "Haftalık eğitim toplantıları",
    date: "2026-11-20",
    summary: "Asistan eğitim programı ve olgu sunumu takvimi.",
    body: "Eğitim toplantılarının takvimi bu alanda duyurulacaktır.",
  },
];

export type LiteratureItem = {
  title: string;
  journal: string;
  date: string;
  topic: string;
  summary: string;
  url?: string;
};

export const literature: LiteratureItem[] = [
  {
    title: "Örnek: Kalp yetersizliği kılavuz güncellemesi",
    journal: "Kılavuz",
    date: "2026-11",
    topic: "Kalp yetersizliği",
    summary: "Klinik ekibin hazırladığı kısa özet ve 'pratiğimize etkisi' notu burada yer alacak.",
  },
  {
    title: "Örnek: İleti sistemi pacing (LBBAP) güncel veriler",
    journal: "Derleme",
    date: "2026-10",
    topic: "Elektrofizyoloji",
    summary: "Kliniğimizde yürüyen pacing çalışmasıyla ilişkili güncel yayınlar.",
  },
];

// Eğitim araçları. Simülasyonlar Streamlit uygulamasından taşındı (public/simulasyon/*.html);
// diyastolik fonksiyon modülü yeni sitede sıfırdan yazıldı.
export type EducationTool = { slug: string; title: string; kind: string; desc: string; file?: string };

export const educationTools: EducationTool[] = [
  {
    slug: "diyastolik-fonksiyon",
    title: "Diyastolik Fonksiyon",
    kind: "Görsel hesaplayıcı",
    desc: "Elinizdeki eko ölçümleriyle dolum basıncı ve evre; eksik parametrede ne yapılacağı, AF ve tuzaklar.",
  },
  {
    slug: "kateterizasyon",
    title: "Kateterizasyon Simülasyonu",
    kind: "Simülasyon",
    desc: "Sağ ve sol kalp kateterizasyonu: kateter pozisyonuna göre basınç dalgaları ve EKG.",
    file: "/simulasyon/kateterizasyon.html",
  },
  {
    slug: "transseptal-ponksiyon",
    title: "Transseptal Ponksiyon Simülasyonu",
    kind: "Simülasyon",
    desc: "Floroskopi ve TEE eş zamanlı: kılıfı çekme, iğneyi çevirme, çadırlanma ve ponksiyon.",
    file: "/simulasyon/transseptal.html",
  },
  {
    slug: "hemodinami",
    title: "Kateter Hemodinami Hesaplayıcı",
    kind: "Hesaplayıcı",
    desc: "Fick / termodilüsyon debi, dirençler, şant ve kapak alanı; değerler kalp çizimi üzerinde.",
    file: "/simulasyon/hemodinami.html",
  },
];

// Asistanlar İçin › Görüntüleme: teorik görüntüleme modülleri (public/moduller/*.html).
export const imagingModules: EducationTool[] = [
  {
    slug: "eko-raporlama-artefakt",
    title: "Eko Raporlama ve Artefakt Eğitimi",
    kind: "Teorik modül",
    desc: "ASE 2025'e göre standart eko raporu (algoritmalar, terimler, aciliyet, örnek raporlar) ve ASE 2026 artefakt tanıma/azaltma rehberi.",
    file: "/moduller/eko-raporlama-artefakt.html",
  },
];

// Soru şeması Streamlit soru bankasıyla aynı tutuldu:
// SoruID | Aktif | Kategori | Soru | A | B | C | D | E | Dogru | Aciklama | Kaynak
export type Study = {
  slug: string;
  title: string;
  area: string;
  summary: string;
  ethicsApprovalNo: string | null; // Opsiyonel; girilirse sayfada gösterilir ve her kayda yazılır
  status: "hazırlık" | "aktif" | "tamamlandı";
};

// Streamlit'teki "NEÜ Klinik Çalışmalar" listesi
export const studies: Study[] = [
  {
    slug: "h-type-ht",
    title: "H-Type HT Çalışması",
    area: "Hipertansiyon",
    summary: "H tipi hipertansiyon hastalarında klinik ve laboratuvar özelliklerin değerlendirilmesi.",
    ethicsApprovalNo: null,
    status: "aktif",
  },
  {
    slug: "av-blok-pacing",
    title: "AV tam blok – ileti sistemi pacing (LBBAP / HBP)",
    area: "Elektrofizyoloji",
    summary: "Tam AV blokta fizyolojik pacing yöntemlerinin kontrol grubuyla karşılaştırılması.",
    ethicsApprovalNo: null,
    status: "aktif",
  },
  {
    slug: "afmr-tee-gls",
    title: "AFMR – TEE ile LV-GLS",
    area: "Ekokardiyografi",
    summary: "Atriyal fonksiyonel mitral yetmezlikte TEE ve TTE ile LV-GLS karşılaştırması.",
    ethicsApprovalNo: null,
    status: "aktif",
  },
  {
    slug: "kv-ablasyon-tee-gls",
    title: "Kardiyoversiyon-Ablasyon / TEE-GLS",
    area: "Elektrofizyoloji",
    summary: "Elektrik kardiyoversiyon ve ablasyon öncesi-sonrası GLS ve ritim sonuçları.",
    ethicsApprovalNo: null,
    status: "aktif",
  },
  {
    slug: "pbmv-rv-pa",
    title: "PBMV – RV-PA Coupling",
    area: "Yapısal kalp",
    summary: "Perkütan balon mitral valvüloplasti öncesi ve sonrası RV-PA eşleşmesi.",
    ethicsApprovalNo: null,
    status: "aktif",
  },
];

export const academicTracking = [
  { title: "Özellikli Vakalar", desc: "Kliniğe ait ilginç olguların anonim kaydı." },
  { title: "Case Report Takip", desc: "Olgu sunumlarının yazım ve gönderim durumu." },
  { title: "Editöre Mektup Takip", desc: "Editöre mektupların hazırlık ve yayın durumu." },
];
