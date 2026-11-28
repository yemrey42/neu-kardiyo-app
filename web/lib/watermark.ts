import "server-only";
import sharp from "sharp";
import { WATERMARK_PNG_BASE64 } from "./watermarkImage";
import { fold } from "./atlasTopics";

// Kliniğimizin kendi vaka görüntülerine "Dr. YEY" yazısını görüntünün kendisine işler.
// Görüntünün ortasında soluk bir yazı olarak.

const MARK = Buffer.from(WATERMARK_PNG_BASE64, "base64");

async function mark(width: number, opacity: number) {
  const w = Math.max(40, Math.round(width));
  const resized = await sharp(MARK).resize({ width: w }).ensureAlpha().toBuffer({ resolveWithObject: true });
  // Saydamlığı ayarla: alfa kanalını opacity ile çarp.
  const { data, info } = await sharp(resized.data).raw().toBuffer({ resolveWithObject: true });
  for (let i = 3; i < data.length; i += 4) data[i] = Math.round(data[i] * opacity);
  return sharp(data, { raw: { width: info.width, height: info.height, channels: 4 } }).png().toBuffer({ resolveWithObject: true });
}

/** Görseli filigranlı olarak yeniden üretir; çıktı biçimi ve MIME türü döner. */
export async function watermarkImage(input: ArrayBuffer, mimeType: string): Promise<{ body: Buffer; mimeType: string }> {
  const img = sharp(Buffer.from(input), { animated: false }).rotate();
  const meta = await img.metadata();
  const W = meta.autoOrient?.width ?? meta.width ?? 800;
  const H = meta.autoOrient?.height ?? meta.height ?? 600;
  const edge = Math.min(W, H);
  const center = await mark(Math.min(W * 0.45, edge * 0.7), 0.16);
  const composed = img.composite([
    {
      input: center.data,
      left: Math.max(0, Math.round((W - center.info.width) / 2)),
      top: Math.max(0, Math.round((H - center.info.height) / 2)),
    },
  ]);
  if (mimeType === "image/png" || mimeType === "image/gif") return { body: await composed.png().toBuffer(), mimeType: "image/png" };
  if (mimeType === "image/webp") return { body: await composed.webp({ quality: 90 }).toBuffer(), mimeType: "image/webp" };
  return { body: await composed.jpeg({ quality: 90 }).toBuffer(), mimeType: "image/jpeg" };
}

/** Drive alt klasör adına göre: kliniğimizin kendi vakaları mı? */
export function isOwnCaseFolder(folder: string) {
  const f = fold(folder);
  return !f.includes("doppler") && (f.includes("neu") || f.includes("vaka"));
}
