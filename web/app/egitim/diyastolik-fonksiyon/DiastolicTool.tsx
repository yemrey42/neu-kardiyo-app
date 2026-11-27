"use client";

import { useMemo, useState } from "react";
import {
  PRESETS,
  averageE,
  eOverE,
  estimatedSPAP,
  evaluate,
  type Criterion,
  type Inputs,
  type LapStatus,
} from "@/lib/diastology";

type NumKey = "age" | "E" | "A" | "septalE" | "lateralE" | "trVmax" | "lavi" | "dt" | "ivrt" | "lars" | "pvSD" | "arA";

type FieldDef = { key: NumKey; label: string; unit: string; min: number; max: number; step: number; hint?: string };

const CORE: FieldDef[] = [
  { key: "E", label: "Mitral E", unit: "cm/s", min: 20, max: 160, step: 1, hint: "PW, mitral uçları" },
  { key: "A", label: "Mitral A", unit: "cm/s", min: 15, max: 140, step: 1 },
  { key: "septalE", label: "e' septal", unit: "cm/s", min: 2, max: 20, step: 0.5, hint: "TDI" },
  { key: "lateralE", label: "e' lateral", unit: "cm/s", min: 2, max: 25, step: 0.5, hint: "TDI" },
  { key: "trVmax", label: "TR Vmax", unit: "m/s", min: 1.5, max: 5, step: 0.05, hint: "CW, en iyi zarf" },
  { key: "lavi", label: "LAVI", unit: "mL/m²", min: 12, max: 90, step: 1, hint: "biplan, LA sonu sistol" },
];
const EXTRA_SINUS: FieldDef[] = [
  { key: "lars", label: "LA rezervuar strain", unit: "%", min: 3, max: 50, step: 1, hint: "LARS" },
  { key: "arA", label: "Ar – A süresi", unit: "ms", min: -60, max: 80, step: 5, hint: "pulmoner ven" },
  { key: "pvSD", label: "Pulmoner ven S/D", unit: "", min: 0.2, max: 2.5, step: 0.05 },
  { key: "dt", label: "Deselerasyon zamanı", unit: "ms", min: 80, max: 350, step: 5 },
];
const AF_FIELDS: FieldDef[] = [
  { key: "E", label: "Mitral E", unit: "cm/s", min: 20, max: 160, step: 1, hint: "5–10 atım ort." },
  { key: "septalE", label: "e' septal", unit: "cm/s", min: 2, max: 20, step: 0.5 },
  { key: "trVmax", label: "TR Vmax", unit: "m/s", min: 1.5, max: 5, step: 0.05 },
  { key: "dt", label: "Deselerasyon zamanı", unit: "ms", min: 80, max: 350, step: 5 },
  { key: "ivrt", label: "IVRT", unit: "ms", min: 30, max: 140, step: 1 },
];

const LAP_STYLE: Record<LapStatus, { text: string; ring: string; fill: string; label: string }> = {
  normal: { text: "text-emerald-700", ring: "border-emerald-300 bg-emerald-50", fill: "#10b981", label: "Normal" },
  elevated: { text: "text-red-700", ring: "border-red-300 bg-red-50", fill: "#dc2626", label: "Yüksek" },
  indeterminate: { text: "text-amber-700", ring: "border-amber-300 bg-amber-50", fill: "#f59e0b", label: "Belirsiz" },
};

