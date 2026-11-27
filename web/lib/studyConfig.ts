// Her çalışmanın verisinin yazılacağı Google Sheets sekmesi ve katılımcı kodu öneki.
// Sekme yoksa ilk kayıtta otomatik oluşturulur. Streamlit'in kullandığı sekmelerden
// ayrı tutulur; böylece Streamlit uygulamasının kayıtları ve davranışı etkilenmez.
export const studySheetConfig: Record<string, { tab: string; codePrefix: string; visitCodes?: Record<string, string> }> = {
  "h-type-ht": { tab: "WEB - H-Type HT", codePrefix: "HT" },
  "av-blok-pacing": {
    tab: "WEB - AV Blok Pacing",
    codePrefix: "PC",
    visitCodes: { "1. Başlangıç": "BASLANGIC", "2. Kontrol": "KONTROL" },
  },
  "afmr-tee-gls": {
    tab: "WEB - AFMR",
    codePrefix: "AF",
    visitCodes: { "1. Başlangıç": "BASLANGIC", "2. Kontrol": "KONTROL" },
  },
  "kv-ablasyon-tee-gls": {
    tab: "WEB - KV-Ablasyon",
    codePrefix: "KA",
    visitCodes: { "1. Başlangıç": "BASLANGIC", "2. Kontrol": "KONTROL" },
  },
  "pbmv-rv-pa": {
    tab: "WEB - PBMV",
    codePrefix: "PB",
    visitCodes: {
      "1. PBMV Öncesi": "PRE",
      "2. PBMV Sonrası Erken (24-72 saat)": "POST_24_72H",
      "3. Kontrol": "KONTROL",
    },
  },
};
