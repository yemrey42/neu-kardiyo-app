// Kalp atlasında bir soruyu hangi anatomik yapıya bağlayacağımızı bulur.
// Streamlit'teki _atlas_topics kurallarının birebir karşılığı (web_app.py, "ANATOMİK SORU ATLASI").
// Öncelik: "Anatomi" / "Anatomik yapı" kolonu → Kategori → soru metni. Şıklar ve cevap konu sayılmaz.

const TERMS: Record<string, string> = {
  mitral: String.raw`\b(?:mitral\w*|miytral\w*)\b`,
  laa: String.raw`\b(?:laa|sol (?:atrial|atriyal|atrium|atriyum|aurikul\w*) (?:apend\w*|append\w*|kulakc\w*)|left atrial append\w*|sol atriyal aurikul\w*)\b`,
  hepatic: String.raw`\b(?:hepat(?:ik|ic) (?:vein\w*|ven\w*|toplardamar\w*)|karaciger ven\w*)\b`,
  aortic_valve: String.raw`\b(?:aort(?:ik|ic)? (?:kapa\w*|val[vf]\w*|darl\w*|steno\w*|yet\w*|reg[uü]\w*)|(?:bikuspi[dt]|trikuspi[dt]|bicuspi[dt]|tricuspi[dt]) aort(?:ik|ic)?(?: (?:val[vf]\w*|kapa\w*))?|tavi|tavr)\b`,
  tricuspid: String.raw`\b(?:trikuspi[dt]\w*|tricuspi[dt]\w*)\b`,
  pulmonary_valve: String.raw`\b(?:pulmon(?:er|ary|ic|ik) (?:kapa\w*|valv\w*|darl\w*|steno\w*|yet\w*|regu\w*))\b`,
  aorta: String.raw`\b(?:aort\w*|arkus aorta|ascending aorta|sinotubuler\w*|valsalva sinus\w*)\b`,
  lv: String.raw`\b(?:sol ventrik\w*|left ventric\w*|lvef|lvot)\b`,
  rv: String.raw`\b(?:sag ventrik\w*|right ventric\w*|tapse|rvot|rvfwls)\b`,
  la: String.raw`\b(?:sol atri(?:y?um|al|yal)\w*|left atri(?:um|al)\w*)\b`,
  ra: String.raw`\b(?:sag atri(?:y?um|al|yal)\w*|right atri(?:um|al)\w*)\b`,
  pa: String.raw`\b(?:pulmon(?:er|ary) (?:arter\w*|trun[kc]\w*)|ana pulmoner arter\w*|truncus pulmonalis)\b`,
  pv: String.raw`\b(?:pulmon(?:er|ary) (?:ven\w*|vein\w*)|pulmonal ven\w*)\b`,
  svc: String.raw`\b(?:v(?:ena)? [kc]a[vw]a sup\w*|superior vena cava|svc|vks|vcs)\b`,
  ivc: String.raw`\b(?:v(?:ena)? [kc]a[vw]a inf\w*|inferior vena cava|ivc|vki|vci)\b`,
  apex:
    String.raw`\b(?:apeks\w*|apex\w*|` +
    String.raw`api[kc]al(?! (?:[2345]|iki|uc|dort|bes|two|three|four|five|kesit\w*|pencere\w*|view\w*)\b)\w*|` +
    String.raw`tak[oa]\s*tsubo\w*|stres\w* (?:(?:induklu|induced) )?(?:kardiyomiyopati\w*|cardiomyopath\w*)|kirik kalp sendrom\w*)\b`,
  prosthesis:
    String.raw`\b(?:protez\w*|prosthe(?:sis|tic)\w*|biyoprotez\w*|bioprotez\w*|bioprosthe\w*|` +
    String.raw`(?:mekanik|mechanical) (?:\w+ ){0,2}(?:kapak\w*|kapag\w*|val[vf]\w*)|` +
    String.raw`paravalv\w*|pannus\w*|tavi|tavr|hasta protez uyumsuz\w*)\b`,
  valve_mass:
    String.raw`\b(?:ve[gj]etasyon\w*|vegetation\w*|endokardit\w*|endocarditis|nbte|` +
    String.raw`(?:fibroelastom|miksom|myxom)\w*|libman sacks|(?:kardiyak|intrakardiyak|intrakardiyal|valvuler|` +
    String.raw`intrakardial|kardiyal|kalpteki|kalp|kapak\w*|kapag\w*) (?:\w+ ){0,2}(?:kitle\w*|tumor\w*)|` +
    String.raw`(?:(?:kardiyak|intrakardiyak|valvuler|kapak\w*|kapag\w*|protez\w*) (?:uzerinde\w* )?tromb\w*)|` +
    String.raw`(?:cardiac|intracardiac|valvular|valve) (?:\w+ ){0,2}(?:mass\w*|tumou?r\w*|thromb\w*))\b`,
  cardiomyopathy: String.raw`\b(?:kardiyo?miyopati\w*|kardiyomyopati\w*|cardiomyopath\w*|kmp|hcm|hkm|hocm|dcm|dkm|arvc|lvnc)\b`,
  myocardium:
    String.raw`\b(?:miyokar[dt](?:i|in|ina)?(?! (?:enfarkt|infarkt|iskemi))|myocardium|kalp kas\w*|endokardit\w*|endocarditis|` +
    String.raw`(?:miyokard|myokard|myocard|perikard|pericard|miyoperikard|myopericard|perimiyokard|perimyocard)it\w*)\b`,
};
const PATTERNS = Object.fromEntries(Object.entries(TERMS).map(([k, p]) => [k, new RegExp(p)]));
const PATTERNS_G = Object.fromEntries(Object.entries(TERMS).map(([k, p]) => [k, new RegExp(p, "g")]));
const CLINICAL = new Set(["apex", "prosthesis", "valve_mass", "myocardium", "cardiomyopathy"]);
const SHORT: Record<string, string> = {
  mr: "mitral", my: "mitral", tr: "tricuspid", ty: "tricuspid",
  as: "aortic_valve", ay: "aortic_valve", ad: "aortic_valve",
  lv: "lv", rv: "rv", ra: "ra", la: "la",
};

