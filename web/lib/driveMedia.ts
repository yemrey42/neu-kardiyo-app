import "server-only";
import { googleAccessToken } from "./sheets";

// Soru görsellerinin Drive klasörü (web_app.py: MEDIA_DRIVE_FOLDER_ID) ve bir alt düzeydeki klasörleri.
// Alt klasör adı sorunun hangi bölüme ait olduğunu belirler:
//   "doppler hemodinami" → Doppler Hemodinami soruları (kitaptan alıntı)
//   "Neu vakalar"        → Kliniğimizden vakalar

export const MEDIA_FOLDER_ID = process.env.QUESTION_MEDIA_FOLDER_ID || "1PkQu5DBmYKKNrLBHQtnLJwCyNgM6f2OQ";
const DRIVE = "https://www.googleapis.com/drive/v3/files";
const FOLDER_MIME = "application/vnd.google-apps.folder";
const SCOPES = ["https://www.googleapis.com/auth/drive.readonly"];
const TTL = 10 * 60 * 1000;

export type DriveFile = { id: string; name: string; mimeType: string; size?: string; folder: string };
export type DriveIndex = { at: number; byName: Map<string, DriveFile[]>; byId: Map<string, DriveFile> };

let cache: DriveIndex | null = null;

async function listFolder(token: string, folderId: string) {
  const out: Omit<DriveFile, "folder">[] = [];
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
    const data = (await res.json()) as { nextPageToken?: string; files?: Omit<DriveFile, "folder">[] };
    out.push(...(data.files ?? []));
    pageToken = data.nextPageToken ?? "";
  } while (pageToken);
  return out;
}

export const nameKey = (s: string) => s.trim().toLocaleLowerCase("tr");

/** Klasör dizini (10 dk önbellek). Kısayollar ve klasörler atlanır; dosyanın alt klasör adı `folder`dadır. */
export async function driveIndex(force = false): Promise<DriveIndex> {
  if (cache && !force && Date.now() - cache.at < TTL) return cache;
  const token = await googleAccessToken(SCOPES);
  const top = await listFolder(token, MEDIA_FOLDER_ID);
  const subs = top.filter((f) => f.mimeType === FOLDER_MIME);
  const subFiles = await Promise.all(subs.map((s) => listFolder(token, s.id)));
  const all: DriveFile[] = [
    ...top.map((f) => ({ ...f, folder: "" })),
    ...subFiles.flatMap((files, i) => files.map((f) => ({ ...f, folder: subs[i].name }))),
  ].filter((f) => f.mimeType !== FOLDER_MIME && f.mimeType !== "application/vnd.google-apps.shortcut");
  const byName = new Map<string, DriveFile[]>();
  const byId = new Map<string, DriveFile>();
  for (const f of all) {
    byName.set(nameKey(f.name), [...(byName.get(nameKey(f.name)) ?? []), f]);
    byId.set(f.id, f);
  }
  cache = { at: Date.now(), byName, byId };
  return cache;
}

export async function driveToken() {
  return googleAccessToken(SCOPES);
}
