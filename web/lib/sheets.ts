import "server-only";
import { JWT } from "google-auth-library";

// Google Sheets'e servis hesabı ile yazar (Streamlit'teki gspread mantığının aynısı).
// Gerekli ortam değişkenleri (Streamlit secrets'taki gcp_service_account bölümünden):
//   GOOGLE_CLIENT_EMAIL : client_email değeri
//   GOOGLE_PRIVATE_KEY  : private_key değeri (-----BEGIN PRIVATE KEY----- ... dahil)
// Alternatif: GOOGLE_SERVICE_ACCOUNT_JSON (JSON'un tamamı). GOOGLE_SHEET_ID verilmezse Streamlit'in tablosu.

const API = "https://sheets.googleapis.com/v4/spreadsheets";

// Streamlit uygulamasının kullandığı tablo (web_app.py içindeki SHEET_ID)
const DEFAULT_SHEET_ID = "1_Jd27n2lvYRl-oKmMOVySd5rGvXLrflDCQJeD_Yz6Y4";

function config() {
  const sheetId = process.env.GOOGLE_SHEET_ID || DEFAULT_SHEET_ID;
  const raw = process.env.GOOGLE_SERVICE_ACCOUNT_JSON;
  // Ya JSON'un tamamı ya da Streamlit secrets'taki iki alan ayrı ayrı verilebilir.
  const creds = raw
    ? (JSON.parse(raw) as { client_email: string; private_key: string })
    : { client_email: process.env.GOOGLE_CLIENT_EMAIL ?? "", private_key: process.env.GOOGLE_PRIVATE_KEY ?? "" };
  if (!creds.client_email || !creds.private_key) {
    throw new Error("Google servis hesabı tanımlı değil (GOOGLE_CLIENT_EMAIL ve GOOGLE_PRIVATE_KEY).");
  }
  return { creds, sheetId };
}

/** Yapıştırırken eklenen tırnakları, \\n kaçışlarını ve Windows satır sonlarını düzeltir. */
function cleanKey(raw: string) {
  return raw.trim().replace(/^["']|["'],?$/g, "").replace(/\\n/g, "\n").replace(/\r/g, "");
}

/** Servis hesabı ortam değişkenleri girilmiş mi? (Hata fırlatmadan kontrol.) */
export function googleConfigured() {
  try {
    config();
    return true;
  } catch {
    return false;
  }
}

/** Servis hesabıyla verilen kapsamlar için erişim jetonu (Sheets okuma/yazma, Drive okuma). */
export async function googleAccessToken(scopes: string[]) {
  const { creds } = config();
  const client = new JWT({
    email: creds.client_email.trim().replace(/^["']|["']$/g, ""),
    key: cleanKey(creds.private_key),
    scopes,
  });
  const { token } = await client.getAccessToken();
  if (!token) throw new Error("Google erişim jetonu alınamadı.");
  return token;
}

async function authHeader() {
  const token = await googleAccessToken(["https://www.googleapis.com/auth/spreadsheets"]);
  return { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
}

async function api(path: string, init: RequestInit = {}) {
  const res = await fetch(`${API}/${config().sheetId}${path}`, {
    ...init,
    headers: { ...(await authHeader()), ...(init.headers ?? {}) },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`Google Sheets hatası (${res.status}): ${await res.text()}`);
  return res.json();
}

const q = (tab: string) => encodeURIComponent(`'${tab.replace(/'/g, "''")}'`);

export function colLetter(n: number) {
  let s = "";
  while (n > 0) {
    const r = (n - 1) % 26;
    s = String.fromCharCode(65 + r) + s;
    n = Math.floor((n - 1) / 26);
  }
  return s;
}

async function ensureTab(tab: string) {
  const meta = await api("?fields=sheets.properties.title");
  const exists = (meta.sheets ?? []).some((s: { properties: { title: string } }) => s.properties.title === tab);
  if (!exists) {
    await api(":batchUpdate", {
      method: "POST",
      body: JSON.stringify({ requests: [{ addSheet: { properties: { title: tab } } }] }),
    });
  }
}

/**
 * Başlık satırına göre kaydı yazar. uniqueCol değeri aynı olan satır varsa günceller,
 * yoksa sona ekler. Eksik başlıklar sağa eklenir. Dönüş: "created" | "updated".
 */
export async function upsertRow(tab: string, record: Record<string, string>, uniqueCol: string) {
  await ensureTab(tab);
  const data = await api(`/values/${q(tab)}`);
  const values: string[][] = data.values ?? [];
  const headers = (values[0] ?? []).map((h) => String(h).trim());

  const missing = Object.keys(record).filter((k) => !headers.includes(k));
  if (missing.length || headers.length === 0) {
    headers.push(...missing);
    await api(`/values/${q(tab)}!A1?valueInputOption=RAW`, {
      method: "PUT",
      body: JSON.stringify({ values: [headers] }),
    });
  }

  const uid = record[uniqueCol];
  if (!uid) throw new Error(`${uniqueCol} boş olamaz.`);
  const uidIdx = headers.indexOf(uniqueCol);
  const rowIdx = values.findIndex((r, i) => i > 0 && String(r[uidIdx] ?? "").trim() === uid);
  const row = headers.map((h) => record[h] ?? "");
  const end = colLetter(headers.length);

  if (rowIdx > 0) {
    const n = rowIdx + 1;
    await api(`/values/${q(tab)}!A${n}:${end}${n}?valueInputOption=RAW`, {
      method: "PUT",
      body: JSON.stringify({ values: [row] }),
    });
    return "updated" as const;
  }
  await api(`/values/${q(tab)}!A1:append?valueInputOption=RAW&insertDataOption=INSERT_ROWS`, {
    method: "POST",
    body: JSON.stringify({ values: [row] }),
  });
  return "created" as const;
}