function NumberField({ def, value, onChange }: { def: FieldDef; value?: number; onChange: (v?: number) => void }) {
  const empty = value === undefined;
  return (
    <div className={`rounded-xl border p-3 ${empty ? "border-dashed border-slate-300 bg-slate-50" : "border-slate-200 bg-white"}`}>
      <div className="flex items-baseline justify-between gap-2">
        <label htmlFor={def.key} className="text-sm font-medium text-slate-700">
          {def.label}
          {def.hint && <span className="ml-1 text-xs font-normal text-slate-400">{def.hint}</span>}
        </label>
        {empty ? (
          <button type="button" className="text-xs text-brand" onClick={() => onChange(Math.round(((def.min + def.max) / 2) / def.step) * def.step)}>
            + ekle
          </button>
        ) : (
          <button type="button" className="text-xs text-slate-400 hover:text-slate-600" onClick={() => onChange(undefined)} title="Ölçülmedi">
            ölçülmedi
          </button>
        )}
      </div>
      <div className="mt-1 flex items-center gap-2">
        <input
          id={def.key}
          type="number"
          inputMode="decimal"
          step={def.step}
          value={empty ? "" : value}
          placeholder="—"
          onChange={(e) => onChange(e.target.value === "" ? undefined : Number(e.target.value))}
          className="w-20 shrink-0 rounded-md border border-slate-300 px-2 py-1 text-right font-semibold tabular-nums"
        />
        <span className="w-11 shrink-0 text-xs text-slate-500">{def.unit}</span>
        <input
          type="range"
          aria-label={def.label}
          min={def.min}
          max={def.max}
          step={def.step}
          value={empty ? def.min : value}
          disabled={empty}
          onChange={(e) => onChange(Number(e.target.value))}
          className="min-w-0 flex-1 accent-[var(--color-brand)] disabled:opacity-30"
        />
      </div>
    </div>
  );
}

/** Mitral giriş akımı (PW) ve septal doku Doppler'i (TDI) şeması */
function DopplerTrace({ inputs }: { inputs: Inputs }) {
  const W = 640;
  const af = inputs.rhythm === "af";
  const E = inputs.E ?? 0;
  const A = af ? 0 : inputs.A ?? 0;
  const dt = inputs.dt ?? (E > 0 && inputs.A && E / inputs.A >= 2 ? 140 : 190);
  const rr = af ? [720, 980, 610, 860] : [860, 860, 860];
  const total = rr.reduce((s, x) => s + x, 0);
  const pxMs = (W - 20) / total;
  const yb = 128; // PW sıfır çizgisi
  const vScale = 105 / 140; // px per cm/s

  // Her döngü: sistol ~ %38, sonra E; A, bir sonraki QRS'ten önce
  let t = 0;
  const pts: string[] = [];
  const marks: { x: number; y: number; label: string }[] = [];
  rr.forEach((len, idx) => {
    const start = t;
    const eOn = start + Math.min(330, len * 0.38);
    const ePeak = eOn + 90;
    const aOn = start + len - 150;
    const eEnd = Math.min(ePeak + dt, af ? start + len - 40 : aOn + 30);
    const x = (ms: number) => 10 + ms * pxMs;
    pts.push(`M${x(eOn)},${yb}`, `Q${x(eOn + 55)},${yb - E * vScale * 1.02} ${x(ePeak)},${yb - E * vScale}`, `L${x(eEnd)},${yb}`, "Z");
    if (E) marks.push({ x: x(ePeak), y: yb - E * vScale - 6, label: idx === 0 ? "E" : "" });
    if (!af && A) {
      const aPeak = aOn + 70;
      pts.push(`M${x(aOn)},${yb}`, `Q${x(aOn + 45)},${yb - A * vScale * 1.02} ${x(aPeak)},${yb - A * vScale}`, `Q${x(aOn + 110)},${yb - A * vScale * 0.6} ${x(aOn + 140)},${yb}`, "Z");
      marks.push({ x: x(aPeak), y: yb - A * vScale - 6, label: idx === 0 ? "A" : "" });
    }
    t += len;
  });

  // TDI (septal): s' yukarı, e' ve a' aşağı
  const ep = inputs.septalE ?? averageE(inputs) ?? 0;
  const yt = 205;
  const tScale = 42 / 15;
  const tdi: string[] = [];
  t = 0;
  rr.forEach((len) => {
    const x = (ms: number) => 10 + ms * pxMs;
    const s0 = t + 60;
    tdi.push(`M${x(s0)},${yt}`, `L${x(s0 + 90)},${yt - 8 * tScale}`, `L${x(s0 + 220)},${yt}`);
    const eOn = t + Math.min(330, len * 0.38) + 10;
    tdi.push(`M${x(eOn)},${yt}`, `L${x(eOn + 70)},${yt + ep * tScale}`, `L${x(eOn + 170)},${yt}`);
    if (!af) {
      const aOn = t + len - 140;
      tdi.push(`M${x(aOn)},${yt}`, `L${x(aOn + 60)},${yt + 9 * tScale}`, `L${x(aOn + 120)},${yt}`);
    }
    t += len;
  });

  // EKG
  const ecg: string[] = [];
  t = 0;
  rr.forEach((len) => {
    const x = (ms: number) => 10 + ms * pxMs;
    const y0 = 16;
    ecg.push(`M${x(t)},${y0}`, `L${x(t + 20)},${y0 - 12}`, `L${x(t + 40)},${y0 + 6}`, `L${x(t + 55)},${y0}`, `L${x(t + len)},${y0}`);
    t += len;
  });

  return (
    <svg viewBox={`0 0 ${W} 260`} className="w-full rounded-2xl bg-slate-950" role="img" aria-label="Mitral giriş akımı ve doku Doppler şeması">
      <path d={ecg.join(" ")} fill="none" stroke="#4ade80" strokeWidth="1.5" />
      <text x="12" y={yb + 14} fill="#94a3b8" fontSize="10">Mitral giriş akımı (PW)</text>
      <line x1="8" x2={W - 8} y1={yb} y2={yb} stroke="#475569" strokeDasharray="3 3" />
      {[50, 100].map((v) => (
        <g key={v}>
          <line x1={W - 40} x2={W - 8} y1={yb - v * vScale} y2={yb - v * vScale} stroke="#334155" />
          <text x={W - 10} y={yb - v * vScale - 2} fill="#64748b" fontSize="9" textAnchor="end">{v}</text>
        </g>
      ))}
      <defs>
        <linearGradient id="pw" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#f8fafc" stopOpacity="0.9" />
          <stop offset="1" stopColor="#94a3b8" stopOpacity="0.15" />
        </linearGradient>
      </defs>
      <path d={pts.join(" ")} fill="url(#pw)" stroke="#f1f5f9" strokeWidth="1.2" strokeLinejoin="round" />
      {marks.filter((m) => m.label).map((m) => (
        <text key={m.label} x={m.x} y={m.y} fill="#fca5a5" fontSize="12" fontWeight="700" textAnchor="middle">{m.label}</text>
      ))}
      <text x="12" y={yt - 30} fill="#94a3b8" fontSize="10">Septal doku Doppler (TDI){!af && " · a' temsili"}</text>
      <line x1="8" x2={W - 8} y1={yt} y2={yt} stroke="#475569" strokeDasharray="3 3" />
      <path d={tdi.join(" ")} fill="rgba(251,191,36,0.25)" stroke="#fbbf24" strokeWidth="1.5" strokeLinejoin="round" />
      {ep > 0 && (
        <text x={10 + (Math.min(330, rr[0] * 0.38) + 80) * pxMs} y={yt + ep * tScale + 14} fill="#fde68a" fontSize="12" fontWeight="700" textAnchor="middle">e&apos;</text>
      )}
      {E === 0 && <text x={W / 2} y={yb - 40} fill="#64748b" fontSize="12" textAnchor="middle">E hızını girin</text>}
    </svg>
  );
}

