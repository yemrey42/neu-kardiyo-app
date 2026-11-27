"use client";

import { useState } from "react";
import type { Question } from "@/lib/content";

const letters = ["A", "B", "C", "D", "E"] as const;

export function Quiz({ questions }: { questions: Question[] }) {
  const [index, setIndex] = useState(0);
  const [picked, setPicked] = useState<string | null>(null);
  const [score, setScore] = useState(0);

  if (questions.length === 0) return <p>Henüz soru yok.</p>;
  const finished = index >= questions.length;

  if (finished) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-6">
        <p className="text-lg font-semibold">Test bitti: {score} / {questions.length} doğru</p>
        <button
          className="mt-4 rounded bg-brand px-4 py-2 text-white"
          onClick={() => { setIndex(0); setScore(0); setPicked(null); }}
        >
          Yeniden başla
        </button>
      </div>
    );
  }

  const q = questions[index];
  return (
    <div className="max-w-3xl rounded-xl border border-slate-200 bg-white p-6">
      <p className="text-sm text-slate-500">
        Soru {index + 1} / {questions.length} · {q.category}
      </p>
      <h2 className="mt-2 text-lg font-medium">{q.text}</h2>
      <div className="mt-4 space-y-2">
        {letters.map((l) => {
          const isCorrect = picked && l === q.correct;
          const isWrong = picked === l && l !== q.correct;
          return (
            <button
              key={l}
              disabled={!!picked}
              onClick={() => { setPicked(l); if (l === q.correct) setScore((s) => s + 1); }}
              className={`block w-full rounded border px-4 py-2 text-left ${
                isCorrect ? "border-green-600 bg-green-50" : isWrong ? "border-red-600 bg-red-50" : "border-slate-200 hover:border-brand"
              }`}
            >
              <span className="font-semibold">{l})</span> {q.options[l]}
            </button>
          );
        })}
      </div>
      {picked && (
        <div className="mt-4 rounded bg-slate-50 p-4 text-sm">
          <p className="font-semibold">{picked === q.correct ? "Doğru!" : `Yanlış. Doğru cevap: ${q.correct}`}</p>
          <p className="mt-1">{q.explanation}</p>
          {q.source && <p className="mt-1 text-slate-500">Kaynak: {q.source}</p>}
          <button
            className="mt-3 rounded bg-brand px-4 py-2 text-white"
            onClick={() => { setIndex((i) => i + 1); setPicked(null); }}
          >
            Sonraki soru
          </button>
        </div>
      )}
    </div>
  );
}
