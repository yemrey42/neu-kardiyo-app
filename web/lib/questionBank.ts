import "server-only";
import { readFile } from "node:fs/promises";
import { googleAccessToken, googleConfigured } from "./sheets";
import { sampleQuestions } from "./sampleQuestions";
import { LETTERS, type BankQuestion, type Letter, type QuestionBankData, type QuestionKind, type QuestionMedia } from "./questionTypes";

// Soru bankası Streamlit ile aynı Google tablosundan okunur (web_app.py: MEDIA_SHEET_ID).
//  - Metin soruları: tablonun 3. sekmesi (QUESTION_WS_INDEX = 2)
//  - Fotoğraflı sorular: "Fotograflar" sekmesi (GorselDosya kolonu)
//  - Videolu sorular: "Videolar" sekmesi (VideoDosya kolonu)
// Başlıklar: SoruID | Aktif | Kategori | Soru | A | B | C | D | E | Dogru | Aciklama | Kaynak
// Yalnızca Aktif = TRUE/1/evet/yes/aktif satırlar gösterilir. Site tabloya hiçbir şey yazmaz.

const SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets";
const DEFAULT_QUESTION_SHEET_ID = "1nrAcMsjEpYmhWThlA5XfKfmCykJ_2w8zCaE00iTaXGI";
const TEXT_TAB_INDEX = 2;
const PHOTO_TAB = "Fotograflar";
const VIDEO_TAB = "Videolar";
/** Sayfa en fazla bu kadar saniyede bir tablodan yenilenir. */
export const QUESTION_REVALIDATE = 300;

const READONLY = ["https://www.googleapis.com/auth/spreadsheets.readonly"];
const ACTIVE = new Set(["true", "1", "evet", "yes", "aktif", "doğru", "dogru"]);

type Deps = { token?: string; fetch?: typeof fetch };

const norm = (s: string) =>
  s.trim().toLocaleLowerCase("tr").normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/ı/g, "i").replace(/\s+/g, "");

/** Başlık satırından kolon bulucu: "Açıklama", "aciklama", "ACIKLAMA" hepsi eşleşir. */
function columnFinder(header: string[]) {
  const map = new Map(header.map((h, i) => [norm(h), i]));
  return (row: string[], ...names: string[]) => {
    for (const n of names) {
      const i = map.get(norm(n));
      if (i !== undefined) return String(row[i] ?? "").trim();
    }
    return "";
  };
}

function driveId(url: string): string | null {
  try {
    const u = new URL(url);
    if (!/(^|\.)drive\.google\.com$/.test(u.hostname)) return null;
    const m = u.pathname.match(/\/file\/d\/([A-Za-z0-9_-]{10,})/);
    if (m) return m[1];
    const id = u.searchParams.get("id");
    return id && /^[A-Za-z0-9_-]{10,}$/.test(id) ? id : null;
  } catch {
    return null;
  }
}

function mediaFor(kind: QuestionKind, file: string, link: string): QuestionMedia | undefined {
  if (kind === "text") return undefined;
  if (file) {
    // Dosya adı Drive klasöründe aranır; dosya servis hesabıyla sunucu üzerinden aktarılır.
    const src = `/api/soru-medya?f=${encodeURIComponent(file)}`;
    return kind === "photo" ? { type: "image", src } : { type: "video", src };
  }
  if (!/^https?:\/\//i.test(link)) return undefined;
  const id = driveId(link);
  if (kind === "photo") return { type: "image", src: id ? `https://drive.google.com/thumbnail?id=${id}&sz=w1600` : link };
  return id ? { type: "iframe", src: `https://drive.google.com/file/d/${id}/preview` } : { type: "video", src: link };
}

function parseCorrect(raw: string, options: { letter: Letter; text: string }[]): Letter | null {
  const v = raw.trim();
  const up = v.toLocaleUpperCase("tr");
  if (/^[A-E]$/.test(up) || /^[A-E][).\s-]/.test(up)) return up[0] as Letter;
  // Doğru cevap seçenek metni olarak yazılmışsa
  const hit = options.find((o) => norm(o.text) === norm(v));
  return hit?.letter ?? null;
}

/** Bir sekmenin değerlerini soru listesine çevirir. Hatalı satırlar notlara eklenir. */
export function parseQuestionRows(kind: QuestionKind, values: string[][], tabLabel: string, notes: string[]): BankQuestion[] {
  if (!values.length) return [];
  const [header, ...rows] = values;
  const col = columnFinder(header);
  const prefix = kind === "text" ? "M" : kind === "photo" ? "F" : "V";
  const out: BankQuestion[] = [];
  const seen = new Set<string>();
  let skipped = 0;

  rows.forEach((row, i) => {
    if (!row.some((c) => String(c ?? "").trim())) return;
    if (!ACTIVE.has(col(row, "Aktif").toLocaleLowerCase("tr"))) return;
    const text = col(row, "Soru");
    const options = LETTERS.map((letter) => ({ letter, text: col(row, letter) })).filter((o) => o.text);
    const correct = parseCorrect(col(row, "Dogru", "Doğru", "Cevap"), options);
    const media = mediaFor(
      kind,
      kind === "photo" ? col(row, "GorselDosya", "GörselDosya", "DosyaAdi", "DosyaAdı") : col(row, "VideoDosya", "DosyaAdi", "DosyaAdı"),
      kind === "photo" ? col(row, "GorselURL", "GörselURL", "FotoURL", "ResimURL", "MedyaURL") : col(row, "VideoURL", "MedyaURL"),
    );
    if (!text || options.length < 2 || !correct || !options.some((o) => o.letter === correct) || (kind !== "text" && !media)) {
      skipped++;
      return;
    }
    let id = `${prefix}-${col(row, "SoruID") || i + 2}`;
    if (seen.has(id)) id = `${id}-${i + 2}`;
    seen.add(id);
    out.push({
      id,
      kind,
      category: col(row, "Kategori") || "Genel",
      text,
      options,
      correct,
      explanation: col(row, "Aciklama", "Açıklama"),
      source: col(row, "Kaynak") || undefined,
      media,
    });
  });
  if (skipped) notes.push(`${tabLabel}: ${skipped} aktif satır eksik bilgi (soru, en az iki seçenek, doğru cevap${kind !== "text" ? ", dosya" : ""}) nedeniyle atlandı.`);
  return out;
}

