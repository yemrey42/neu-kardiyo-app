"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { BankQuestion, Letter, QuestionKind } from "@/lib/questionTypes";
import { clearProgress, loadProgress, recordAnswer, saveProgress, type Progress } from "./progress";

type Mode = "pratik" | "sinav" | "seri";

const MODES: { id: Mode; title: string; desc: string; icon: React.ReactNode }[] = [
  {
    id: "pratik",
    title: "Pratik",
    desc: "Kalp modelinde bir yapıya dokun, o yapının sorularını çöz. Açıklama hemen gelir.",
    icon: <path d="M4 12h3l2-6 4 12 2-6h5" />,
  },
  {
    id: "sinav",
    title: "Sınav",
    desc: "Süre işler, cevaplar sonda açılır. Soruları işaretleyip geri dönebilirsin.",
    icon: (
      <>
        <circle cx="12" cy="13" r="8" />
        <path d="M12 9v4l3 2M10 2h4" />
      </>
    ),
  },
  {
    id: "seri",
    title: "Seri",
    desc: "İlk yanlışa kadar devam. En uzun doğru serini geçmeye çalış.",
    icon: <path d="M12 21s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 11c0 5.6-7 10-7 10z" />,
  },
];

const KIND_LABEL: Record<QuestionKind, string> = { text: "Metin", photo: "Fotoğraflı", video: "Videolu" };
const SECONDS_PER_QUESTION = 60;

type Session = {
  mode: Mode;
  qs: BankQuestion[];
  answers: (Letter | null)[];
  revealed: boolean[];
  flagged: boolean[];
  index: number;
  startedAt: number;
  endsAt: number | null;
  finishedAt: number | null;
  streak: number;
};

function shuffle<T>(arr: T[]): T[] {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

const countBy = <T,>(items: T[], key: (t: T) => string) =>
  items.reduce<Record<string, number>>((acc, it) => ((acc[key(it)] = (acc[key(it)] ?? 0) + 1), acc), {});

function Icon({ children, className = "h-6 w-6" }: { children: React.ReactNode; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden>
      {children}
    </svg>
  );
}

function Ring({ value, size = 120, label }: { value: number; size?: number; label?: string }) {
  const r = size / 2 - 9;
  const c = 2 * Math.PI * r;
  const color = value >= 0.7 ? "#059669" : value >= 0.5 ? "#d97706" : "#b91c1c";
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={`%${Math.round(value * 100)}`}>
      <circle cx={size / 2} cy={size / 2} r={r} stroke="#e2e8f0" strokeWidth={9} fill="none" />
      {value > 0 && <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        stroke={color}
        strokeWidth={9}
        fill="none"
        strokeLinecap="round"
        strokeDasharray={`${c * value} ${c}`}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
        style={{ transition: "stroke-dasharray .6s ease" }}
      />}
      <text x="50%" y="50%" textAnchor="middle" dominantBaseline="central" className="fill-slate-900" fontSize={size / 4.4} fontWeight={700}>
        %{Math.round(value * 100)}
      </text>
      {label && (
        <text x="50%" y={size / 2 + size / 5.5} textAnchor="middle" className="fill-slate-500" fontSize={size / 11}>
          {label}
        </text>
      )}
    </svg>
  );
}

function Chip({ on, onClick, children, disabled }: { on: boolean; onClick: () => void; children: React.ReactNode; disabled?: boolean }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      aria-pressed={on}
      className={`rounded-full border px-3 py-1.5 text-sm transition disabled:opacity-40 ${
        on ? "border-brand bg-brand text-white shadow-sm" : "border-slate-300 bg-white text-slate-700 hover:border-brand"
      }`}
    >
      {children}
    </button>
  );
}

