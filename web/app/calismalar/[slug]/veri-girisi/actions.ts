"use server";

import { studies } from "@/lib/content";
import { getFormSpec, computeDerived } from "@/lib/studyForms";
import { studySheetConfig } from "@/lib/studyConfig";
import { upsertRow } from "@/lib/sheets";
import { currentUserEmail } from "@/lib/supabaseServer";

export type SaveState = { ok: boolean; message: string } | null;

// Kimlik numarası / telefon gibi görünen uzun rakam dizileri serbest metinde kabul edilmez.
const LOOKS_IDENTIFYING = /\d[\d\s-]{9,}\d/;

export async function saveRecord(slug: string, _prev: SaveState, formData: FormData): Promise<SaveState> {
  const userEmail = await currentUserEmail();
  if (!userEmail) return { ok: false, message: "Oturum süresi doldu, tekrar giriş yapın." };

  const study = studies.find((s) => s.slug === slug);
  const spec = getFormSpec(slug);
  const cfg = studySheetConfig[slug];
  if (!study || !spec || !cfg) return { ok: false, message: "Çalışma bulunamadı." };

  const code = String(formData.get("__code") ?? "").trim().toUpperCase();
  const codeRe = new RegExp(`^${cfg.codePrefix}-\\d{3,5}$`);
  if (!codeRe.test(code)) {
    return { ok: false, message: `Katılımcı kodu ${cfg.codePrefix}-001 biçiminde olmalı (ad, dosya no vb. girmeyin).` };
  }
  const visit = String(formData.get("__visit") ?? "");
  if (spec.visits.length && !spec.visits.includes(visit)) return { ok: false, message: "Ziyaret seçin." };
  const date = String(formData.get("__date") ?? "");
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return { ok: false, message: "Tarih girin." };

  const row: Record<string, string> = {};
  for (const f of spec.fields) {
    if (f.type === "checkbox") {
      row[f.key] = formData.get(f.key) ? "True" : "False";
    } else if (f.type === "multiselect") {
      row[f.key] = formData.getAll(f.key).map(String).join(", ");
    } else {
      const v = String(formData.get(f.key) ?? "").trim();
      if (f.type === "select" && v && f.options && !f.options.includes(v)) {
        return { ok: false, message: `${f.label}: geçersiz seçim.` };
      }
      if ((f.type === "text" || f.type === "textarea") && LOOKS_IDENTIFYING.test(v)) {
        return { ok: false, message: `${f.label}: telefon/kimlik numarası gibi görünen veri girilemez.` };
      }
      row[f.key] = v;
    }
  }

  const visitCode = cfg.visitCodes?.[visit];
  const recordId = [code, visitCode, visitCode ? date.replaceAll("-", "") : ""].filter(Boolean).join("_");

  const record: Record<string, string> = {
    KayıtID: recordId,
    "Katılımcı Kodu": code,
    ...(spec.visits.length ? { Ziyaret: visit } : {}),
    Tarih: date,
    ...row,
    ...computeDerived(slug, row),
    "Etik Kurul No": study.ethicsApprovalNo ?? "",
    Kaydeden: userEmail,
    "Kayıt Zamanı": new Date().toISOString(),
  };

  try {
    const result = await upsertRow(cfg.tab, record, "KayıtID");
    return { ok: true, message: result === "updated" ? `Güncellendi: ${recordId}` : `Kaydedildi: ${recordId}` };
  } catch (e) {
    console.error(e);
    return { ok: false, message: "Kayıt sırasında hata oluştu. Yöneticiye bildirin." };
  }
}