/** Apikal 4 boşluk şeması (eko yerleşimi: apeks üstte, LV ekranın sağında).
 *  LA boyutu LAVI ile, rengi tahmini LAP ile değişir. */
function HeartView({ inputs, lap }: { inputs: Inputs; lap: LapStatus }) {
  const lavi = inputs.lavi;
  const r = lavi ? Math.max(22, Math.min(50, 12 + lavi * 0.75)) : 32;
  const spap = estimatedSPAP(inputs.trVmax);
  const style = LAP_STYLE[lap];
  const tr = inputs.trVmax;
  return (
    <svg viewBox="0 0 300 300" className="w-full" role="img" aria-label="Apikal dört boşluk şeması" overflow="visible">
      {/* Sektör */}
      <path d="M150 8 L 30 212 A 190 190 0 0 0 270 212 Z" fill="#0f172a" />
      {/* RV (ekranın solu) */}
      <path d="M146 30 C 118 60, 88 110, 84 150 L 140 150 C 140 110, 146 60, 146 30 Z" fill="#c7d2fe" fillOpacity="0.85" />
      <text x="118" y="125" textAnchor="middle" fontSize="11" fontWeight="700" fill="#1e1b4b">RV</text>
      {/* LV (ekranın sağı) */}
      <path d="M154 30 C 158 60, 160 110, 160 150 L 236 150 C 232 105, 196 55, 154 30 Z" fill="#fecaca" fillOpacity="0.9" />
      <text x="198" y="122" textAnchor="middle" fontSize="12" fontWeight="700" fill="#7f1d1d">LV</text>
      {/* RA */}
      <circle cx="112" cy="176" r="26" fill="#c7d2fe" fillOpacity="0.85" />
      <text x="104" y="184" textAnchor="middle" fontSize="10" fontWeight="700" fill="#1e1b4b">RA</text>
      {/* LA */}
      <circle cx="198" cy={150 + r} r={r} fill={style.fill} fillOpacity="0.35" stroke={style.fill} strokeWidth="2.5" style={{ transition: "all .4s ease" }} />
      <text x="198" y={150 + r + 2} textAnchor="middle" fontSize="12" fontWeight="700" fill="#f8fafc">LA</text>
      <text x="198" y={150 + r + 15} textAnchor="middle" fontSize="9" fill="#e2e8f0">{inputs.rhythm === "af" ? "" : lavi ? `${lavi} mL/m²` : "LAVI ?"}</text>
      {/* Kapaklar */}
      <line x1="162" y1="150" x2="234" y2="150" stroke="#f8fafc" strokeWidth="2.5" strokeLinecap="round" />
      <line x1="86" y1="150" x2="138" y2="150" stroke="#f8fafc" strokeWidth="2.5" strokeLinecap="round" />
      {/* TR jeti */}
      {tr ? (
        <path
          d={`M126 152 Q ${132 + (tr - 2) * 3} 166, 128 ${158 + Math.min(30, tr * 7)}`}
          stroke={tr > 2.8 ? "#f87171" : "#60a5fa"}
          strokeWidth={3 + Math.max(0, tr - 2) * 3}
          fill="none"
          strokeLinecap="round"
          opacity="0.9"
        />
      ) : null}
      <text x="12" y="276" fontSize="11" fill="#334155">{tr ? `TR ${tr.toFixed(2)} m/s · sPAP ≈ ${spap?.toFixed(0)} mmHg` : "TR ölçülmedi"}</text>
      {tr ? <text x="12" y="290" fontSize="9" fill="#94a3b8">sPAP = 4v² + RAP (5 mmHg varsayıldı)</text> : null}
      {/* LAP göstergesi */}
      <g transform="translate(278 30)">
        <rect x="0" y="0" width="16" height="150" rx="8" fill="#f1f5f9" stroke="#cbd5e1" />
        <rect x="2" width="12" rx="6"
          y={lap === "elevated" ? 8 : lap === "indeterminate" ? 60 : 100}
          height={lap === "elevated" ? 140 : lap === "indeterminate" ? 88 : 48}
          fill={style.fill} style={{ transition: "all .4s ease" }} />
        <text x="8" y="166" textAnchor="middle" fontSize="10" fill="#334155">LAP</text>
      </g>
    </svg>
  );
}

