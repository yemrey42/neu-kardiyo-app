"use client";

import { useEffect, useMemo, useState } from "react";
import type { CaseMedia, ClinicalCase, Letter } from "@/lib/questionTypes";

const SEEN_KEY = "neu-vakalar-v1";

function loadSeen(): Record<string, 1> {
  try {
    return JSON.parse(localStorage.getItem(SEEN_KEY) || "{}");
  } catch {
    return {};
  }
}

export function CaseLibrary({ cases }: { cases: ClinicalCase[] }) {
  const [openId, setOpenId] = useState<string | null>(null);
  const [cat, setCat] = useState<string | null>(null);
  const [seen, setSeen] = useState<Record<string, 1>>({});

  useEffect(() => {
    setSeen(loadSeen());
    const fromHash = () => {
      const id = decodeURIComponent(location.hash.slice(1));
      setOpenId(cases.some((c) => c.id === id) ? id : null);
    };
    fromHash();
    window.addEventListener("hashchange", fromHash);
    return () => window.removeEventListener("hashchange", fromHash);
  }, [cases]);

  const markSeen = (id: string) =>
    setSeen((s) => {
      const next = { ...s, [id]: 1 as const };
      try {
        localStorage.setItem(SEEN_KEY, JSON.stringify(next));
      } catch {}
      return next;
    });

  const categories = useMemo(() => [...new Set(cases.map((c) => c.category))].sort((a, b) => a.localeCompare(b, "tr")), [cases]);
  const list = cat ? cases.filter((c) => c.category === cat) : cases;
  const open = (id: string | null) => {
    if (id) location.hash = encodeURIComponent(id);
    else history.pushState(null, "", location.pathname);
    setOpenId(id);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const idx = openId ? list.findIndex((c) => c.id === openId) : -1;
  const current = openId ? cases.find((c) => c.id === openId) : undefined;
  if (current) {
    return (
      <CaseView
        key={current.id}
        c={current}
        onBack={() => open(null)}
        onPrev={idx > 0 ? () => open(list[idx - 1].id) : undefined}
        onNext={idx >= 0 && idx < list.length - 1 ? () => open(list[idx + 1].id) : undefined}
        onReveal={() => markSeen(current.id)}
      />
    );
  }

  return (
    <div className="space-y-5">
      {categories.length > 1 && (
        <div className="flex flex-wrap gap-2">
          {[null, ...categories].map((c) => (
            <button
              key={c ?? "all"}
              type="button"
              onClick={() => setCat(c)}
              className={`rounded-full border px-3 py-1.5 text-sm transition ${
                cat === c ? "border-brand bg-brand text-white" : "border-slate-300 bg-white text-slate-700 hover:border-brand"
              }`}
            >
              {c ?? "Tümü"}
            </button>
          ))}
        </div>
      )}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {list.map((c) => (
          <button
            key={c.id}
            type="button"
            onClick={() => open(c.id)}
            className="group overflow-hidden rounded-2xl border border-slate-200 bg-white text-left transition hover:-translate-y-0.5 hover:border-brand hover:shadow-md"
          >
            <div className="relative aspect-video bg-slate-900">
              {c.media[0] ? <Thumb m={c.media[0]} /> : <span className="absolute inset-0 grid place-items-center text-sm text-slate-400">Görsel yok</span>}
              {c.media.length > 1 && (
                <span className="absolute right-2 top-2 rounded-full bg-black/60 px-2 py-0.5 text-xs text-white">{c.media.length} görüntü</span>
              )}
              {seen[c.id] && <span className="absolute left-2 top-2 rounded-full bg-emerald-600 px-2 py-0.5 text-xs font-medium text-white">Çözüldü</span>}
            </div>
            <div className="p-4">
              <p className="text-xs font-medium uppercase tracking-wide text-brand">{c.category}</p>
              {c.title && <h2 className="mt-1 font-semibold text-slate-900">{c.title}</h2>}
              <p className={`mt-1 line-clamp-3 text-sm ${c.title ? "text-slate-600" : "text-slate-800"}`}>{c.history || c.question}</p>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

/** Kartta küçük önizleme: video ise ilk kare, değilse görsel. */
function Thumb({ m }: { m: CaseMedia }) {
  const [asVideo, setAsVideo] = useState(m.type === "video");
  const [failed, setFailed] = useState(false);
  if (failed) return <span className="absolute inset-0 grid place-items-center text-sm text-slate-400">Önizleme yok</span>;
  return asVideo ? (
    <>
      <video src={`${m.src}#t=0.1`} muted playsInline preload="metadata" className="h-full w-full object-cover" onError={() => setFailed(true)} />
      <span className="absolute inset-0 grid place-items-center">
        <span className="grid h-12 w-12 place-items-center rounded-full bg-black/55 text-white">▶</span>
      </span>
    </>
  ) : (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={m.src} alt="" loading="lazy" className="h-full w-full object-cover" onError={() => (m.type === "auto" ? setAsVideo(true) : setFailed(true))} />
  );
}

function Viewer({ m }: { m: CaseMedia }) {
  const [asVideo, setAsVideo] = useState(m.type === "video");
  const [failed, setFailed] = useState(false);
  const [zoom, setZoom] = useState(false);
  if (failed) return <div className="grid aspect-video place-items-center rounded-xl bg-slate-900 text-sm text-slate-400">Görüntü yüklenemedi.</div>;
  if (asVideo)
    return <video key={m.src} src={m.src} controls autoPlay muted loop playsInline className="max-h-[70vh] w-full rounded-xl bg-black" onError={() => setFailed(true)} />;
  return (
    <>
      <button type="button" onClick={() => setZoom(true)} className="block w-full overflow-hidden rounded-xl bg-black" aria-label="Büyüt">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={m.src} alt="Vaka görüntüsü" className="mx-auto max-h-[70vh] w-auto object-contain" onError={() => (m.type === "auto" ? setAsVideo(true) : setFailed(true))} />
      </button>
      {zoom && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/90 p-4" onClick={() => setZoom(false)} role="dialog" aria-label="Büyük görüntü">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={m.src} alt="Vaka görüntüsü" className="max-h-full max-w-full object-contain" />
        </div>
      )}
    </>
  );
}

function CaseView({
  c,
  onBack,
  onPrev,
  onNext,
  onReveal,
}: {
  c: ClinicalCase;
  onBack: () => void;
  onPrev?: () => void;
  onNext?: () => void;
  onReveal: () => void;
}) {
  const [active, setActive] = useState(0);
  const [pick, setPick] = useState<Letter | null>(null);
  const [revealed, setRevealed] = useState(false);
  const reveal = () => {
    setRevealed(true);
    onReveal();
  };
  const mc = c.options && c.correct;

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3 text-sm">
        <button type="button" onClick={onBack} className="text-brand">
          ← Tüm vakalar
        </button>
        <span className="flex gap-2">
          <button type="button" disabled={!onPrev} onClick={onPrev} className="rounded-lg border border-slate-300 px-3 py-1.5 disabled:opacity-30">
            ← Önceki
          </button>
          <button type="button" disabled={!onNext} onClick={onNext} className="rounded-lg border border-slate-300 px-3 py-1.5 disabled:opacity-30">
            Sonraki →
          </button>
        </span>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <section className="space-y-3">
          {c.media.length ? <Viewer key={c.media[active].src} m={c.media[active]} /> : null}
          {c.media.length > 1 && (
            <div className="flex gap-2 overflow-x-auto pb-1">
              {c.media.map((m, i) => (
                <button
                  key={m.src}
                  type="button"
                  onClick={() => setActive(i)}
                  className={`relative h-16 w-24 shrink-0 overflow-hidden rounded-lg bg-slate-900 ${i === active ? "ring-2 ring-brand ring-offset-2" : "opacity-70 hover:opacity-100"}`}
                  aria-label={`Görüntü ${i + 1}`}
                >
                  <Thumb m={m} />
                </button>
              ))}
            </div>
          )}
        </section>

        <section className="space-y-4">
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-brand">{c.category}</p>
            {c.title && <h1 className="mt-1 text-2xl font-bold text-slate-900">{c.title}</h1>}
          </div>
          {c.history && (
            <div className="rounded-xl bg-slate-100 p-4 text-sm leading-relaxed text-slate-700">
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Öykü</p>
              <p className="whitespace-pre-line">{c.history}</p>
            </div>
          )}
          <div className="rounded-2xl border border-slate-200 bg-white p-5">
            <p className="whitespace-pre-line text-lg font-semibold leading-relaxed text-slate-900">{c.question}</p>

            {mc && (
              <div className="mt-4 space-y-2">
                {c.options!.map((o) => {
                  const isCorrect = o.letter === c.correct;
                  const picked = pick === o.letter;
                  const style = !revealed
                    ? "border-slate-200 hover:border-brand"
                    : isCorrect
                      ? "border-emerald-400 bg-emerald-50"
                      : picked
                        ? "border-red-400 bg-red-50"
                        : "border-slate-200 opacity-60";
                  return (
                    <button
                      key={o.letter}
                      type="button"
                      disabled={revealed}
                      onClick={() => (setPick(o.letter), reveal())}
                      className={`flex w-full items-start gap-3 rounded-xl border p-3 text-left text-sm transition ${style}`}
                    >
                      <span className="grid h-6 w-6 shrink-0 place-items-center rounded-md bg-slate-100 text-xs font-bold">{o.letter}</span>
                      <span>{o.text}</span>
                    </button>
                  );
                })}
              </div>
            )}

            {!revealed && !mc && (
              <button type="button" onClick={reveal} className="mt-5 w-full rounded-xl bg-brand px-4 py-3 font-semibold text-white hover:bg-brand-dark">
                Cevabı göster
              </button>
            )}

            {revealed && (
              <div className="mt-5 animate-[qin_.3s_ease-out] space-y-2 rounded-xl bg-emerald-50 p-4 text-sm text-emerald-950">
                {mc && <p className="font-semibold">{pick === c.correct ? "Doğru!" : `Doğru cevap: ${c.correct}`}</p>}
                {c.answer && (
                  <p className="whitespace-pre-line">
                    <b>Cevap: </b>
                    {c.answer}
                  </p>
                )}
                {c.explanation && <p className="whitespace-pre-line leading-relaxed">{c.explanation}</p>}
                {c.source && <p className="text-xs opacity-70">Kaynak: {c.source}</p>}
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
