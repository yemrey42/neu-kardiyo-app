// Kişisel ilerleme yalnızca bu tarayıcıda (localStorage) tutulur; sunucuya gönderilmez.

const KEY = "neu-soru-bankasi-v1";

export type QStat = { r: number; w: number; last: 0 | 1; t: number };
export type Progress = { q: Record<string, QStat>; bestStreak: number; sessions: number };

const empty = (): Progress => ({ q: {}, bestStreak: 0, sessions: 0 });

export function loadProgress(): Progress {
  if (typeof window === "undefined") return empty();
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return empty();
    const p = JSON.parse(raw) as Partial<Progress>;
    return { q: p.q ?? {}, bestStreak: p.bestStreak ?? 0, sessions: p.sessions ?? 0 };
  } catch {
    return empty();
  }
}

export function saveProgress(p: Progress) {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(p));
  } catch {
    // Gizli sekme / dolu depolama: ilerleme kaydedilmez, test yine çalışır.
  }
}

export function recordAnswer(p: Progress, id: string, correct: boolean): Progress {
  const prev = p.q[id] ?? { r: 0, w: 0, last: 0, t: 0 };
  return {
    ...p,
    q: { ...p.q, [id]: { r: prev.r + (correct ? 1 : 0), w: prev.w + (correct ? 0 : 1), last: correct ? 1 : 0, t: Date.now() } },
  };
}

export function clearProgress(): Progress {
  try {
    window.localStorage.removeItem(KEY);
  } catch {}
  return empty();
}
