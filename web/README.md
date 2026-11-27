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
| Veri girişi | `/calismalar/[slug]/veri-girisi` | Çalışıyor: şifreli giriş, Google Sheets'e yazar |
| Ekip girişi | `/giris` | Supabase bağlanınca aktif olacak |
| KVKK | `/kvkk` | Taslak metin (hukuk onayı gerekli) |

İçerikler şimdilik `lib/content.ts` içinde; veritabanı şeması `supabase/schema.sql`.

## Klinik çalışma veri girişi (Google Sheets)

Şimdilik veriler veritabanına değil, **Google Sheets**'e yazılır (Streamlit ile aynı mantık).
Yeni çalışmalar ileride Supabase'e alınabilir.

- 5 çalışmanın formları Streamlit'teki formlardan çıkarıldı (`lib/studyForms.data.ts`);
  sütun adları Streamlit ile aynıdır. BMI, BSA, LAVI, PASP, TAPSE/PASP gibi değerler
  sunucuda aynı formüllerle hesaplanır (`lib/studyForms.ts`).
- Her çalışma aynı tablonun içinde **ayrı bir sekmeye** yazılır (`WEB - H-Type HT`, `WEB - AFMR` ...;
  bkz. `lib/studyConfig.ts`). Sekme yoksa ilk kayıtta oluşur. Streamlit'in sekmelerine dokunulmaz.
- `KayıtID` = katılımcı kodu + ziyaret + tarih. Aynı KayıtID tekrar kaydedilirse satır güncellenir.
- Her satıra `Etik Kurul No` ve `Kayıt Zamanı` eklenir.
- Giriş: tek ortak şifre (`DATA_ENTRY_PASSWORD`), 8 saatlik imzalı çerez. Kişiye özel hesaplar
  Supabase ile gelecek.
- Bir çalışmanın etik kurul onay numarası `lib/content.ts` içinde girilmeden formu açılmaz.

**Vercel ortam değişkenleri:** `GOOGLE_SERVICE_ACCOUNT_JSON` (Streamlit secrets'taki servis
hesabı bilgilerinin JSON hali, tek satır), `GOOGLE_SHEET_ID`, `DATA_ENTRY_PASSWORD`,
`SESSION_SECRET` (uzun rastgele metin). Servis hesabının e-postası tabloya **Düzenleyici**
olarak paylaşılmış olmalı (Streamlit için zaten paylaşılmış durumda).

## Etik / KVKK ilkeleri (veri girişi)

- Ad, TC kimlik no, telefon, dosya/protokol numarası tutulmaz; hasta yalnızca
  çalışmaya özel takma kodla (ör. `HT-001`) tanımlanır. Eşleştirme listesi sitede değil,
  sorumlu araştırmacıda kalır.
- Serbest metin alanlarında telefon/TC gibi uzun rakam dizileri reddedilir.
- Etik kurul onay numarası girilmemiş çalışmaya veri eklenemez.
- Sitede kayıt listeleme/görüntüleme yok; veriler yalnızca tabloya yetkili kişilerce erişilir.
- İleride Supabase'e geçilen çalışmalarda `supabase/schema.sql` (rol bazlı erişim, `audit_log`,
  AB-Frankfurt) kullanılacak.

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
