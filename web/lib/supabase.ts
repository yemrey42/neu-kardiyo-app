import { createBrowserClient } from "@supabase/ssr";
import { SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY } from "./supabaseConfig";

export function getSupabaseBrowserClient() {
  const url = SUPABASE_URL;
  const key = SUPABASE_PUBLISHABLE_KEY;
  return createBrowserClient(url, key);
}