/** Python'daki _atlas_fold: küçük harf, aksanları at, harf/rakam dışını boşluk yap. */
export function fold(value: string) {
  return value
    .toLowerCase()
    .replace(/ı/g, "i")
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function topics(value: string, asTags = false): Set<string> {
  let normalized = fold(value);
  const out = new Set<string>();
  if (!normalized) return out;
  if (asTags) {
    for (const part of value.split(/[,;|/\n]+/)) {
      const code = part.trim().toLowerCase();
      if (code in TERMS) out.add(code);
      else if (code in SHORT) out.add(SHORT[code]);
      const label = fold(part);
      if (["kitle", "kitleler", "trombus", "thrombus"].includes(label)) out.add("valve_mass");
      else if (label === "ie") (out.add("valve_mass"), out.add("myocardium"));
    }
  }
  for (const k of CLINICAL) if (PATTERNS[k].test(normalized)) out.add(k);
  // Daha özel ifadeyi (aort kapağı, LAA) önce yakala, sonra genel yapıyı (aort, sol atriyum) ara.
  for (const k of ["aortic_valve", "laa"]) {
    if (PATTERNS[k].test(normalized)) {
      out.add(k);
      normalized = normalized.replace(PATTERNS_G[k], " ");
    }
  }
  for (const k of Object.keys(TERMS)) if (!CLINICAL.has(k) && PATTERNS[k].test(normalized)) out.add(k);
  return out;
}

/** Bir sorunun atlas yapıları. tags = Anatomi kolon(lar)ı, boşsa Kategori + soru metni kullanılır. */
export function atlasRegions(tags: string, category: string, stem: string): string[] {
  let set: Set<string>;
  if (tags.trim()) set = topics(tags, true);
  else {
    const cat = topics(category, true);
    const st = topics(stem);
    set = cat.size ? new Set([...cat, ...[...st].filter((t) => CLINICAL.has(t))]) : st;
  }
  return [...set].sort();
}
