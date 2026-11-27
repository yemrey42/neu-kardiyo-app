import { createBrowserClient } from "@supabase/ssr";

// Ortam değişkenleri tanımlı değilse null döner; iskelet Supabase olmadan da çalışır.
export function getSupabaseBrowserClient() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !key) return null;
  return createBrowserClient(url, key);
}
