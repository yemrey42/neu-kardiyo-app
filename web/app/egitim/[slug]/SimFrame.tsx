"use client";

import { useEffect, useRef, useState } from "react";

// Aynı alan adındaki simülasyon sayfasını, içeriğinin yüksekliğine göre büyüyen bir çerçevede gösterir.
export function SimFrame({ src, title }: { src: string; title: string }) {
  const ref = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState(1200);

  useEffect(() => {
    const frame = ref.current;
    if (!frame) return;
    let ro: ResizeObserver | undefined;
    const measure = () => {
      const doc = frame.contentDocument;
      if (doc?.body) setHeight(Math.max(600, doc.documentElement.scrollHeight));
    };
    const onLoad = () => {
      measure();
      const doc = frame.contentDocument;
      if (doc?.body && "ResizeObserver" in window) {
        ro = new ResizeObserver(measure);
        ro.observe(doc.body);
      }
    };
    frame.addEventListener("load", onLoad);
    // Çerçeve, bu kod çalışmadan önce yüklenmiş olabilir
    if (frame.contentDocument?.readyState === "complete" && frame.contentDocument.body?.childElementCount) onLoad();
    return () => {
      frame.removeEventListener("load", onLoad);
      ro?.disconnect();
    };
  }, []);

  return (
    <iframe
      ref={ref}
      src={src}
      title={title}
      style={{ height }}
      className="w-full rounded-2xl border border-slate-200 bg-white"
    />
  );
}
