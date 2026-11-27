import Link from "next/link";

export default function NotFound() {
  return (
    <div className="text-center">
      <h1 className="text-2xl font-bold">Sayfa bulunamadı</h1>
      <Link href="/" className="mt-4 inline-block text-brand">Ana sayfaya dön</Link>
    </div>
  );
}