async function getJson(url: string, token: string, f: typeof fetch) {
  const res = await f(url, {
    headers: { Authorization: `Bearer ${token}` },
    next: { revalidate: QUESTION_REVALIDATE },
  } as RequestInit);
  if (!res.ok) throw new Error(`Google Sheets ${res.status}: ${(await res.text()).slice(0, 200)}`);
  return res.json();
}

/** Tablodaki aktif soruları okur. Bağlantı yoksa örnek sorularla döner (sayfa çökmez). */
export async function loadQuestionBank(deps: Deps = {}): Promise<QuestionBankData> {
  const fixture = process.env.QUESTION_BANK_FIXTURE; // yalnızca yerel deneme: Sheets yanıtı biçiminde JSON
  if (!fixture && !deps.token && !googleConfigured()) {
    return { questions: sampleQuestions, origin: "sample", notes: ["Google servis hesabı tanımlı değil."] };
  }
  const notes: string[] = [];
  try {
    let tabs: { title: string; kind: QuestionKind; label: string }[];
    let ranges: { values?: string[][] }[];
    if (fixture) {
      const data = JSON.parse(await readFile(fixture, "utf8")) as { tabs: string[]; values: Record<string, string[][]> };
      tabs = pickTabs(data.tabs.map((title, index) => ({ title, index })), notes);
      ranges = tabs.map((t) => ({ values: data.values[t.title] ?? [] }));
    } else {
      const f = deps.fetch ?? fetch;
      const token = deps.token ?? (await googleAccessToken(READONLY));
      const id = process.env.QUESTION_SHEET_ID || DEFAULT_QUESTION_SHEET_ID;
      const meta = await getJson(`${SHEETS_API}/${id}?fields=sheets.properties(title,index)`, token, f);
      tabs = pickTabs((meta.sheets ?? []).map((s: { properties: { title: string; index: number } }) => s.properties), notes);
      if (!tabs.length) throw new Error("Soru sekmesi bulunamadı.");
      const qs = tabs.map((t) => `ranges=${encodeURIComponent(`'${t.title.replace(/'/g, "''")}'`)}`).join("&");
      const data = await getJson(`${SHEETS_API}/${id}/values:batchGet?${qs}&majorDimension=ROWS`, token, f);
      ranges = data.valueRanges ?? [];
    }
    const questions = tabs.flatMap((t, i) => parseQuestionRows(t.kind, ranges[i]?.values ?? [], t.label, notes));
    if (!questions.length) {
      notes.push("Tabloda aktif soru bulunamadı.");
      return { questions: sampleQuestions, origin: "sample", notes };
    }
    return { questions, origin: "google", notes };
  } catch (e) {
    console.error("[soru-bankasi]", e);
    return { questions: sampleQuestions, origin: "sample", notes: [...notes, explain(e)] };
  }
}

function pickTabs(props: { title: string; index: number }[], notes: string[]) {
  const sorted = [...props].sort((a, b) => a.index - b.index);
  const tabs: { title: string; kind: QuestionKind; label: string }[] = [];
  const textTab = sorted[TEXT_TAB_INDEX];
  if (textTab && textTab.title !== PHOTO_TAB && textTab.title !== VIDEO_TAB) {
    tabs.push({ title: textTab.title, kind: "text", label: `"${textTab.title}" sekmesi` });
  } else notes.push("Metin soruları için 3. sekme bulunamadı.");
  for (const [title, kind] of [[PHOTO_TAB, "photo"], [VIDEO_TAB, "video"]] as const) {
    if (sorted.some((p) => p.title === title)) tabs.push({ title, kind, label: `"${title}" sekmesi` });
  }
  return tabs;
}

/** Hatayı yöneticinin anlayacağı, gizli bilgi içermeyen bir cümleye çevirir. */
function explain(e: unknown): string {
  const m = e instanceof Error ? e.message : String(e);
  if (/DECODER|PEM|asn1|private key|secretOrPrivateKey|key must be/i.test(m))
    return "Özel anahtar okunamadı: GOOGLE_PRIVATE_KEY değeri eksik veya hatalı yapıştırılmış.";
  if (/invalid_grant|invalid_client|unauthorized_client|account not found/i.test(m))
    return "Google anahtarı reddetti: e-posta ile anahtar eşleşmiyor ya da anahtar silinmiş.";
  if (/Sheets 403/.test(m)) return "Google Sheets 403: servis hesabının soru tablosuna erişimi yok veya Sheets API kapalı.";
  if (/Sheets 404/.test(m)) return "Google Sheets 404: soru tablosu bulunamadı.";
  if (/Sheets (\d+)/.test(m)) return `Google Sheets hatası (${m.match(/Sheets (\d+)/)![1]}).`;
  return "Google tablosu okunamadı.";
}
