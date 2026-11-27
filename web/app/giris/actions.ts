"use server";

import { redirect } from "next/navigation";
import { getSupabaseServerClient } from "@/lib/supabaseServer";

export type LoginState = { ok: boolean; message: string; email?: string } | null;

export async function login(_prev: LoginState, formData: FormData): Promise<LoginState> {
  const email = String(formData.get("email") ?? "").trim().toLowerCase();
  const password = String(formData.get("password") ?? "");
  const next = String(formData.get("next") ?? "/calismalar");
  if (!email || !password) return { ok: false, message: "E-posta ve şifre girin." };

  let error: unknown;
  try {
    const supabase = await getSupabaseServerClient();
    ({ error } = await supabase.auth.signInWithPassword({ email, password }));
  } catch (e) {
    return { ok: false, message: (e as Error).message };
  }
  if (error) return { ok: false, message: "E-posta veya şifre hatalı.", email };
  redirect(next.startsWith("/") && !next.startsWith("//") ? next : "/calismalar");
}

export async function logout(formData: FormData) {
  const supabase = await getSupabaseServerClient();
  await supabase.auth.signOut();
  redirect(String(formData.get("next") ?? "/giris"));
}
