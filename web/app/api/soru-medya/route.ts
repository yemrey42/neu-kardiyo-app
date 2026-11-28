import { googleAccessToken, googleConfigured } from "@/lib/sheets";

// Soru bankasındaki fotoğraf/video dosyalarını Streamlit'in kullandığı Drive klasöründen
// (web_app.py: MEDIA_DRIVE_FOLDER_ID) ve onun alt klasörlerinden (ör. Vakalar) servis hesabıyla okuyup tarayıcıya aktarır.
// Klasörün herkese açık paylaşılması gerekmez; jeton tarayıcıya hiç gönderilmez.

const FOLDER_ID = process.env.QUESTION_MEDIA_FOLDER_ID || "1PkQu5DBmYKKNrLBHQtnLJwCyNgM6f2OQ";
const DRIVE = "https://www.googleapis.com/drive/v3/files";
const SCOPES = ["https://www.googleapis.com/auth/drive.readonly"];
const ALLOWED = new Set(["image/jpeg", "image/png", "image/webp", "image/gif", "video/mp4", "video/webm", "video/ogg"]);
const LIST_TTL = 10 * 60 * 1000;

type DriveFile = { id: string; name: string; mimeType: string; size?: string; parents?: string[] };
const FOLDER_MIME = "application/vnd.google-apps.folder";
let listing: { at: number; files: Map<string, DriveFile[]>; byId: Map<string, DriveFile> } | null = null;

async function listFolder(token: string, folderId: string) {
  const out: DriveFile[] = [];
  let pageToken = "";
  do {
    const params = new URLSearchParams({
      q: `'${folderId}' in parents and trashed = false`,
      fields: "nextPageToken,files(id,name,mimeType,size)",
      pageSize: "1000",
      supportsAllDrives: "true",
      includeItemsFromAllDrives: "true",
    });
    if (pageToken) params.set("pageToken", pageToken);
    const res = await fetch(`${DRIVE}?${params}`, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
    if (!res.ok) throw new Error(`Drive listesi ${res.status}`);
    const data = (await res.json()) as { nextPageToken?: string; files?: DriveFile[] };
    out.push(...(data.files ?? []));
    pageToken = data.nextPageToken ?? "";
  } while (pageToken);
  return out;
}

/** Ana klasör ve bir alt düzeydeki klasörler (ör. "Vakalar") taranır. Dosya adıyla ve kimliğiyle aranabilir. */
async function folderIndex(token: string, force = false) {
  if (listing && !force && Date.now() - listing.at < LIST_TTL) return listing;
  const files = new Map<string, DriveFile[]>();
  const byId = new Map<string, DriveFile>();
  const top = await listFolder(token, FOLDER_ID);
  const sub = await Promise.all(top.filter((f) => f.mimeType === FOLDER_MIME).map((f) => listFolder(token, f.id)));
  for (const f of [...top, ...sub.flat()]) {
    if (f.mimeType === FOLDER_MIME) continue;
    const key = f.name.trim().toLocaleLowerCase("tr");
    files.set(key, [...(files.get(key) ?? []), f]);
    byId.set(f.id, f);
  }
  listing = { at: Date.now(), files, byId };
  return listing;
}

const fail = (status: number, msg: string) => new Response(msg, { status, headers: { "Content-Type": "text/plain; charset=utf-8" } });

export async function GET(request: Request) {
  const params = new URL(request.url).searchParams;
  const name = params.get("f")?.trim() ?? "";
  const id = params.get("id")?.trim() ?? "";
  if (id ? !/^[A-Za-z0-9_-]{10,200}$/.test(id) : !name || name.length > 250 || /[\\/]/.test(name))
    return fail(400, "Geçersiz dosya adı.");
  if (!googleConfigured()) return fail(503, "Google servis hesabı tanımlı değil.");
  try {
    const token = await googleAccessToken(SCOPES);
    // Kimlikle istenen dosya da yalnızca soru/vaka klasöründe ise verilir (başka Drive dosyalarına erişim yok).
    const find = (ix: NonNullable<typeof listing>) =>
      id ? [ix.byId.get(id)].filter((f): f is DriveFile => !!f) : (ix.files.get(name.toLocaleLowerCase("tr")) ?? []);
    let index = await folderIndex(token);
    let matches = find(index);
    // Yeni yüklenen dosya listede yoksa (liste 30 sn'den eskiyse) bir kez yenile.
    if (!matches.length && Date.now() - index.at > 30_000) {
      index = await folderIndex(token, true);
      matches = find(index);
    }
    if (matches.length !== 1) return fail(404, matches.length ? "Aynı adda birden fazla dosya var." : "Dosya bulunamadı.");
    const file = matches[0];
    if (!ALLOWED.has(file.mimeType)) return fail(415, "Desteklenmeyen dosya biçimi.");

    const range = request.headers.get("range");
    const upstream = await fetch(`${DRIVE}/${file.id}?alt=media&supportsAllDrives=true`, {
      headers: { Authorization: `Bearer ${token}`, ...(range ? { Range: range } : {}) },
      cache: "no-store",
    });
    if (!upstream.ok && upstream.status !== 206) return fail(502, "Dosya Drive'dan alınamadı.");

    const headers = new Headers({
      "Content-Type": file.mimeType,
      "Cache-Control": "public, max-age=3600, s-maxage=86400",
      "Accept-Ranges": "bytes",
      "X-Content-Type-Options": "nosniff",
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
