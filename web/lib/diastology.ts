// Diyastolik fonksiyon / sol ventrikül dolum basıncı değerlendirmesi.
// Kaynaklar:
//  - Nagueh SF ve ark. ASE/EACVI 2016 diyastolik fonksiyon önerileri (Algoritma A ve B, AF önerileri)
//  - Smiseth OA ve ark. EACVI 2022 uzlaşı raporu: belirsiz durumda LA rezervuar strain (LARS) < %18
// Eğitim amaçlıdır; klinik kararın yerine geçmez.

export type Rhythm = "sinus" | "af";

export type Inputs = {
  rhythm: Rhythm;
  /** LVEF < %50 ya da miyokard hastalığı var (HKMP, infiltratif, belirgin LVH, KAH ile duvar hareket bozukluğu) */
  myocardialDisease: boolean;
  age?: number;
  E?: number; // cm/s
  A?: number; // cm/s (sinüs)
  septalE?: number; // e' septal, cm/s
  lateralE?: number; // e' lateral, cm/s
  trVmax?: number; // m/s
  lavi?: number; // mL/m²
  dt?: number; // ms
  ivrt?: number; // ms
  lars?: number; // % (LA rezervuar strain)
  pvSD?: number; // pulmoner ven S/D oranı
  arA?: number; // Ar - A süresi, ms
};

export type Light = "abnormal" | "normal" | "missing";
export type Criterion = { id: string; label: string; detail: string; value?: string; state: Light };

export type LapStatus = "normal" | "elevated" | "indeterminate";

export type Result = {
  /** Algoritma A sonucu (yalnızca EF normal + miyokard hastalığı yok + sinüs) */
  screening?: { verdict: "normal" | "dysfunction" | "indeterminate"; criteria: Criterion[]; abnormal: number; available: number };
  lap: LapStatus;
  grade?: "I" | "II" | "III";
  headline: string;
  explanation: string[];
  criteria: Criterion[];
  /** Belirsizlikte yardımcı olan ek parametreler ve kullanılıp kullanılmadığı */
  tieBreakers: Criterion[];
  nextSteps: string[];
  /** Normal diyastolik fonksiyon; dolum basıncı adımına gerek yok */
  normalFunction?: boolean;
};

const has = (v: number | undefined): v is number => typeof v === "number" && Number.isFinite(v) && v > 0;
const fmt = (v: number, d = 1) => String(Number(v.toFixed(d)));

export function averageE(i: Inputs) {
  if (has(i.septalE) && has(i.lateralE)) return (i.septalE + i.lateralE) / 2;
  return has(i.septalE) ? i.septalE : has(i.lateralE) ? i.lateralE : undefined;
}

/** E/e' — iki e' varsa ortalama; tek varsa o kullanılır (eşik buna göre değişir) */
export function eOverE(i: Inputs): { value?: number; kind: "average" | "septal" | "lateral" | "none"; cutoff: number } {
  if (!has(i.E)) return { kind: "none", cutoff: 14 };
  if (has(i.septalE) && has(i.lateralE)) return { value: i.E / ((i.septalE + i.lateralE) / 2), kind: "average", cutoff: 14 };
  if (has(i.septalE)) return { value: i.E / i.septalE, kind: "septal", cutoff: 15 };
  if (has(i.lateralE)) return { value: i.E / i.lateralE, kind: "lateral", cutoff: 13 };
  return { kind: "none", cutoff: 14 };
}

export function estimatedSPAP(trVmax?: number, rap = 5) {
  return has(trVmax) ? 4 * trVmax * trVmax + rap : undefined;
}

function crit(id: string, label: string, detail: string, test: boolean | undefined, value?: string): Criterion {
  return { id, label, detail, value, state: test === undefined ? "missing" : test ? "abnormal" : "normal" };
}

function eeCriterion(i: Inputs, cutoffOverride?: number): Criterion {
  const ee = eOverE(i);
  const cutoff = cutoffOverride ?? ee.cutoff;
  const name = ee.kind === "septal" ? "E/e' septal" : ee.kind === "lateral" ? "E/e' lateral" : "Ortalama E/e'";
  return crit("ee", name, `> ${cutoff}`, ee.value === undefined ? undefined : ee.value > cutoff, ee.value !== undefined ? fmt(ee.value) : undefined);
}

const trCriterion = (i: Inputs) =>
  crit("tr", "TR Vmax", "> 2,8 m/s", has(i.trVmax) ? i.trVmax > 2.8 : undefined, has(i.trVmax) ? `${fmt(i.trVmax, 2)} m/s` : undefined);
