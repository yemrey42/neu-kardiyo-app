// Supabase proje adresi ve "publishable" anahtar. Bu anahtar tarayıcıya açık olacak şekilde
// tasarlanmıştır (gizli değildir); erişim güvenliği Supabase tarafında sağlanır.
// Ortam değişkeni verilirse o kullanılır. "secret" / "service_role" anahtarı ASLA buraya yazılmaz.
export const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL || "https://oyupmosqmvlibykbsgzf.supabase.co";
export const SUPABASE_PUBLISHABLE_KEY =
  process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY ||
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ||
  "sb_publishable_tznZQZM-NtLJUDfPUlzq6A_OiEdOh6m";
