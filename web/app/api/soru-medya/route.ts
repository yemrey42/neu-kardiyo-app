import { googleConfigured } from "@/lib/sheets";
import { driveIndex, driveToken, nameKey, type DriveFile } from "@/lib/driveMedia";
import { isOwnCaseFolder, watermarkImage } from "@/lib/watermark";
import { currentUserEmail } from "@/lib/supabaseServer";

// Soru görsellerini/videolarını Streamlit'in kullandığı Drive klasöründen (ve alt klasörlerinden)
// servis hesabıyla okuyup tarayıcıya aktarır. Klasörün herkese açık olması gerekmez; jeton tarayıcıya gitmez.
// Yalnızca bu klasördeki dosyalar verilir (kimlikle istense bile başka Drive dosyalarına erişim yok).

const DRIVE = "https://www.googleapis.com/drive/v3/files";
const ALLOWED = new Set(["image/jpeg", "image/png", "image/webp", "image/gif", "video/mp4", "video/webm", "video/ogg", "video/quicktime"]);

const fail = (status: number, msg: string) => new Response(msg, { status, headers: { "Content-Type": "text/plain; charset=utf-8" } });

export async function GET(request: Request) {
  const params = new URL(request.url).searchParams;
  const name = params.get("f")?.trim() ?? "";
  const id = params.get("id")?.trim() ?? "";
  if (id ? !/^[A-Za-z0-9_-]{10,200}$/.test(id) : !name || name.length > 250 || /[\\/]/.test(name))
    return fail(400, "Geçersiz dosya adı.");
  if (!googleConfigured()) return fail(503, "Google servis hesabı tanımlı değil.");
  try {
    const find = (ix: Awaited<ReturnType<typeof driveIndex>>): DriveFile[] =>
      id ? [ix.byId.get(id)].filter((f): f is DriveFile => !!f) : (ix.byName.get(nameKey(name)) ?? []);
    let index = await driveIndex();
    let matches = find(index);
    // Yeni yüklenen dosya listede yoksa (liste 30 sn'den eskiyse) bir kez yenile.
    if (!matches.length && Date.now() - index.at > 30_000) {
      index = await driveIndex(true);
      matches = find(index);
    }
    if (matches.length !== 1) return fail(404, matches.length ? "Aynı adda birden fazla dosya var." : "Dosya bulunamadı.");
    const file = matches[0];
    if (!ALLOWED.has(file.mimeType)) return fail(415, "Desteklenmeyen dosya biçimi.");

    const own = isOwnCaseFolder(file.folder);
    // Kendi vakalarımız herkese açık; soru bankası ve Doppler görselleri yalnızca giriş yapanlara.
    if (!own && !(await currentUserEmail())) return fail(401, "Giriş gerekli.");
    // Kendi vakalarımız: dosya adresi doğrudan sekmede açılıp kaydedilemesin (yalnızca sayfa içinden gösterilir).
    if (own && request.headers.get("sec-fetch-dest") === "document") return fail(403, "Bu görüntü yalnızca site içinde görüntülenebilir.");

    const token = await driveToken();

    // Kendi vaka görsellerimize "Dr. YEY" filigranı görüntünün kendisine işlenir.
    if (own && file.mimeType.startsWith("image/")) {
      const res = await fetch(`${DRIVE}/${file.id}?alt=media&supportsAllDrives=true`, {
        headers: { Authorization: `Bearer ${token}` },
        cache: "no-store",
      });
      if (!res.ok) return fail(502, "Dosya Drive'dan alınamadı.");
      const out = await watermarkImage(await res.arrayBuffer(), file.mimeType);
      return new Response(new Uint8Array(out.body), {
        headers: {
          "Content-Type": out.mimeType,
          "Content-Disposition": "inline",
          "Cache-Control": "public, max-age=3600, s-maxage=86400",
          "X-Content-Type-Options": "nosniff",
        },
      });
    }

    const range = request.headers.get("range");
    const upstream = await fetch(`${DRIVE}/${file.id}?alt=media&supportsAllDrives=true`, {
      headers: { Authorization: `Bearer ${token}`, ...(range ? { Range: range } : {}) },
      cache: "no-store",
    });
    if (!upstream.ok && upstream.status !== 206) return fail(502, "Dosya Drive'dan alınamadı.");

    const headers = new Headers({
      "Content-Type": file.mimeType,
      // Girişli içerik paylaşılan önbelleğe (CDN) girmesin.
      "Cache-Control": own ? "public, max-age=3600, s-maxage=86400" : "private, max-age=3600",
      "Accept-Ranges": "bytes",
      "X-Content-Type-Options": "nosniff",
      ...(own ? { "Content-Disposition": "inline" } : {}),
    });
    for (const h of ["content-length", "content-range"]) {
      const v = upstream.headers.get(h);
      if (v) headers.set(h, v);
    }
    return new Response(upstream.body, { status: upstream.status, headers });
  } catch (e) {
    console.error("[soru-medya]", e);
    return fail(502, "Medya yüklenemedi.");
  }
}