const laviCriterion = (i: Inputs) =>
  crit("lavi", "LAVI", "> 34 mL/m²", has(i.lavi) ? i.lavi > 34 : undefined, has(i.lavi) ? `${fmt(i.lavi, 0)} mL/m²` : undefined);

function eprimeCriterion(i: Inputs): Criterion {
  const parts: string[] = [];
  let abnormal: boolean | undefined;
  if (has(i.septalE)) {
    parts.push(`sep ${fmt(i.septalE)}`);
    abnormal = (abnormal ?? false) || i.septalE < 7;
  }
  if (has(i.lateralE)) {
    parts.push(`lat ${fmt(i.lateralE)}`);
    abnormal = (abnormal ?? false) || i.lateralE < 10;
  }
  return crit("eprime", "e' hızı", "septal < 7 ya da lateral < 10 cm/s", abnormal, parts.length ? parts.join(" / ") + " cm/s" : undefined);
}

function tieBreakersFor(i: Inputs): Criterion[] {
  const list: Criterion[] = [
    crit("lars", "LA rezervuar strain (LARS)", "< %18 ise yüksek LAP lehine", has(i.lars) ? i.lars < 18 : undefined, has(i.lars) ? `%${fmt(i.lars, 0)}` : undefined),
    crit("arA", "Ar – A süresi", "≥ 30 ms ise yüksek LVEDP lehine", typeof i.arA === "number" && Number.isFinite(i.arA) ? i.arA >= 30 : undefined,
      typeof i.arA === "number" && Number.isFinite(i.arA) ? `${fmt(i.arA, 0)} ms` : undefined),
  ];
  // S/D < 1 genç ve sağlıklı bireylerde normal olabilir; yalnızca EF düşük / miyokard hastalığında anlamlı
  if (i.myocardialDisease) {
    list.push(crit("pv", "Pulmoner ven S/D", "< 1 ise yüksek LAP lehine (EF düşükse)", has(i.pvSD) ? i.pvSD < 1 : undefined, has(i.pvSD) ? fmt(i.pvSD, 2) : undefined));
  }
  return list;
}

function decideByTieBreakers(tb: Criterion[]): LapStatus {
  const avail = tb.filter((c) => c.state !== "missing");
  if (!avail.length) return "indeterminate";
  const ab = avail.filter((c) => c.state === "abnormal").length;
  if (ab > avail.length - ab) return "elevated";
  if (ab < avail.length - ab) return "normal";
  return "indeterminate";
}

const PITFALLS_NEXT = [
  "Ölçülmeyen parametreyi tamamlayın: en çok bilgi veren genellikle TR Vmax (iyi zarflı sinyal) ve LAVI'dir.",
  "LA rezervuar strain (LARS) ölçün: < %18 yüksek dolum basıncı lehinedir (EACVI 2022).",
  "Pulmoner ven akımı: Ar – A ≥ 30 ms yüksek LVEDP lehinedir; EF düşükse S/D < 1 de yüksek LAP lehinedir.",
  "Semptom efor ile geliyorsa diyastolik stres ekosu (egzersizde ortalama E/e' > 14 ve TR > 3,4 m/s) düşünün.",
];

export function evaluate(i: Inputs): Result {
  return i.rhythm === "af" ? evaluateAF(i) : evaluateSinus(i);
}