function fmtTime(sec: number) {
  const s = Math.max(0, Math.round(sec));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

// ---------------------------------------------------------------------------

export function QuestionBank({ questions, atlas = true }: { questions: BankQuestion[]; atlas?: boolean }) {
  const [progress, setProgress] = useState<Progress>({ q: {}, bestStreak: 0, sessions: 0 });
  useEffect(() => setProgress(loadProgress()), []);
  const updateProgress = useCallback((fn: (p: Progress) => Progress) => {
    setProgress((p) => {
      const next = fn(p);
      saveProgress(next);
      return next;
    });
  }, []);

  const [mode, setMode] = useState<Mode>("pratik");
  const kindsAvailable = useMemo(() => (["text", "photo", "video"] as QuestionKind[]).filter((k) => questions.some((q) => q.kind === k)), [questions]);
  const [kinds, setKinds] = useState<QuestionKind[]>(kindsAvailable);
  const [cats, setCats] = useState<string[]>([]); // boş = tümü
  const [count, setCount] = useState<number>(20);
  const [onlyWrong, setOnlyWrong] = useState(false);
  const [session, setSession] = useState<Session | null>(null);

  const byKind = useMemo(() => questions.filter((q) => kinds.includes(q.kind)), [questions, kinds]);
  const categories = useMemo(() => Object.entries(countBy(byKind, (q) => q.category)).sort((a, b) => a[0].localeCompare(b[0], "tr")), [byKind]);
  const wrongIds = useMemo(() => new Set(Object.entries(progress.q).filter(([, s]) => s.last === 0).map(([id]) => id)), [progress]);
  const pool = useMemo(
    () => byKind.filter((q) => (!cats.length || cats.includes(q.category)) && (!onlyWrong || wrongIds.has(q.id))),
    [byKind, cats, onlyWrong, wrongIds],
  );
  const take = mode === "seri" ? pool.length : Math.min(count, pool.length);

  const start = useCallback(
    (m: Mode, list: BankQuestion[], n: number) => {
      const qs = shuffle(list).slice(0, n);
      if (!qs.length) return;
      const now = Date.now();
      setSession({
        mode: m,
        qs,
        answers: qs.map(() => null),
        revealed: qs.map(() => false),
        flagged: qs.map(() => false),
        index: 0,
        startedAt: now,
        endsAt: m === "sinav" ? now + qs.length * SECONDS_PER_QUESTION * 1000 : null,
        finishedAt: null,
        streak: 0,
      });
      updateProgress((p) => ({ ...p, sessions: p.sessions + 1 }));
      window.scrollTo({ top: 0, behavior: "smooth" });
    },
    [updateProgress],
  );

  if (session && !session.finishedAt) {
    return <Player session={session} setSession={setSession} updateProgress={updateProgress} bestStreak={progress.bestStreak} />;
  }
  if (session?.finishedAt) {
    return (
      <Results
        session={session}
        bestStreak={progress.bestStreak}
        onRetryWrong={(wrong) => start("pratik", wrong, wrong.length)}
        onAgain={() => start(session.mode, pool.length ? pool : session.qs, session.mode === "seri" ? pool.length : session.qs.length)}
        onSetup={() => setSession(null)}
      />
    );
  }

  // ------------------------------- Kurulum ---------------------------------
  const solvedIds = Object.keys(progress.q).filter((id) => questions.some((q) => q.id === id));
  const solvedCorrect = solvedIds.filter((id) => progress.q[id].last === 1).length;
  const wrongAvailable = byKind.filter((q) => wrongIds.has(q.id)).length;
  const startButton = (
    <button
      type="button"
      disabled={!take}
      onClick={() => start(mode, pool, take)}
      className="rounded-xl bg-brand px-6 py-3 font-semibold text-white shadow-sm transition hover:bg-brand-dark disabled:opacity-40"
    >
      {MODES.find((m) => m.id === mode)?.title} başlat · {take} soru
    </button>
  );

  return (
    <div className="space-y-5">
      {/* Genel ilerleme: tek satır */}
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm">
        <span className="flex items-center gap-3">
          <Ring value={solvedIds.length ? solvedCorrect / solvedIds.length : 0} size={52} />
          <span className="font-semibold text-slate-900">İlerlemen</span>
        </span>
        <span className="text-slate-600">
          Çözülen <b className="tabular-nums text-slate-900">{solvedIds.length}/{questions.length}</b>
        </span>
        <span className="text-slate-600">
          Doğru <b className="tabular-nums text-slate-900">{solvedCorrect}</b>
        </span>
        <span className="text-slate-600">
          En iyi seri <b className="tabular-nums text-slate-900">{progress.bestStreak}</b>
        </span>
        <span className="ml-auto">
          <ResetButton onReset={() => setProgress(clearProgress())} disabled={!solvedIds.length} />
        </span>
      </div>

      <section>
        <div className="grid gap-3 sm:grid-cols-3">
          {MODES.map((m) => (
            <button
              key={m.id}
              type="button"
              onClick={() => setMode(m.id)}
              aria-pressed={mode === m.id}
              className={`group flex gap-3 rounded-2xl border p-4 text-left transition ${
                mode === m.id ? "border-brand bg-red-50/60 ring-2 ring-brand/20" : "border-slate-200 bg-white hover:border-slate-300"
              }`}
            >
              <span className={`inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${mode === m.id ? "bg-brand text-white" : "bg-slate-100 text-slate-600"}`}>
                <Icon>{m.icon}</Icon>
              </span>
              <span className="block min-w-0">
                <span className="block font-semibold text-slate-900">{m.title}</span>
                <span className="mt-0.5 block text-sm leading-snug text-slate-600">
                  {m.id === "pratik" && !atlas ? "Her cevaptan sonra doğrusu, açıklaması ve kaynağı hemen gelir." : m.desc}
                </span>
              </span>
            </button>
          ))}
        </div>
      </section>

      {mode === "pratik" && atlas ? (
        <section className="space-y-3">
          <HeartAtlas questions={questions} onAnswer={(id, ok) => updateProgress((p) => recordAnswer(p, id, ok))} />
          <p className="text-sm text-slate-500">
            Atlasta yeri olmayan sorular da dahil, konudan bağımsız çözmek için{" "}
            <button type="button" className="font-medium text-brand underline" onClick={() => start("pratik", byKind, Math.min(20, byKind.length))}>
              karışık pratik başlat
            </button>
            .
          </p>
        </section>
      ) : (
        <section className="space-y-4 rounded-2xl border border-slate-200 bg-white p-4 sm:p-5">
          <div className="flex flex-wrap items-center gap-4">
            {startButton}
            <p className="text-sm text-slate-500">
              {!take
                ? "Bu seçimle soru yok; filtreleri genişlet."
                : mode === "sinav"
                  ? `Süre ${fmtTime(take * SECONDS_PER_QUESTION)} (soru başına 1 dk)`
                  : mode === "seri"
                    ? `Rekorun: ${progress.bestStreak}`
                    : "Klavye: A–E ile seç, Enter ile ilerle."}
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-x-6 gap-y-3 border-t border-slate-100 pt-4 text-sm">
            {mode !== "seri" && (
              <span className="flex flex-wrap items-center gap-2">
                <span className="text-slate-500">Soru sayısı</span>
                {[10, 20, 40].map((n) => (
                  <Chip key={n} on={count === n} onClick={() => setCount(n)}>
                    {n}
                  </Chip>
                ))}
                <Chip on={count >= 9999} onClick={() => setCount(9999)}>
                  Tümü
                </Chip>
              </span>
            )}
            {kindsAvailable.length > 1 && (
              <span className="flex flex-wrap items-center gap-2">
                <span className="text-slate-500">Tür</span>
                {kindsAvailable.map((k) => (
                  <Chip
                    key={k}
                    on={kinds.includes(k)}
                    onClick={() => setKinds((ks) => (ks.includes(k) ? (ks.length > 1 ? ks.filter((x) => x !== k) : ks) : [...ks, k]))}
                  >
                    {KIND_LABEL[k]}
                  </Chip>
                ))}
              </span>
            )}
            <label className={`flex items-center gap-2 ${wrongAvailable ? "text-slate-700" : "text-slate-400"}`}>
              <input type="checkbox" className="h-4 w-4 accent-brand" checked={onlyWrong} disabled={!wrongAvailable} onChange={(e) => setOnlyWrong(e.target.checked)} />
              Yalnızca yanlışlarım ({wrongAvailable})
            </label>
          </div>

          <details className="group border-t border-slate-100 pt-3 text-sm">
            <summary className="flex cursor-pointer list-none items-center gap-2 text-slate-600">
              <span className="text-xs transition group-open:rotate-90">▶</span>
              Konu: <b className="font-medium text-slate-900">{cats.length ? cats.join(", ") : `Tümü (${byKind.length})`}</b>
            </summary>
            <div className="mt-3 flex flex-wrap gap-2">
              <Chip on={!cats.length} onClick={() => setCats([])}>
                Tümü
              </Chip>
              {categories.map(([c, n]) => (
                <Chip key={c} on={cats.includes(c)} onClick={() => setCats((cs) => (cs.includes(c) ? cs.filter((x) => x !== c) : [...cs, c]))}>
                  {c} <span className="opacity-70">· {n}</span>
                </Chip>
              ))}
            </div>
          </details>
        </section>
      )}
    </div>
  );
}

// ------------------------------- Kalp atlası -------------------------------

type AtlasEntry = { id: string; stem: string; options: [string, string][]; key: string; why: string; source: [string, string] };

function HeartAtlas({ questions, onAnswer }: { questions: BankQuestion[]; onAnswer: (id: string, correct: boolean) => void }) {
  const ref = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState(720);
  const banks = useMemo(() => {
    const out: Record<string, AtlasEntry[]> = {};
    for (const q of questions) {
      if (q.kind !== "text" || !q.regions) continue;
      const src = q.source ?? "";
      const entry: AtlasEntry = {
        id: q.id,
        stem: q.text,
        options: q.options.map((o) => [o.letter, o.text]),
        key: q.correct,
        why: q.explanation,
        source: [src, /^https?:\/\/\S+$/i.test(src) ? src : ""],
      };
      for (const r of q.regions) (out[r] ??= []).push(entry);
    }
    return out;
  }, [questions]);
  const answerRef = useRef(onAnswer);
  answerRef.current = onAnswer;

  useEffect(() => {
    const send = () => ref.current?.contentWindow?.postMessage({ type: "neu-atlas:init", banks, status: "ready" }, window.location.origin);
    const onMsg = (e: MessageEvent) => {
      if (e.origin !== window.location.origin || e.source !== ref.current?.contentWindow) return;
      const d = e.data as { type?: string; height?: number; qid?: string; correct?: boolean };
      if (d?.type === "neu-atlas:ready") send();
      else if (d?.type === "neu-atlas:height" && typeof d.height === "number") setHeight(Math.max(400, Math.min(2400, d.height)));
      else if (d?.type === "neu-atlas:answer" && typeof d.qid === "string") answerRef.current(d.qid, d.correct === true);
    };
    window.addEventListener("message", onMsg);
    send(); // iframe zaten yüklendiyse
    return () => window.removeEventListener("message", onMsg);
  }, [banks]);

  return (
    <iframe
      ref={ref}
      src="/simulasyon/kalp-atlasi.html?embed=1"
      title="Kalp atlası: yapıya dokun, sorularını çöz"
      className="block w-full rounded-2xl border border-slate-200"
      style={{ height }}
      onLoad={() => ref.current?.contentWindow?.postMessage({ type: "neu-atlas:init", banks, status: "ready" }, window.location.origin)}
    />
  );
}

function ResetButton({ onReset, disabled }: { onReset: () => void; disabled: boolean }) {
  const [ask, setAsk] = useState(false);
  if (disabled) return null;
  return ask ? (
    <p className="text-xs text-slate-600">
      İlerleme silinsin mi?{" "}
      <button className="font-semibold text-brand" onClick={() => (onReset(), setAsk(false))}>
        Evet, sil
      </button>{" "}
      ·{" "}
      <button className="underline" onClick={() => setAsk(false)}>
        Vazgeç
      </button>
    </p>
  ) : (
    <button className="text-xs text-slate-400 underline hover:text-slate-600" onClick={() => setAsk(true)}>
      İlerlemeyi sıfırla
    </button>
  );
}

// ------------------------------- Soru ekranı -------------------------------

function Player({
  session,
  setSession,
  updateProgress,
  bestStreak,
}: {
  session: Session;
  setSession: React.Dispatch<React.SetStateAction<Session | null>>;
  updateProgress: (fn: (p: Progress) => Progress) => void;
  bestStreak: number;
}) {
  const { mode, qs, index, answers, revealed } = session;
  const q = qs[index];
  const chosen = answers[index];
  const isRevealed = revealed[index];
  const exam = mode === "sinav";
  const [now, setNow] = useState(() => Date.now());
  const [pulse, setPulse] = useState(0);
  const [confirmEnd, setConfirmEnd] = useState(false);
  const topRef = useRef<HTMLDivElement>(null);

  const finish = useCallback(() => {
    setSession((s) => {
      if (!s || s.finishedAt) return s;
      if (s.mode === "sinav") {
        // Sınav sonunda tüm cevaplar ilerlemeye yazılır
        updateProgress((p) => s.qs.reduce((acc, qq, i) => (s.answers[i] ? recordAnswer(acc, qq.id, s.answers[i] === qq.correct) : acc), p));
      }
      return { ...s, finishedAt: Date.now() };
    });
  }, [setSession, updateProgress]);

  useEffect(() => {
    if (!session.endsAt) return;
    const t = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(t);
  }, [session.endsAt]);
  useEffect(() => {
    if (session.endsAt && now >= session.endsAt) finish();
  }, [now, session.endsAt, finish]);

  const goTo = useCallback(
    (i: number) => {
      setConfirmEnd(false);
      setSession((s) => (s ? { ...s, index: Math.max(0, Math.min(s.qs.length - 1, i)) } : s));
      topRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    },
    [setSession],
  );

  const choose = useCallback(
    (letter: Letter) => {
      if (!q.options.some((o) => o.letter === letter)) return;
      if (exam) {
        setSession((s) => (s ? { ...s, answers: s.answers.map((a, i) => (i === s.index ? letter : a)) } : s));
        return;
      }
      if (isRevealed) return;
      const correct = letter === q.correct;
      updateProgress((p) => {
        const next = recordAnswer(p, q.id, correct);
        const streak = correct ? session.streak + 1 : 0;
        return { ...next, bestStreak: Math.max(next.bestStreak, streak) };
      });
      if (correct) setPulse((n) => n + 1);
      setSession((s) =>
        s
          ? {
              ...s,
              answers: s.answers.map((a, i) => (i === s.index ? letter : a)),
              revealed: s.revealed.map((r, i) => (i === s.index ? true : r)),
              streak: correct ? s.streak + 1 : 0,
            }
          : s,
      );
    },
    [q, exam, isRevealed, session.streak, setSession, updateProgress],
  );

  const next = useCallback(() => {
    if (!exam && !isRevealed) return;
    const seriOver = mode === "seri" && chosen !== q.correct;
    if (seriOver || index === qs.length - 1) {
      if (exam) setConfirmEnd(true);
      else finish();
      return;
    }
    goTo(index + 1);
  }, [exam, isRevealed, mode, chosen, q, index, qs.length, finish, goTo]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLElement && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const k = e.key.toUpperCase();
      if (/^[A-E]$/.test(k)) choose(k as Letter);
      else if (/^[1-5]$/.test(k)) choose("ABCDE"[Number(k) - 1] as Letter);
      else if (e.key === "Enter") {
        e.preventDefault();
        next();
      } else if (exam && e.key === "ArrowRight") goTo(index + 1);
      else if (exam && e.key === "ArrowLeft") goTo(index - 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [choose, next, goTo, exam, index]);

  const remaining = session.endsAt ? (session.endsAt - now) / 1000 : 0;
  const answeredCount = answers.filter(Boolean).length;
  const correctSoFar = qs.filter((qq, i) => revealed[i] && answers[i] === qq.correct).length;
  const seriLost = mode === "seri" && isRevealed && chosen !== q.correct;

  return (
    <div ref={topRef} className="mx-auto max-w-3xl scroll-mt-24">
      {/* Üst bilgi çubuğu */}
      <div className="sticky top-2 z-10 -mx-4 mb-4 border-b border-slate-200 bg-slate-50/90 px-4 py-3 backdrop-blur sm:mx-0 sm:rounded-2xl sm:border sm:bg-white/90">
        <div className="flex items-center justify-between gap-3 text-sm">
          <div className="flex items-center gap-2">
            <span className="rounded-full bg-brand/10 px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide text-brand">{MODES.find((m) => m.id === mode)?.title}</span>
            <span className="font-medium tabular-nums text-slate-700">
              {mode === "seri" ? `${index + 1}. soru` : `${index + 1} / ${qs.length}`}
            </span>
          </div>
          <div className="flex items-center gap-3">
            {exam ? (
              <span className={`font-mono text-base font-semibold tabular-nums ${remaining < 60 ? "text-brand" : "text-slate-800"}`} aria-label="Kalan süre">
                {fmtTime(remaining)}
              </span>
            ) : (
              <span className="flex items-center gap-1.5 font-semibold text-slate-800" aria-label="Doğru serisi">
                <svg key={pulse} viewBox="0 0 24 24" className={`h-5 w-5 ${session.streak ? "fill-brand text-brand" : "fill-slate-200 text-slate-300"} ${pulse ? "animate-[heartbeat_0.8s_ease-in-out]" : ""}`} aria-hidden>
                  <path d="M12 21s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 11c0 5.6-7 10-7 10z" />
                </svg>
                <span className="tabular-nums">{session.streak}</span>
                {mode === "seri" && <span className="text-xs font-normal text-slate-500">/ rekor {Math.max(bestStreak, session.streak)}</span>}
              </span>
            )}
            <button type="button" onClick={exam ? () => setConfirmEnd(true) : finish} className="rounded-lg border border-slate-300 px-2.5 py-1 text-xs text-slate-600 hover:border-brand hover:text-brand">
              Bitir
            </button>
          </div>
        </div>
        {mode !== "seri" && (
          <div className="mt-2.5 flex gap-[3px]" aria-hidden>
            {qs.map((qq, i) => {
              const a = answers[i];
              const color =
                exam || !revealed[i]
                  ? a
                    ? "bg-slate-500"
                    : session.flagged[i]
                      ? "bg-amber-400"
                      : "bg-slate-200"
                  : a === qq.correct
                    ? "bg-emerald-500"
                    : "bg-red-500";
              return <span key={qq.id} className={`h-1.5 flex-1 rounded-full transition-colors ${color} ${i === index ? "ring-2 ring-brand/40 ring-offset-1" : ""}`} />;
            })}
          </div>
        )}
      </div>

      {/* Soru kartı */}
      <article key={q.id} className="animate-[qin_.35s_ease-out] rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-7">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="rounded-full bg-slate-100 px-2.5 py-1 font-medium text-slate-600">{q.category}</span>
          {q.kind !== "text" && <span className="rounded-full bg-sky-50 px-2.5 py-1 font-medium text-sky-700">{KIND_LABEL[q.kind]}</span>}
          {exam && (
            <button
              type="button"
              onClick={() => setSession((s) => (s ? { ...s, flagged: s.flagged.map((f, i) => (i === s.index ? !f : f)) } : s))}
              className={`ml-auto rounded-full px-2.5 py-1 font-medium ${session.flagged[index] ? "bg-amber-100 text-amber-800" : "text-slate-500 hover:bg-slate-100"}`}
            >
              {session.flagged[index] ? "★ İşaretli" : "☆ Sonra bak"}
            </button>
          )}
        </div>

        {q.media && <Media media={q.media} />}

        <h2 className="mt-4 whitespace-pre-line text-lg font-semibold leading-relaxed text-slate-900 sm:text-xl">{q.text}</h2>

        <div className="mt-5 space-y-2.5" role="radiogroup" aria-label="Seçenekler">
          {q.options.map((o) => {
            const picked = chosen === o.letter;
            const isCorrect = o.letter === q.correct;
            let style = "border-slate-200 bg-white hover:border-brand hover:bg-red-50/40";
            let badge = "bg-slate-100 text-slate-600";
            if (exam && picked) {
              style = "border-brand bg-red-50/70 ring-2 ring-brand/20";
              badge = "bg-brand text-white";
            } else if (!exam && isRevealed) {
              if (isCorrect) {
                style = "border-emerald-400 bg-emerald-50";
                badge = "bg-emerald-600 text-white";
              } else if (picked) {
                style = "border-red-400 bg-red-50 animate-[shake_.35s_ease-in-out]";
                badge = "bg-red-600 text-white";
              } else style = "border-slate-200 bg-white opacity-60";
            }
            return (
              <button
                key={o.letter}
                type="button"
                role="radio"
                aria-checked={picked}
                disabled={!exam && isRevealed}
                onClick={() => choose(o.letter)}
                className={`flex w-full items-start gap-3 rounded-xl border p-3.5 text-left transition sm:p-4 ${style}`}
              >
                <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-sm font-bold ${badge}`}>{o.letter}</span>
                <span className="min-w-0 pt-0.5 text-slate-800">{o.text}</span>
                {!exam && isRevealed && isCorrect && <span className="ml-auto shrink-0 pt-0.5 text-emerald-700">✓</span>}
                {!exam && isRevealed && picked && !isCorrect && <span className="ml-auto shrink-0 pt-0.5 text-red-700">✕</span>}
              </button>
            );
          })}
        </div>

        {!exam && isRevealed && (
          <div className={`mt-5 animate-[qin_.3s_ease-out] rounded-xl p-4 text-sm ${chosen === q.correct ? "bg-emerald-50 text-emerald-950" : "bg-amber-50 text-amber-950"}`}>
            <p className="font-semibold">{chosen === q.correct ? "Doğru!" : `Doğru cevap: ${q.correct}`}</p>
            {q.explanation && <p className="mt-1 whitespace-pre-line leading-relaxed">{q.explanation}</p>}
            {q.source && <p className="mt-2 text-xs opacity-70">Kaynak: {q.source}</p>}
          </div>
        )}

        {/* Alt düğmeler */}
        <div className="mt-6 flex items-center justify-between gap-3">
          {exam ? (
            <button type="button" disabled={index === 0} onClick={() => goTo(index - 1)} className="rounded-xl border border-slate-300 px-4 py-2.5 text-sm disabled:opacity-30">
              ← Önceki
            </button>
          ) : (
            <span className="text-sm tabular-nums text-slate-500">{mode === "pratik" ? `${correctSoFar} doğru` : ""}</span>
          )}
          {(exam || isRevealed) && (
            <button type="button" onClick={next} className="rounded-xl bg-brand px-5 py-2.5 text-sm font-semibold text-white hover:bg-brand-dark">
              {seriLost ? "Sonucu gör" : index === qs.length - 1 ? (exam ? "Sınavı bitir" : "Sonucu gör") : "Sonraki →"}
            </button>
          )}
        </div>
      </article>

      {exam && confirmEnd && (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
          <span>
            {qs.length - answeredCount > 0 ? `${qs.length - answeredCount} soru boş. ` : ""}Sınavı bitirmek istiyor musun?
          </span>
          <span className="flex gap-2">
            <button onClick={() => setConfirmEnd(false)} className="rounded-lg border border-amber-300 px-3 py-1.5">
              Devam et
            </button>
            <button onClick={finish} className="rounded-lg bg-brand px-3 py-1.5 font-semibold text-white">
              Bitir ve değerlendir
            </button>
          </span>
        </div>
      )}

      {exam && (
        <nav className="mt-5 rounded-2xl border border-slate-200 bg-white p-4" aria-label="Soru haritası">
          <p className="mb-3 text-xs text-slate-500">
            {answeredCount}/{qs.length} cevaplandı · ← → ile gezin
          </p>
          <div className="grid grid-cols-8 gap-1.5 sm:grid-cols-10">
            {qs.map((qq, i) => (
              <button
                key={qq.id}
                onClick={() => goTo(i)}
                className={`relative h-9 rounded-lg text-xs font-semibold tabular-nums transition ${
                  i === index ? "ring-2 ring-brand" : ""
                } ${answers[i] ? "bg-slate-700 text-white" : session.flagged[i] ? "bg-amber-200 text-amber-900" : "bg-slate-100 text-slate-600 hover:bg-slate-200"}`}
              >
                {i + 1}
                {session.flagged[i] && <span className="absolute -right-1 -top-1.5 text-[11px] text-amber-500" aria-label="işaretli">★</span>}
              </button>
            ))}
          </div>
        </nav>
      )}
    </div>
  );
}

function Media({ media }: { media: NonNullable<BankQuestion["media"]> }) {
  const [zoom, setZoom] = useState(false);
  const [failed, setFailed] = useState(false);
  if (failed) return <p className="mt-4 rounded-xl bg-slate-100 p-6 text-center text-sm text-slate-500">Görsel yüklenemedi.</p>;
  if (media.type === "image") {
    return (
      <>
        <button type="button" onClick={() => setZoom(true)} className="mt-4 block w-full overflow-hidden rounded-xl bg-slate-900" aria-label="Görseli büyüt">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={media.src} alt="Soru görseli" className="mx-auto max-h-[420px] w-auto object-contain" onError={() => setFailed(true)} />
        </button>
        {zoom && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 p-4" onClick={() => setZoom(false)} role="dialog" aria-label="Büyük görsel">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={media.src} alt="Soru görseli" className="max-h-full max-w-full object-contain" />
          </div>
        )}
      </>
    );
  }
  if (media.type === "video") {
    return <video src={media.src} controls loop playsInline preload="metadata" className="mt-4 w-full rounded-xl bg-black" onError={() => setFailed(true)} />;
  }
  return (
    <div className="mt-4 aspect-video overflow-hidden rounded-xl bg-black">
      <iframe src={media.src} title="Soru videosu" allow="autoplay" className="h-full w-full" />
    </div>
  );
}

// ------------------------------- Sonuç ekranı ------------------------------

function Results({
  session,
  bestStreak,
  onRetryWrong,
  onAgain,
  onSetup,
}: {
  session: Session;
  bestStreak: number;
  onRetryWrong: (qs: BankQuestion[]) => void;
  onAgain: () => void;
  onSetup: () => void;
}) {
  const { mode, qs, answers } = session;
  const [onlyWrong, setOnlyWrong] = useState(true);
  // Seri ve pratikte yalnızca görülen sorular sayılır
  const seenIdx = qs.map((_, i) => i).filter((i) => mode === "sinav" || session.revealed[i]);
  const correct = seenIdx.filter((i) => answers[i] === qs[i].correct);
  const wrong = seenIdx.filter((i) => answers[i] !== qs[i].correct);
  const total = mode === "sinav" ? qs.length : seenIdx.length;
  const ratio = total ? correct.length / total : 0;
  const secs = ((session.finishedAt ?? Date.now()) - session.startedAt) / 1000;
  const byCat = Object.entries(
    seenIdx.reduce<Record<string, { ok: number; n: number }>>((acc, i) => {
      const c = qs[i].category;
      acc[c] = acc[c] ?? { ok: 0, n: 0 };
      acc[c].n++;
      if (answers[i] === qs[i].correct) acc[c].ok++;
      return acc;
    }, {}),
  ).sort((a, b) => a[1].ok / a[1].n - b[1].ok / b[1].n);
  const list = onlyWrong ? wrong : seenIdx;
  const streakRun = mode === "seri" ? correct.length : 0;
  const message =
    mode === "seri"
      ? streakRun >= bestStreak && streakRun > 0
        ? "Yeni rekor!"
        : `Serin ${streakRun} doğruda bitti.`
      : ratio >= 0.85
        ? "Harika iş."
        : ratio >= 0.6
          ? "İyi gidiyorsun."
          : "Tekrar etmeye değer konular var.";

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <section className="flex flex-col items-center gap-6 rounded-2xl border border-slate-200 bg-white p-6 text-center sm:flex-row sm:text-left">
        {mode === "seri" ? (
          <div className="flex h-[136px] w-[136px] shrink-0 flex-col items-center justify-center rounded-full bg-red-50">
            <span className="text-5xl font-bold text-brand">{streakRun}</span>
            <span className="text-xs text-slate-500">doğru seri</span>
          </div>
        ) : (
          <Ring value={ratio} size={136} />
        )}
        <div className="min-w-0 flex-1">
          <p className="text-2xl font-bold text-slate-900">{message}</p>
          <p className="mt-1 text-slate-600">
            {mode === "seri"
              ? `Rekorun: ${bestStreak}`
              : `${correct.length} doğru · ${wrong.length - (mode === "sinav" ? qs.filter((_, i) => !answers[i]).length : 0)} yanlış${
                  mode === "sinav" ? ` · ${qs.filter((_, i) => !answers[i]).length} boş` : ""
                }`}
            {" · "}
            {fmtTime(secs)}
          </p>
          <div className="mt-4 flex flex-wrap justify-center gap-2 sm:justify-start">
            {wrong.length > 0 && (
              <button onClick={() => onRetryWrong(wrong.map((i) => qs[i]))} className="rounded-xl bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-dark">
                Yanlışları tekrar çöz ({wrong.length})
              </button>
            )}
            <button onClick={onAgain} className="rounded-xl border border-slate-300 px-4 py-2 text-sm hover:border-brand">
              Yeni test
            </button>
            <button onClick={onSetup} className="rounded-xl border border-slate-300 px-4 py-2 text-sm hover:border-brand">
              Ayarlara dön
            </button>
          </div>
        </div>
      </section>

      {byCat.length > 1 && (
        <section className="rounded-2xl border border-slate-200 bg-white p-5">
          <h2 className="font-semibold">Konulara göre</h2>
          <ul className="mt-4 space-y-3">
            {byCat.map(([c, { ok, n }]) => (
              <li key={c} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 text-sm">
                <span className="truncate text-slate-700">{c}</span>
                <span className="tabular-nums text-slate-500">
                  {ok}/{n}
                </span>
                <div className="col-span-2 h-2 overflow-hidden rounded-full bg-slate-100">
                  <div className={`h-full rounded-full ${ok / n >= 0.7 ? "bg-emerald-500" : ok / n >= 0.5 ? "bg-amber-500" : "bg-red-500"}`} style={{ width: `${Math.max(4, (ok / n) * 100)}%` }} />
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {seenIdx.length > 0 && (
        <section>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="font-semibold">Soruların üzerinden geç</h2>
            <div className="flex gap-2">
              <Chip on={onlyWrong} onClick={() => setOnlyWrong(true)}>
                Yanlış / boş
              </Chip>
              <Chip on={!onlyWrong} onClick={() => setOnlyWrong(false)}>
                Tümü
              </Chip>
            </div>
          </div>
          {!list.length && <p className="rounded-2xl bg-emerald-50 p-5 text-sm text-emerald-900">Yanlışın yok.</p>}
          <ol className="space-y-3">
            {list.map((i) => {
              const qq = qs[i];
              const a = answers[i];
              const ok = a === qq.correct;
              return (
                <li key={qq.id}>
                  <details className="group rounded-2xl border border-slate-200 bg-white p-4 open:shadow-sm">
                    <summary className="flex cursor-pointer list-none items-start gap-3">
                      <span className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold text-white ${ok ? "bg-emerald-500" : a ? "bg-red-500" : "bg-slate-400"}`}>
                        {ok ? "✓" : a ? "✕" : "–"}
                      </span>
                      <span className="min-w-0 flex-1 text-sm text-slate-800">{qq.text}</span>
                      <span className="shrink-0 text-xs text-slate-400 group-open:rotate-180">▾</span>
                    </summary>
                    <div className="mt-3 space-y-2 border-t border-slate-100 pt-3 text-sm">
                      {qq.media && <Media media={qq.media} />}
                      <p>
                        <span className="text-slate-500">Senin cevabın: </span>
                        {a ? `${a}) ${qq.options.find((o) => o.letter === a)?.text ?? ""}` : "boş"}
                      </p>
                      <p className="text-emerald-800">
                        <span className="text-slate-500">Doğru: </span>
                        {qq.correct}) {qq.options.find((o) => o.letter === qq.correct)?.text}
                      </p>
                      {qq.explanation && <p className="whitespace-pre-line leading-relaxed text-slate-700">{qq.explanation}</p>}
                      {qq.source && <p className="text-xs text-slate-500">Kaynak: {qq.source}</p>}
                    </div>
                  </details>
                </li>
              );
            })}
          </ol>
        </section>
      )}
    </div>
  );
}