function Light({ state }: { state: Criterion["state"] }) {
  const cls = state === "abnormal" ? "bg-red-500" : state === "normal" ? "bg-emerald-500" : "bg-slate-300";
  return <span className={`mt-1 inline-block h-3 w-3 shrink-0 rounded-full ${cls}`} aria-hidden />;
}

function CriteriaList({ items }: { items: Criterion[] }) {
  return (
    <ul className="space-y-2">
      {items.map((c) => (
        <li key={c.id} className="flex gap-3 text-sm">
          <Light state={c.state} />
          <div className="flex-1">
            <span className="font-medium">{c.label}</span> <span className="text-slate-500">{c.detail}</span>
          </div>
          <span className={`tabular-nums ${c.state === "missing" ? "text-slate-400" : "font-semibold"}`}>
            {c.value ?? "ölçülmedi"}
          </span>
        </li>
      ))}
    </ul>
  );
}

const PITFALLS: { title: string; text: string }[] = [
  { title: "Mitral anulus kalsifikasyonu, mitral protez/onarım", text: "e' ve E/e' güvenilmez. TR Vmax, LAVI, LARS ve pulmoner ven akımına ağırlık verin." },
  { title: "Konstriktif perikardit", text: "Lateral e' septal e''den düşük olabilir (annulus reversus); E/e' dolum basıncını olduğundan düşük gösterir." },
  { title: "Sol dal bloğu, sağ ventrikül pacing", text: "Septal e' bozulur; lateral e' kullanın ya da ortalamayı dikkatle yorumlayın." },
  { title: "Ağır/eksantrik TR, kötü zarflı TR sinyali", text: "TR Vmax düşük ölçülür. Eksik zarfı 'normal' saymayın, 'ölçülmedi' bırakın." },
  { title: "Sporcu, anemi, gebelik, bradikardi", text: "LA dilatasyonu dolum basıncı artışı olmadan da görülebilir; LAVI'yi tek başına kullanmayın." },
  { title: "Taşikardi, birinci derece AV blok", text: "E ve A birleşebilir (füzyon). A başlangıcında E hızı > 20 cm/s ise E/A yorumlanmaz." },
  { title: "Orta-ağır mitral yetmezlik/darlık", text: "E ve LAVI kapaktan etkilenir; IVRT ve Ar – A daha yararlıdır." },
];

