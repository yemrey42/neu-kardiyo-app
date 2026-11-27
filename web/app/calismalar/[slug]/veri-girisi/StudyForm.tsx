"use client";

import { useActionState } from "react";
import { saveRecord, type SaveState } from "./actions";
import type { FieldSpec, FormSpec } from "@/lib/studyFormTypes";

const input = "mt-1 block w-full rounded border border-slate-300 px-3 py-1.5 text-sm";

function Field({ f }: { f: FieldSpec }) {
  if (f.type === "checkbox") {
    return (
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" name={f.key} className="h-4 w-4" /> {f.label}
      </label>
    );
  }
  return (
    <label className="block text-sm">
      {f.label}
      {f.type === "number" && (
        <input name={f.key} type="number" inputMode="decimal" step={f.step ?? "any"} min={f.min} max={f.max} className={input} />
      )}
      {f.type === "text" && <input name={f.key} type="text" className={input} autoComplete="off" />}
      {f.type === "textarea" && <textarea name={f.key} rows={2} className={input} />}
      {f.type === "date" && <input name={f.key} type="date" className={input} />}
      {f.type === "select" && (
        <select name={f.key} className={input} defaultValue={f.options?.[0]}>
          {f.options?.map((o) => <option key={o}>{o}</option>)}
        </select>
      )}
      {f.type === "multiselect" && (
        <select name={f.key} multiple className={input}>
          {f.options?.map((o) => <option key={o}>{o}</option>)}
        </select>
      )}
    </label>
  );
}

export function StudyForm({
  slug,
  spec,
  sections,
  codePrefix,
}: {
  slug: string;
  spec: FormSpec;
  sections: [string, FieldSpec[]][];
  codePrefix: string;
}) {
  const [state, action, pending] = useActionState<SaveState, FormData>(saveRecord.bind(null, slug), null);
  const today = new Date().toISOString().slice(0, 10);

  return (
    <form action={action} className="space-y-6">
      <fieldset className="grid gap-4 rounded-xl border border-slate-200 bg-white p-5 sm:grid-cols-3">
        <legend className="px-1 font-semibold">Kayıt</legend>
        <label className="block text-sm">
          Katılımcı kodu
          <input name="__code" required placeholder={`${codePrefix}-001`} pattern={`${codePrefix}-[0-9]{3,5}`}
            className={input} autoComplete="off" />
          <span className="text-xs text-slate-500">Ad, dosya no, telefon girmeyin.</span>
        </label>
        {spec.visits.length > 0 && (
          <label className="block text-sm">
            Ziyaret
            <select name="__visit" className={input}>
              {spec.visits.map((v) => <option key={v}>{v}</option>)}
            </select>
          </label>
        )}
        <label className="block text-sm">
          Tarih
          <input name="__date" type="date" required defaultValue={today} className={input} />
        </label>
      </fieldset>

      {sections.map(([name, fields]) => (
        <fieldset key={name} className="rounded-xl border border-slate-200 bg-white p-5">
          <legend className="px-1 font-semibold">{name}</legend>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {fields.map((f) => <Field key={f.key} f={f} />)}
          </div>
        </fieldset>
      ))}

      {spec.computed.length > 0 && (
        <p className="text-xs text-slate-500">Otomatik hesaplanır: {spec.computed.join(", ")}</p>
      )}

      <div className="sticky bottom-0 flex items-center gap-4 border-t border-slate-200 bg-slate-50 py-3">
        <button disabled={pending} className="rounded bg-brand px-5 py-2 text-white disabled:opacity-60">
          {pending ? "Kaydediliyor..." : "Kaydet"}
        </button>
        {state && <p className={`text-sm ${state.ok ? "text-green-700" : "text-red-700"}`}>{state.message}</p>}
      </div>
      <p className="text-xs text-slate-500">
        Aynı katılımcı kodu, ziyaret ve tarihle tekrar kaydederseniz mevcut satır güncellenir.
      </p>
    </form>
  );
}
