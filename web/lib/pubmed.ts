import "server-only";

// PubMed E-utilities (ücretsiz). Sonuçlar Next.js veri önbelleğinde 24 saat tutulur;
// böylece site PubMed'e günde yaklaşık bir kez gider.
// İsteğe bağlı: NCBI_API_KEY (ncbi.nlm.nih.gov hesabından, saniyede 10 istek hakkı verir).

const BASE = process.env.PUBMED_BASE_URL ?? "https://eutils.ncbi.nlm.nih.gov/entrez/eutils";
const REVALIDATE = 60 * 60 * 24;

export type Article = {
  pmid: string;
  title: string;
  journal: string;
  date: string;
  authors: string;
  doi?: string;
  url: string;
};

export const JOURNALS = [
  "N Engl J Med",
  "Lancet",
  "JAMA",
  "Circulation",
  "Eur Heart J",
  "J Am Coll Cardiol",
  "JACC Heart Fail",
  "JACC Cardiovasc Interv",
  "JACC Clin Electrophysiol",
  "JACC Cardiovasc Imaging",
  "Eur J Heart Fail",
  "Europace",
  "Heart Rhythm",
  "EuroIntervention",
  "Eur Heart J Cardiovasc Imaging",
  "J Am Soc Echocardiogr",
  "Anatol J Cardiol",
];

export const TOPICS: { slug: string; label: string; term: string }[] = [
  { slug: "tumu", label: "Tümü", term: "" },
  { slug: "kalp-yetersizligi", label: "Kalp yetersizliği", term: '"Heart Failure"[mh] OR "heart failure"[tiab]' },
  { slug: "elektrofizyoloji", label: "Elektrofizyoloji", term: '"Arrhythmias, Cardiac"[mh] OR "atrial fibrillation"[tiab] OR "pacing"[tiab] OR "ablation"[tiab]' },
  { slug: "koroner", label: "Koroner / girişimsel", term: '"Coronary Artery Disease"[mh] OR "Percutaneous Coronary Intervention"[mh] OR "acute coronary syndrome"[tiab]' },
  { slug: "kapak", label: "Kapak / yapısal", term: '"Heart Valve Diseases"[mh] OR "TAVI"[tiab] OR "TAVR"[tiab] OR "mitral"[tiab]' },
  { slug: "goruntuleme", label: "Görüntüleme", term: '"Echocardiography"[mh] OR "strain"[tiab] OR "cardiac magnetic resonance"[tiab]' },
  { slug: "hipertansiyon", label: "Hipertansiyon", term: '"Hypertension"[mh]' },
];

// Kliniğin kendi yayınları (adres alanında kurum + kardiyoloji geçenler)
export const CLINIC_TERM = '("Necmettin Erbakan"[ad]) AND (cardiol*[ad])';

function params(extra: Record<string, string>) {
  const p = new URLSearchParams({ db: "pubmed", retmode: "json", tool: "neu-cardio-web", ...extra });
  if (process.env.NCBI_API_KEY) p.set("api_key", process.env.NCBI_API_KEY);
  return p.toString();
}

async function getJson(url: string) {
  const res = await fetch(url, { next: { revalidate: REVALIDATE } });
  if (!res.ok) throw new Error(`PubMed ${res.status}`);
  return res.json();
}

const stripTags = (s: string) =>
  s.replace(/<[^>]+>/g, "").replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'").trim();

type Summary = {
  uid: string;
  title?: string;
  source?: string;
  pubdate?: string;
  epubdate?: string;
  authors?: { name: string }[];
  articleids?: { idtype: string; value: string }[];
  pubtype?: string[];
};

export function toArticle(s: Summary): Article {
  const authors = s.authors ?? [];
  const doi = s.articleids?.find((a) => a.idtype === "doi")?.value;
  return {
    pmid: s.uid,
    title: stripTags(s.title ?? "").replace(/\.$/, ""),
    journal: s.source ?? "",
    date: s.epubdate || s.pubdate || "",
    authors: authors.length > 3 ? `${authors[0].name} ve ark.` : authors.map((a) => a.name).join(", "),
    doi,
    url: `https://pubmed.ncbi.nlm.nih.gov/${s.uid}/`,
  };
}

// Yorum, düzeltme vb. makale dışı kayıtları ele
const SKIP_TYPES = new Set(["Comment", "Erratum", "Published Erratum", "Retraction Notice", "News", "Retracted Publication"]);

export async function searchPubMed(term: string, opts: { days?: number; max?: number } = {}): Promise<Article[]> {
  const search = await getJson(
    `${BASE}/esearch.fcgi?${params({
      term,
      sort: "pub_date",
      retmax: String(opts.max ?? 30),
      ...(opts.days ? { datetype: "edat", reldate: String(opts.days) } : {}),
    })}`,
  );
  const ids: string[] = search?.esearchresult?.idlist ?? [];
  if (ids.length === 0) return [];
  const summary = await getJson(`${BASE}/esummary.fcgi?${params({ id: ids.join(",") })}`);
  const result = summary?.result ?? {};
  return ids
    .map((uid) => result[uid] as Summary)
    .filter((s) => s && s.title && !(s.pubtype ?? []).some((t) => SKIP_TYPES.has(t)))
    .map(toArticle);
}

export function journalsTerm() {
  return "(" + JOURNALS.map((j) => `"${j}"[ta]`).join(" OR ") + ")";
}

export async function latestCardiology(topicSlug: string) {
  const topic = TOPICS.find((t) => t.slug === topicSlug) ?? TOPICS[0];
  const term = [journalsTerm(), topic.term && `(${topic.term})`, "hasabstract"].filter(Boolean).join(" AND ");
  return searchPubMed(term, { days: 14, max: 40 });
}

export async function clinicPublications() {
  return searchPubMed(CLINIC_TERM, { max: 15 });
}
