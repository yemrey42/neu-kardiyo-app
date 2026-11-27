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

// Streamlit uygulamasında (web_app.py) bulunan eğitim araçları.
// Yeni sitede ayrı sayfalar olarak yeniden yazılacak.
export const educationTools = [
  { title: "Kateterizasyon Simülasyonu", kind: "Simülasyon", status: "taşınacak" },
  { title: "Transseptal Ponksiyon Simülasyonu", kind: "Simülasyon", status: "taşınacak" },
  { title: "Kateter Hemodinami Hesaplayıcı", kind: "Hesaplayıcı", status: "taşınacak" },
  { title: "Mitral Yetmezlik Hesaplayıcı", kind: "Hesaplayıcı", status: "taşınacak" },
  { title: "Diyastolik Disfonksiyon Hesaplayıcı", kind: "Hesaplayıcı", status: "taşınacak" },
  { title: "Kalp Atlası", kind: "Görsel içerik", status: "taşınacak" },
] as const;

// Soru şeması Streamlit soru bankasıyla aynı tutuldu:
// SoruID | Aktif | Kategori | Soru | A | B | C | D | E | Dogru | Aciklama | Kaynak
export type Question = {
  id: string;
  category: string;
  text: string;
  options: Record<"A" | "B" | "C" | "D" | "E", string>;
  correct: "A" | "B" | "C" | "D" | "E";
  explanation: string;
  source?: string;
};

export const sampleQuestions: Question[] = [
  {
    id: "Q1",
    category: "Elektrofizyoloji",
    text: "Örnek soru: Tam AV blokta kalıcı pacing için ileti sistemi pacing yöntemlerinden hangisi sol dal bölgesini hedefler?",
    options: { A: "HBP", B: "LBBAP", C: "RV apikal", D: "CRT-D", E: "Epikardiyal" },
    correct: "B",
    explanation: "LBBAP (left bundle branch area pacing) sol dal bölgesini hedefler. Bu bir örnek sorudur.",
    source: "Örnek",
  },
  {
    id: "Q2",
    category: "Kapak hastalıkları",
    text: "Örnek soru: PISA yöntemiyle hesaplanan parametre hangisidir?",
    options: { A: "EROA", B: "LVEF", C: "TAPSE", D: "E/e'", E: "LAVI" },
    correct: "A",
    explanation: "PISA yöntemi ile efektif regürjitan orifis alanı (EROA) hesaplanır. Bu bir örnek sorudur.",
    source: "Örnek",
  },
];

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