function evaluateSinus(i: Inputs): Result {
  const explanation: string[] = [];
  let screening: Result["screening"];

  // ---- Adım 1: EF normal ve miyokard hastalığı yoksa önce diyastolik disfonksiyon var mı?
  if (!i.myocardialDisease) {
    const cs = [eprimeCriterion(i), eeCriterion(i), trCriterion(i), laviCriterion(i)];
    const available = cs.filter((c) => c.state !== "missing").length;
    const abnormal = cs.filter((c) => c.state === "abnormal").length;
    let verdict: "normal" | "dysfunction" | "indeterminate" = "indeterminate";
    if (available > 0) {
      if (abnormal / available > 0.5) verdict = "dysfunction";
      else if (abnormal / available < 0.5) verdict = "normal";
    }
    screening = { verdict, criteria: cs, abnormal, available };

    if (available < 2) {
      return {
        screening,
        lap: "indeterminate",
        headline: "Yorum için en az 2 parametre gerekli",
        explanation: ["e', E/e', TR Vmax ve LAVI'den en az ikisini girin. Ne kadar çok parametre, o kadar güvenilir sonuç."],
        criteria: cs,
        tieBreakers: tieBreakersFor(i),
        nextSteps: PITFALLS_NEXT.slice(0, 1),
      };
    }

    if (verdict === "normal") {
      return {
        screening,
        lap: "normal",
        normalFunction: true,
        headline: "Normal diyastolik fonksiyon",
        explanation: [
          `${available} ölçülebilen kriterden ${abnormal} tanesi anormal (yarısından az).`,
          "Dolum basınçları normal kabul edilir; evreleme gerekmez.",
          ...(has(i.age) && i.age >= 65 && cs[0].state === "abnormal"
            ? ["İleri yaşta e' fizyolojik olarak düşebilir; tek başına e' düşüklüğü disfonksiyon demek değildir."]
            : []),
        ],
        criteria: cs,
        tieBreakers: tieBreakersFor(i),
        nextSteps: [],
      };
    }
    explanation.push(
      verdict === "dysfunction"
        ? `Tarama: ${available} kriterden ${abnormal} tanesi anormal, diyastolik disfonksiyon var. Dolum basıncı ve evre aşağıda.`
        : `Tarama: ${available} kriterden ${abnormal} tanesi anormal (tam yarı), sonuç belirsiz. Pratikte dolum basıncı adımına geçilir.`,
    );
  }

  // ---- Adım 2: Dolum basıncı (LAP) ve evre
  const criteria = [eeCriterion(i), trCriterion(i), laviCriterion(i)];
  const tieBreakers = tieBreakersFor(i);
  const ea = has(i.E) && has(i.A) ? i.E / i.A : undefined;

  if (!has(i.E)) {
    return {
      screening,
      lap: "indeterminate",
      headline: "Mitral E dalgası gerekli",
      explanation: [...explanation, "Dolum basıncı adımı mitral E (ve sinüs ritminde A) hızıyla başlar."],
      criteria,
      tieBreakers,
      nextSteps: ["Apikal 4 boşlukta, mitral uçlarında PW Doppler ile E ve A hızını ölçün."],
    };
  }

  if (ea !== undefined && ea <= 0.8 && i.E <= 50) {
    return {
      screening,
      lap: "normal",
      grade: "I",
      headline: "Evre I – gevşeme bozukluğu, dolum basıncı normal",
      explanation: [...explanation, `E/A ${fmt(ea, 2)} (≤ 0,8) ve E ${fmt(i.E, 0)} cm/s (≤ 50): ortalama LAP normal.`],
      criteria,
      tieBreakers,
      nextSteps: [],
    };
  }
  if (ea !== undefined && ea >= 2) {
    const young = has(i.age) && i.age < 40;
    return {
      screening,
      lap: young && !i.myocardialDisease ? "indeterminate" : "elevated",
      grade: young && !i.myocardialDisease ? undefined : "III",
      headline: young && !i.myocardialDisease ? "E/A ≥ 2 – gençte normal olabilir" : "Evre III – restriktif dolum, dolum basıncı yüksek",
      explanation: [
        ...explanation,
        `E/A ${fmt(ea, 2)} (≥ 2).`,
        ...(young && !i.myocardialDisease
          ? ["40 yaş altında, özellikle sporcularda, güçlü erken gevşeme nedeniyle E/A ≥ 2 normal bulgu olabilir. Diğer kriterlerle birlikte yorumlayın."]
          : ["Bu desen kendi başına yüksek ortalama LAP göstergesidir."]),
      ],
      criteria,
      tieBreakers,
      nextSteps: young && !i.myocardialDisease ? PITFALLS_NEXT.slice(0, 2) : [],
    };
  }

  // Ara bölge: E/A ≤ 0,8 ve E > 50 ya da 0,8 < E/A < 2 (A yoksa da buraya düşer)
  const avail = criteria.filter((c) => c.state !== "missing");
  const ab = avail.filter((c) => c.state === "abnormal").length;
  const nl = avail.length - ab;
  const why = ea !== undefined ? `E/A ${fmt(ea, 2)}, E ${fmt(i.E, 0)} cm/s: ara bölge, üç kritere bakılır.` : "A ölçülmemiş: üç kritere bakılır.";

  let lap: LapStatus = "indeterminate";
  const lines = [...explanation, why];
  if (avail.length >= 2 && ab >= 2) lap = "elevated";
  else if (avail.length >= 2 && nl >= 2) lap = "normal";
  else {
    lines.push(
      avail.length < 2
        ? `Üç kriterden yalnızca ${avail.length} tanesi ölçülebildi, karar için yetmez.`
        : "Ölçülen iki kriterden biri anormal, biri normal: belirsiz.",
    );
    const tb = decideByTieBreakers(tieBreakers);
    if (tb !== "indeterminate") {
      lap = tb;
      lines.push(`Ek parametreler (${tieBreakers.filter((c) => c.state !== "missing").map((c) => c.label).join(", ")}) kararı ${tb === "elevated" ? "yüksek" : "normal"} LAP yönüne getirdi.`);
    }
  }
  if (lap === "elevated") lines.push(`${ab} kriter anormal: ortalama LAP yüksek.`);
  if (lap === "normal" && ab < 2 && avail.length >= 2) lines.push(`${nl} kriter normal: ortalama LAP normal.`);

  return {
    screening,
    lap,
    grade: lap === "elevated" ? "II" : lap === "normal" ? "I" : undefined,
    headline:
      lap === "elevated"
        ? "Evre II – psödonormal dolum, dolum basıncı yüksek"
        : lap === "normal"
          ? "Evre I – gevşeme bozukluğu, dolum basıncı normal"
          : "Dolum basıncı belirsiz",
    explanation: lines,
    criteria,
    tieBreakers,
    nextSteps: lap === "indeterminate" ? PITFALLS_NEXT : [],
  };
}

