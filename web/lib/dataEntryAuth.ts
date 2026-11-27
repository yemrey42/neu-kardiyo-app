import "server-only";
import { cookies } from "next/headers";
import { createHmac, timingSafeEqual } from "node:crypto";

// Geçici şifre kapısı (Streamlit'teki app_password ile aynı mantık).
// Supabase girişi gelince kişiye özel hesaplarla değiştirilecek.
//   DATA_ENTRY_PASSWORD : veri girişi şifresi
//   SESSION_SECRET      : uzun rastgele bir metin (çerez imzası için)

const COOKIE = "neu_veri_oturum";
const MAX_AGE = 60 * 60 * 8; // 8 saat

function sign(value: string) {
  const secret = process.env.SESSION_SECRET;
  if (!secret) throw new Error("SESSION_SECRET tanımlı değil.");
  return createHmac("sha256", secret).update(value).digest("hex");
}

function safeEqual(a: string, b: string) {
  const ba = Buffer.from(a);
  const bb = Buffer.from(b);
  return ba.length === bb.length && timingSafeEqual(ba, bb);
}

export function checkPassword(pw: string) {
  const expected = process.env.DATA_ENTRY_PASSWORD;
  if (!expected) throw new Error("DATA_ENTRY_PASSWORD tanımlı değil.");
  return safeEqual(sign(pw), sign(expected));
}

export async function startSession() {
  const exp = String(Math.floor(Date.now() / 1000) + MAX_AGE);
  (await cookies()).set(COOKIE, `${exp}.${sign(exp)}`, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "strict",
    maxAge: MAX_AGE,
    path: "/",
  });
}

export async function endSession() {
  (await cookies()).delete(COOKIE);
}

export async function hasSession() {
  const v = (await cookies()).get(COOKIE)?.value;
  if (!v || !process.env.SESSION_SECRET) return false;
  const [exp, sig] = v.split(".");
  if (!exp || !sig || !safeEqual(sig, sign(exp))) return false;
  return Number(exp) > Date.now() / 1000;
}
