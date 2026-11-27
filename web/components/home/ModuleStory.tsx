"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { AnimatePresence, motion, useMotionValueEvent, useReducedMotion, useScroll } from "motion/react";

type Item = { href: string; title: string; text: string; accent: string; visual: React.ReactNode };

const Bars = () => (
  <svg viewBox="0 0 200 140" className="h-full w-full">
    {[30, 55, 45, 80, 65, 100].map((h, i) => (
      <motion.rect key={i} x={15 + i * 30} width="18" rx="4" fill="currentColor"
        initial={{ y: 130, height: 0 }} animate={{ y: 130 - h, height: h }} transition={{ delay: i * 0.08, duration: 0.6 }} />
    ))}
  </svg>
);

const Pages = () => (
  <svg viewBox="0 0 200 140" className="h-full w-full">
    {[0, 1, 2].map((i) => (
      <motion.g key={i} initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.12 }}>
        <rect x={40 + i * 18} y={8 + i * 12} width="100" height="96" rx="8" fill="white" stroke="currentColor" strokeWidth="2" />
        {[0, 1, 2, 3].map((l) => (
          <rect key={l} x={52 + i * 18} y={30 + i * 12 + l * 16} width={l === 0 ? 60 : 76} height="6" rx="3" fill="currentColor" opacity={l === 0 ? 0.9 : 0.3} />
        ))}
      </motion.g>
    ))}
  </svg>
);

const Monitor = () => (
  <svg viewBox="0 0 200 140" className="h-full w-full">
    <rect x="20" y="10" width="160" height="100" rx="10" fill="#0f172a" />
    <motion.path d="M30 70 H70 L80 60 L90 70 H100 L108 30 L116 100 L124 70 H170" fill="none" stroke="#4ade80" strokeWidth="3"
      initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 1.2, repeat: Infinity, repeatDelay: 0.4 }} />
    <rect x="85" y="112" width="30" height="14" fill="currentColor" opacity="0.4" />
    <rect x="65" y="126" width="70" height="6" rx="3" fill="currentColor" opacity="0.4" />
  </svg>
);

const Checklist = () => (
  <svg viewBox="0 0 200 140" className="h-full w-full">
    {["A", "B", "C", "D"].map((l, i) => (
      <motion.g key={l} initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.1 }}>
        <rect x="30" y={12 + i * 30} width="140" height="22" rx="11" fill={i === 1 ? "currentColor" : "white"} stroke="currentColor" strokeWidth="2" />
        <text x="45" y={27 + i * 30} fontSize="11" fontWeight="700" fill={i === 1 ? "white" : "currentColor"}>{l})</text>
        <rect x="65" y={20 + i * 30} width={i === 1 ? 70 : 85} height="6" rx="3" fill={i === 1 ? "white" : "currentColor"} opacity={i === 1 ? 0.9 : 0.3} />
      </motion.g>
    ))}
  </svg>
);

const items: Item[] = [
  { href: "/literatur", title: "Güncel literatür", accent: "text-sky-600 bg-sky-50",
    text: "Önde gelen kardiyoloji dergilerindeki yeni yayınlar PubMed'den her gün otomatik olarak listelenir. Kliniğimizin yayınları ayrı bir bölümde.",
    visual: <Pages /> },
  { href: "/egitim", title: "Eğitim", accent: "text-emerald-600 bg-emerald-50",
    text: "Kateterizasyon ve transseptal ponksiyon simülasyonları, hemodinami, mitral yetmezlik ve diyastolik fonksiyon hesaplayıcıları.",
    visual: <Monitor /> },
  { href: "/soru-bankasi", title: "Soru bankası", accent: "text-violet-600 bg-violet-50",
    text: "Kategorilere ayrılmış sorular, anında geri bildirim ve kaynaklı açıklamalar.",
    visual: <Checklist /> },
  { href: "/calismalar", title: "Klinik çalışmalar", accent: "text-brand bg-red-50",
    text: "Yürüttüğümüz çalışmalar hakkında bilgi ve yetkili ekip için anonim veri girişi.",
    visual: <Bars /> },
];

export function ModuleStory() {
  const ref = useRef<HTMLElement>(null);
  const reduce = useReducedMotion();
  const [active, setActive] = useState(0);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start start", "end end"] });
  useMotionValueEvent(scrollYProgress, "change", (v) => {
    setActive(Math.min(items.length - 1, Math.max(0, Math.floor(v * items.length))));
  });

  // Hareketi azalt açıksa: sabit, basit liste
  if (reduce) {
    return (
      <section className="grid gap-6 py-16 md:grid-cols-2">
        {items.map((it) => (
          <Link key={it.href} href={it.href} className="rounded-2xl border border-slate-200 bg-white p-6">
            <div className={`h-40 rounded-xl p-4 ${it.accent}`}>{it.visual}</div>
            <h3 className="mt-4 text-xl font-semibold">{it.title}</h3>
            <p className="mt-2 text-slate-600">{it.text}</p>
          </Link>
        ))}
      </section>
    );
  }

  return (
    <section ref={ref} style={{ height: `${items.length * 90}vh` }} className="relative">
      <div className="sticky top-0 flex h-screen items-center">
        <div className="grid w-full items-center gap-10 md:grid-cols-2">
          <div className={`relative aspect-[10/7] w-full overflow-hidden rounded-3xl p-8 transition-colors duration-500 ${items[active].accent}`}>
            <AnimatePresence mode="wait">
              <motion.div key={active} className="h-full w-full"
                initial={{ opacity: 0, scale: 0.92 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 1.05 }}
                transition={{ duration: 0.4 }}>
                {items[active].visual}
              </motion.div>
            </AnimatePresence>
          </div>

          <div>
            <div className="mb-6 flex gap-2" aria-hidden>
              {items.map((_, i) => (
                <span key={i} className={`h-1.5 rounded-full transition-all duration-300 ${i === active ? "w-8 bg-brand" : "w-3 bg-slate-300"}`} />
              ))}
            </div>
            <AnimatePresence mode="wait">
              <motion.div key={active} initial={{ opacity: 0, y: 30 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -30 }}
                transition={{ duration: 0.35 }}>
                <h2 className="text-4xl font-bold tracking-tight text-slate-900 sm:text-5xl">{items[active].title}</h2>
                <p className="mt-4 max-w-md text-lg text-slate-600">{items[active].text}</p>
                <Link href={items[active].href} className="mt-6 inline-block font-semibold text-brand hover:underline">
                  Keşfet →
                </Link>
              </motion.div>
            </AnimatePresence>
          </div>
        </div>
      </div>
    </section>
  );
}
