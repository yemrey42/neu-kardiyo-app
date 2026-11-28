import { NextResponse, type NextRequest } from "next/server";
import { createServerClient } from "@supabase/ssr";
import { SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY } from "@/lib/supabaseConfig";

// Supabase oturum çerezini her istekte yeniler (süresi dolan erişim jetonu için).
export async function proxy(request: NextRequest) {
  let response = NextResponse.next({ request });
  const url = SUPABASE_URL;
  const key = SUPABASE_PUBLISHABLE_KEY;

  const supabase = createServerClient(url, key, {
    cookies: {
      getAll: () => request.cookies.getAll(),
      setAll: (list) => {
        list.forEach(({ name, value }) => request.cookies.set(name, value));
        response = NextResponse.next({ request });
        list.forEach(({ name, value, options }) => response.cookies.set(name, value, options));
      },
    },
  });
  const { data } = await supabase.auth.getUser();
  // Görüntüleme modüllerinin HTML dosyaları girişsiz doğrudan açılmasın.
  if (!data.user && request.nextUrl.pathname.startsWith("/moduller/")) {
    return NextResponse.redirect(new URL("/asistan/goruntuleme", request.url));
  }
  return response;
}

export const config = { matcher: ["/calismalar/:path*", "/giris", "/asistan/:path*", "/moduller/:path*", "/api/soru-medya"] };
