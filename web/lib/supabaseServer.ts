import "server-only";
import { cookies } from "next/headers";
import { createServerClient } from "@supabase/ssr";
import { SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY } from "./supabaseConfig";

// Supabase yalnızca GİRİŞ (e-posta + şifre) için kullanılır; çalışma verisi Google Sheets'e gider.
export async function getSupabaseServerClient() {
  const url = SUPABASE_URL;
  const key = SUPABASE_PUBLISHABLE_KEY;
  const store = await cookies();
  return createServerClient(url, key, {
    cookies: {
      getAll: () => store.getAll(),
      setAll: (list) => {
        try {
          list.forEach(({ name, value, options }) => store.set(name, value, options));
        } catch {
          // Server Component içinden çağrıldığında çerez yazılamaz; oturum proxy.ts'de yenilenir.
        }
      },
    },
  });
}

/** Giriş yapmış kullanıcının e-postası; yoksa null. */
export async function currentUserEmail(): Promise<string | null> {
  const supabase = await getSupabaseServerClient();
  const { data } = await supabase.auth.getUser();
  return data.user?.email ?? null;
}
