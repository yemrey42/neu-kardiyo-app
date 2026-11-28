// İstemci ve sunucu tarafında ortak soru tipi (sunucuya özel kod içermez).

export const LETTERS = ["A", "B", "C", "D", "E"] as const;
export type Letter = (typeof LETTERS)[number];

export type QuestionKind = "text" | "photo" | "video";

export type QuestionMedia =
  | { type: "image"; src: string }
  | { type: "video"; src: string }
  | { type: "iframe"; src: string };

/** theory: SoruBankasi sekmesi · doppler: "doppler hemodinami" klasörü · neu: "Neu vakalar" klasörü */
export type QuestionSection = "theory" | "doppler" | "neu";

export type BankQuestion = {
  /** Sekme önekiyle benzersiz kimlik (M-12, F-3, V-1). */
  id: string;
  kind: QuestionKind;
  section?: QuestionSection;
  /** Tablodaki dosya adı (görselli sorularda). */
  mediaFile?: string;
  category: string;
  text: string;
  /** Boş seçenekler çıkarılmış hali. */
  options: { letter: Letter; text: string }[];
  correct: Letter;
  explanation: string;
  source?: string;
  media?: QuestionMedia;
  /** Kalp atlasındaki yapılar (aorta, mitral, lv ...); yalnızca metin sorularında. */
  regions?: string[];
};

export type QuestionBankData = {
  questions: BankQuestion[];
  /** "google": tablodan okundu; "sample": bağlantı yok, örnek sorular. */
  origin: "google" | "sample";
  /** Yöneticiye yönelik kısa uyarılar (eksik sekme, hatalı satır vb.). */
  notes: string[];
};

/** NEÜ vakaları kart görünümü için. */
export type CaseMedia = { src: string; type: "image" | "video" | "auto" };

export type ClinicalCase = {
  id: string;
  title: string;
  category: string;
  history: string;
  question: string;
  answer: string;
  explanation: string;
  source?: string;
  media: CaseMedia[];
  options?: { letter: Letter; text: string }[];
  correct?: Letter;
};

export function questionToCase(q: BankQuestion): ClinicalCase {
  const m = q.media;
  return {
    id: q.id,
    title: "",
    category: q.category,
    history: "",
    question: q.text,
    answer: "",
    explanation: q.explanation,
    source: q.source,
    media: m && m.type !== "iframe" ? [{ src: m.src, type: m.type }] : [],
    options: q.options,
    correct: q.correct,
  };
}