function evaluateAF(i: Inputs): Result {
  const ee =
    has(i.E) && has(i.septalE)
      ? crit("ees", "E/e' septal", "≥ 11", i.E / i.septalE >= 11, fmt(i.E / i.septalE))
      : crit("ees", "E/e' septal", "≥ 11", undefined);
  const criteria: Criterion[] = [
    ee,
    trCriterion(i),
    crit("dt", "Deselerasyon zamanı (DT)", "≤ 160 ms (EF düşükse)", has(i.dt) ? i.dt <= 160 : undefined, has(i.dt) ? `${fmt(i.dt, 0)} ms` : undefined),
    crit("ivrt", "IVRT", "≤ 65 ms", has(i.ivrt) ? i.ivrt <= 65 : undefined, has(i.ivrt) ? `${fmt(i.ivrt, 0)} ms` : undefined),
  ];
  const avail = criteria.filter((c) => c.state !== "missing");
  const ab = avail.filter((c) => c.state === "abnormal").length;
  let lap: LapStatus = "indeterminate";
  if (avail.length >= 2) lap = ab >= 2 ? "elevated" : ab === 0 || (avail.length >= 3 && ab === 1) ? "normal" : "indeterminate";

  return {
    lap,
    headline:
      lap === "elevated" ? "AF – dolum basıncı yüksek olası" : lap === "normal" ? "AF – dolum basıncı normal olası" : "AF – dolum basıncı belirsiz",
    explanation: [
      "AF'de evreleme yapılmaz; LAVI ve E/A kullanılamaz (LA zaten genişleyebilir, A dalgası yoktur).",
      "Ölçümler 5–10 atımın ortalaması ya da önceki iki RR aralığı benzer olan atım (indeks atım) üzerinden alınmalı.",
      avail.length < 2
        ? "En az iki parametre girin."
        : `${avail.length} parametreden ${ab} tanesi anormal${lap === "elevated" ? ": birden fazla anormal bulgu yüksek LAP lehine." : "."}`,
    ],
    criteria,
    tieBreakers: [],
    nextSteps:
      lap === "indeterminate"
        ? ["TR Vmax ve E/e' septal en pratik iki parametredir; ikisini birlikte almaya çalışın.", "Ritim kontrolü sonrası tekrar değerlendirme daha güvenilirdir."]
        : [],
  };
}

export type Preset = { id: string; label: string; inputs: Inputs };

export const PRESETS: Preset[] = [
  { id: "normal", label: "Normal (45 yaş)", inputs: { rhythm: "sinus", myocardialDisease: false, age: 45, E: 75, A: 55, septalE: 9, lateralE: 13, trVmax: 2.2, lavi: 24, dt: 190 } },
  { id: "g1", label: "Evre I", inputs: { rhythm: "sinus", myocardialDisease: true, age: 68, E: 48, A: 80, septalE: 5, lateralE: 7, trVmax: 2.4, lavi: 30, dt: 260 } },
  { id: "g2", label: "Evre II", inputs: { rhythm: "sinus", myocardialDisease: true, age: 66, E: 90, A: 70, septalE: 5, lateralE: 6.5, trVmax: 3.0, lavi: 42, dt: 170, lars: 14 } },
  { id: "g3", label: "Evre III", inputs: { rhythm: "sinus", myocardialDisease: true, age: 60, E: 110, A: 40, septalE: 4, lateralE: 5.5, trVmax: 3.3, lavi: 52, dt: 130 } },
  { id: "eksik", label: "Eksik ölçüm (TR yok)", inputs: { rhythm: "sinus", myocardialDisease: true, age: 70, E: 80, A: 85, septalE: 6, lateralE: 8, lavi: 38 } },
  { id: "af", label: "AF örneği", inputs: { rhythm: "af", myocardialDisease: false, age: 72, E: 105, septalE: 6, trVmax: 3.0, dt: 150, ivrt: 60 } },
];
