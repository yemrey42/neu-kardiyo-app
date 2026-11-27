import { studyForms } from "./studyForms.data";
import type { FormSpec } from "./studyFormTypes";

export { studyForms };

export function getFormSpec(slug: string): FormSpec | undefined {
  return studyForms[slug];
}

/** Bölümleri ilk göründükleri sırayla gruplar. */
export function groupBySection(spec: FormSpec) {
  const groups = new Map<string, FormSpec["fields"]>();
  for (const f of spec.fields) {
    const name = f.section || "Diğer";
    if (!groups.has(name)) groups.set(name, []);
    groups.get(name)!.push(f);
  }
  return [...groups.entries()];
}

type Row = Record<string, string>;

const num = (v: string | undefined) => {
  const n = parseFloat((v ?? "").replace(",", "."));
  return Number.isFinite(n) ? n : 0;
};
const fmt = (n: number, digits = 2) => (Number.isFinite(n) && n !== 0 ? String(Number(n.toFixed(digits))) : "");

/**
 * Streamlit'teki hesaplamaların aynısı (BMI, BSA, LAVI, PASP, TAPSE/PASP ...).
 * Hesaplanan değerler sütunlara yazılır; kullanıcı formda bunları girmez.
 */
export function computeDerived(slug: string, row: Row): Row {
  const out: Row = {};
  const boy = num(row["Boy"]);
  const kilo = num(row["Kilo"]);
  const bsa = boy > 0 && kilo > 0 ? Math.sqrt((boy * kilo) / 3600) : 0;
  out["BMI"] = boy > 0 ? fmt(kilo / (boy / 100) ** 2, 1) : "";
  out["BSA"] = fmt(bsa, 2);

  if (slug === "av-blok-pacing") {
    const laedv = num(row["LAEDV (mL)"]);
    const laesv = num(row["LAESV (mL)"]);
    const laedvi = bsa > 0 ? laedv / bsa : 0;
    const laesvi = bsa > 0 ? laesv / bsa : 0;
    out["LAEDVi (mL/m2)"] = fmt(laedvi);
    out["LAESVi (mL/m2)"] = fmt(laesvi);
    out["LAVI (mL/m2)"] = fmt(laesvi);
    out["LACi"] = laesvi > 0 ? fmt(laedvi / laesvi, 3) : "";
  }

  if (slug === "kv-ablasyon-tee-gls") {
    const ablasyon = row["İşlem"] === "Ablasyon";
    out["Primary endpoint"] = ablasyon
      ? "Ablasyon başarısı: 3 ay blanking sonrası atriyal taşiaritmi rekürrensi yok (AF/AFL/AT)"
      : "Kardiyoversiyon başarısı: 30 gün içinde AF rekürrensi yok";
    const recurrence = ablasyon ? row["Rekürrens (blanking sonrası)"] === "True" : row["Rekürrens (30 gün)"] === "True";
    out["Endpoint başarılı"] = recurrence ? "False" : "True";
  }

  if (slug === "pbmv-rv-pa") {
    const mvaPlan = num(row["MVA planimetri (cm2)"]);
    const mvaPht = num(row["MVA PHT (cm2)"]);
    out["MVA final (cm2)"] = fmt(mvaPlan > 0 ? mvaPlan : mvaPht);
    const trVmax = num(row["TR Vmax"]);
    const rap = num(row["RAP"]);
    const paspCalc = trVmax > 0 ? 4 * trVmax ** 2 + rap : 0;
    const paspManual = num(row["PASP manuel (mmHg)"]);
    const paspFinal = paspManual > 0 ? paspManual : paspCalc;
    out["PASP hesap (mmHg)"] = fmt(paspCalc, 1);
    out["PASP final (mmHg)"] = fmt(paspFinal, 1);
    const tapse = num(row["TAPSE"]);
    out["TAPSE/PASP"] = paspFinal > 0 ? fmt(tapse / paspFinal, 3) : "";
    out["RVFWLS/PASP"] = paspFinal > 0 ? fmt(Math.abs(num(row["RV FWLS (%)"])) / paspFinal, 3) : "";
    out["RVGLS/PASP"] = paspFinal > 0 ? fmt(Math.abs(num(row["RV GLS (%)"])) / paspFinal, 3) : "";
    const eda = num(row["RV EDA (cm2)"]);
    const esa = num(row["RV ESA (cm2)"]);
    out["RV FAC hesap (%)"] = eda > 0 ? fmt(((eda - esa) / eda) * 100, 1) : row["RV FAC (%)"] ?? "";
    out["LAVI (mL/m2)"] = bsa > 0 ? fmt(num(row["LAESV (mL)"]) / bsa, 1) : "";
  }
  return out;
}