export function DiastolicTool() {
  const [inputs, setInputs] = useState<Inputs>(PRESETS[0].inputs);
  const [showExtra, setShowExtra] = useState(false);
  const result = useMemo(() => evaluate(inputs), [inputs]);
  const style = LAP_STYLE[result.lap];
  const ee = eOverE(inputs);
  const af = inputs.rhythm === "af";

  const set = (k: NumKey) => (v?: number) => setInputs((s) => ({ ...s, [k]: v }));
  const fields = af ? AF_FIELDS : CORE;

  return (
    <div className="space-y-6">
      {/* Üst ayarlar */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="inline-flex rounded-full border border-slate-300 bg-white p-1 text-sm">
          {(["sinus", "af"] as const).map((r) => (
            <button
              key={r}
              type="button"
              onClick={() => setInputs((s) => ({ ...s, rhythm: r }))}
              className={`rounded-full px-4 py-1.5 font-medium ${inputs.rhythm === r ? "bg-brand text-white" : "text-slate-600"}`}
            >
              {r === "sinus" ? "Sinüs ritmi" : "Atriyal fibrilasyon"}
            </button>
          ))}
        </div>
        {!af && (
          <label className="flex items-center gap-2 rounded-full border border-slate-300 bg-white px-4 py-1.5 text-sm">
            <input
              type="checkbox"
              checked={inputs.myocardialDisease}
              onChange={(e) => setInputs((s) => ({ ...s, myocardialDisease: e.target.checked }))}
              className="h-4 w-4 accent-[var(--color-brand)]"
            />
            EF &lt; %50 ya da miyokard hastalığı var
          </label>
        )}
        <label className="flex items-center gap-2 text-sm text-slate-600">
          Yaş
          <input
            type="number"
            value={inputs.age ?? ""}
            onChange={(e) => setInputs((s) => ({ ...s, age: e.target.value === "" ? undefined : Number(e.target.value) }))}
            className="w-16 rounded-md border border-slate-300 px-2 py-1 text-right"
          />
        </label>
      </div>

      <div className="flex flex-wrap gap-2 text-sm">
        <span className="py-1 text-slate-500">Örnek olgular:</span>
        {PRESETS.map((p) => (
          <button
            key={p.id}
            type="button"
            onClick={() => setInputs(p.inputs)}
            className="rounded-full border border-slate-300 bg-white px-3 py-1 hover:border-brand hover:text-brand"
          >
            {p.label}
          </button>
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-[1.1fr_1fr]">
        {/* Sol: görseller */}
        <div className="space-y-4">
          <DopplerTrace inputs={inputs} />
          <div className="grid gap-4 sm:grid-cols-[1fr_1.1fr]">
            <div className="rounded-2xl border border-slate-200 bg-white p-3">
              <HeartView inputs={inputs} lap={result.lap} />
            </div>
            <div className={`rounded-2xl border-2 p-5 transition-colors ${style.ring}`} aria-live="polite">
              <p className={`text-xs font-semibold uppercase tracking-wider ${style.text}`}>
                Dolum basıncı: {style.label}
                {result.grade && ` · Evre ${result.grade}`}
              </p>
              <h3 className="mt-1 text-lg font-bold text-slate-900">{result.headline}</h3>
              <ul className="mt-2 space-y-1 text-sm text-slate-700">
                {result.explanation.map((l) => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
              {ee.value !== undefined && (
                <p className="mt-3 text-xs text-slate-500">
                  {ee.kind === "average" ? "Ortalama" : ee.kind === "septal" ? "Septal" : "Lateral"} E/e&apos; = {ee.value.toFixed(1)}
                  {inputs.E && inputs.A && !af ? ` · E/A = ${(inputs.E / inputs.A).toFixed(2)}` : ""}
                </p>
              )}
            </div>
          </div>
        </div>

        {/* Sağ: girişler ve kriterler */}
        <div className="space-y-4">
          <p className="text-sm text-slate-600">
            Elinizde ne varsa girin. Ölçemediğiniz parametreyi <b>ölçülmedi</b> bırakın; araç kalanlarla karar verir ve eksikte ne yapılacağını söyler.
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            {fields.map((d) => (
              <NumberField key={d.key} def={d} value={inputs[d.key]} onChange={set(d.key)} />
            ))}
          </div>
          {!af && (
            <div>
              <button type="button" onClick={() => setShowExtra((x) => !x)} className="text-sm font-semibold text-brand">
                {showExtra ? "▾" : "▸"} Ek parametreler (belirsizlikte yardımcı)
              </button>
              {showExtra && (
                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  {EXTRA_SINUS.map((d) => (
                    <NumberField key={d.key} def={d} value={inputs[d.key]} onChange={set(d.key)} />
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="rounded-2xl border border-slate-200 bg-white p-5">
          {result.screening && (
            <>
              <h3 className="font-semibold">1. Diyastolik disfonksiyon var mı?</h3>
              <p className="mb-3 text-xs text-slate-500">EF normal ve miyokard hastalığı yoksa: kriterlerin yarısından fazlası anormalse disfonksiyon.</p>
              <CriteriaList items={result.screening.criteria} />
              <hr className="my-4 border-slate-200" />
            </>
          )}
          {!result.normalFunction && (
            <>
              <h3 className="font-semibold">{result.screening ? "2. " : ""}Dolum basıncı kriterleri</h3>
              <p className="mb-3 text-xs text-slate-500">
                {af ? "AF'de birden fazla anormal bulgu yüksek LAP lehine." : "Ara bölgede (E/A 0,8–2): 3 kriterden ≥2 anormal → yüksek, ≥2 normal → normal."}
              </p>
              <CriteriaList items={result.criteria} />
              {result.tieBreakers.length > 0 && (
                <>
                  <h4 className="mt-4 text-sm font-semibold text-slate-700">Ek parametreler</h4>
                  <CriteriaList items={result.tieBreakers} />
                </>
              )}
            </>
          )}
        </div>

        <div className="space-y-4">
          {result.nextSteps.length > 0 && (
            <div className="rounded-2xl border border-amber-200 bg-amber-50 p-5">
              <h3 className="font-semibold text-amber-900">Pratikte şimdi ne yapmalı?</h3>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-amber-900">
                {result.nextSteps.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>
            </div>
          )}
          <div className="rounded-2xl border border-slate-200 bg-white p-5">
            <h3 className="font-semibold">Ölçüm tuzakları</h3>
            <div className="mt-2 divide-y divide-slate-100">
              {PITFALLS.map((p) => (
                <details key={p.title} className="py-2 text-sm">
                  <summary className="cursor-pointer font-medium text-slate-800">{p.title}</summary>
                  <p className="mt-1 text-slate-600">{p.text}</p>
                </details>
              ))}
            </div>
          </div>
        </div>
      </div>

      <p className="text-xs text-slate-500">
        Kaynak: ASE/EACVI 2016 diyastolik fonksiyon önerileri; LA strain için EACVI 2022 uzlaşı raporu. Eğitim amaçlıdır, klinik değerlendirmenin yerine geçmez.
      </p>
    </div>
  );
}
