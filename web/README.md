# NEÜ Kardiyoloji – Yeni Web Sitesi (`web/`)

Bu klasör, `neu-cardio.com.tr` için yeni sitenin kaynak kodudur. Depo kökündeki
Streamlit uygulaması (`web_app.py`, `KARDİYO-APP.py`) **ayrıdır ve değiştirilmez**;
yalnızca içerik ve fikir kaynağı olarak kullanıldı.

**Teknoloji:** Next.js (App Router, TypeScript) + Tailwind CSS · Barındırma: Vercel ·
Veritabanı/Giriş: Supabase (EU – Frankfurt).

## Modüller

| Sayfa | Yol | Durum |
|---|---|---|
| Klinik haberleri | `/haberler` | Örnek içerik |
| Güncel literatür | `/literatur` | Örnek içerik |
| Eğitim | `/egitim` | Streamlit'teki simülasyon/hesaplayıcı listesi, taşınacak |
| Soru bankası | `/soru-bankasi` | Çalışan örnek test (Streamlit soru şemasıyla uyumlu) |
| Klinik çalışmalar | `/calismalar` | 5 çalışma + bilgilendirme sayfası |
| Veri girişi | `/calismalar/[slug]/veri-girisi` | Pasif form önizlemesi, erişim kuralları |
| Ekip girişi | `/giris` | Supabase bağlanınca aktif olacak |
| KVKK | `/kvkk` | Taslak metin (hukuk onayı gerekli) |

İçerikler şimdilik `lib/content.ts` içinde; veritabanı şeması `supabase/schema.sql`.

## Etik / KVKK ilkeleri (veri girişi)

- Ad, TC kimlik no, telefon, dosya/protokol numarası tutulmaz; hasta yalnızca
  çalışmaya özel takma kodla (ör. `HT-001`) tanımlanır. Eşleştirme listesi sitede değil,
  sorumlu araştırmacıda kalır.
- Etik kurul onay numarası girilmemiş çalışmaya veri eklenemez (RLS ile zorunlu).
- Yalnızca çalışmaya eklenmiş araştırmacılar okur/yazar; silme yalnızca admin.
- Her ekleme/düzenleme/silme `audit_log` tablosuna yazılır.
- Veriler AB (Frankfurt) bölgesinde tutulur.

## Yerelde çalıştırma

```bash
cd web
npm install
cp .env.example .env.local   # Supabase anahtarlarını girin (opsiyonel)
npm run dev                  # http://localhost:3000
```

## Vercel'e yayın

1. vercel.com → **Add New → Project** → GitHub'dan `neu-kardiyo-app` deposunu seçin.
2. **Root Directory** = `web` (önemli: Streamlit kodu kökte kalır).
3. Framework otomatik "Next.js" gelir. Environment Variables bölümüne `.env.example`
   içindeki değişkenleri ekleyin → **Deploy**.
4. Project → **Settings → Domains** → `neu-cardio.com.tr` ve `www.neu-cardio.com.tr` ekleyin.

## METUnic DNS kayıtları

METUnic panelinde alan adı → DNS yönetimi bölümüne şunları ekleyin
(Vercel'in Domains ekranında gösterdiği değerler esastır, farklıysa onları kullanın):

| Tür | Ad (Host) | Değer |
|---|---|---|
| A | `@` | `76.76.21.21` |
| CNAME | `www` | `cname.vercel-dns.com` |

- `@` için mevcut başka A/AAAA kaydı varsa (park sayfası vb.) silin.
- E-posta kullanıyorsanız MX kayıtlarına dokunmayın.
- Yayılma genelde birkaç dakika–birkaç saat sürer; Vercel SSL sertifikasını otomatik üretir.
