// İstemci ve sunucu tarafında ortak soru tipi (sunucuya özel kod içermez).

export const LETTERS = ["A", "B", "C", "D", "E"] as const;
export type Letter = (typeof LETTERS)[number];

export type QuestionKind = "text" | "photo" | "video";

export type QuestionMedia =
  | { type: "image"; src: string }
  | { type: "video"; src: string }
  | { type: "iframe"; src: string };

export type BankQuestion = {
  /** Sekme önekiyle benzersiz kimlik (M-12, F-3, V-1). */
  id: string;
  kind: QuestionKind;
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

export type CaseMedia = { src: string; type: "image" | "video" | "auto" };

export type ClinicalCase = {
  id: string;
  title: string;
  category: string;
  history: string;
  question: string;
  /** Açık uçlu cevap (şıklı vakalarda boş olabilir). */
  answer: string;
  explanation: string;
  source?: string;
  media: CaseMedia[];
  options?: { letter: Letter; text: string }[];
  correct?: Letter;
};
