"use client";

import { useRef } from "react";
import Link from "next/link";
import { motion, useReducedMotion, useScroll, useTransform } from "motion/react";

// Kalp atışı ritminde bir EKG çizgisi (viewBox 0 0 1200 200)
const ECG_PATH =
  "M0 120 H180 L200 112 L215 120 H300 L318 128 L332 30 L348 170 L362 120 H450 L480 98 L515 120 H640 " +
  "L660 112 L675 120 H760 L778 128 L792 30 L808 170 L822 120 H910 L940 98 L975 120 H1200";

export function Hero() {
  const ref = useRef<HTMLElement>(null);
  const reduce = useReducedMotion();
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start start", "end start"] });

  const heartScale = useTransform(scrollYProgress, [0, 1], [1, reduce ? 1 : 1.6]);
  const heartOpacity = useTransform(scrollYProgress, [0, 0.8], [0.9, reduce ? 0.9 : 0]);
  const textY = useTransform(scrollYProgress, [0, 1], [0, reduce ? 0 : -160]);
  const textOpacity = useTransform(scrollYProgress, [0, 0.6], [1, reduce ? 1 : 0]);
  const ecgLength = useTransform(scrollYProgress, [0, 0.7], [reduce ? 1 : 0.25, 1]);

  return (
    <section ref={ref} className="relative -mt-10 mx-[calc(50%-50vw)] h-[160vh]">
      <div className="sticky top-0 flex h-screen items-center justify-center overflow-hidden bg-slate-950 text-white">
        {/* Arka plan ışıması */}
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(185,28,28,0.45),transparent_60%)]" />

        {/* Kalp */}
        <motion.svg
          viewBox="0 0 24 24"
          aria-hidden
          style={{ scale: heartScale, opacity: heartOpacity }}
          className="heart-beat absolute h-[60vmin] w-[60vmin] text-brand"
        >
          <path
            fill="currentColor"
            d="M12 21s-7.5-4.6-10-9.3C.4 8.4 2.2 4.5 6 4.5c2.1 0 3.4 1.2 4 2.2.6-1 1.9-2.2 4-2.2 3.8 0 5.6 3.9 4 7.2C19.5 16.4 12 21 12 21z"
          />
        </motion.svg>

        {/* EKG */}
        <svg viewBox="0 0 1200 200" preserveAspectRatio="none" aria-hidden className="absolute bottom-[12%] h-32 w-full">
          <motion.path
            d={ECG_PATH}
            fill="none"
            stroke="rgba(255,255,255,0.85)"
            strokeWidth="3"
            strokeLinejoin="round"
            style={{ pathLength: ecgLength }}
          />
        </svg>

        <motion.div style={{ y: textY, opacity: textOpacity }} className="relative z-10 px-6 text-center">
          <p className="text-sm font-medium uppercase tracking-[0.3em] text-red-200">Necmettin Erbakan Üniversitesi</p>
          <h1 className="mt-4 text-5xl font-bold tracking-tight sm:text-7xl">Kardiyoloji Kliniği</h1>
          <p className="mx-auto mt-6 max-w-xl text-lg text-slate-300">
            Klinik haberleri, güncel literatür, eğitim ve araştırma tek bir yerde.
          </p>
          <div className="mt-8 flex justify-center gap-3">
            <Link href="/literatur" className="rounded-full bg-white px-5 py-2.5 text-sm font-semibold text-slate-900 hover:bg-red-50">
              Güncel literatür
            </Link>
            <Link href="/egitim" className="rounded-full border border-white/40 px-5 py-2.5 text-sm font-semibold hover:bg-white/10">
              Eğitim
            </Link>
          </div>
        </motion.div>

        <motion.p style={{ opacity: textOpacity }} className="absolute bottom-6 text-xs tracking-widest text-slate-400">
          AŞAĞI KAYDIRIN ↓
        </motion.p>
      </div>
    </section>
  );
}
