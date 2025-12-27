import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import time
import random

# ===================== AYARLAR =====================
SHEET_ID = "1_Jd27n2lvYRl-oKmMOVySd5rGvXLrflDCQJeD_Yz6Y4"
CASE_SHEET_ID = SHEET_ID
LETTER_SHEET_ID = SHEET_ID

DATA_WS_INDEX = 0       # 1. sayfa: Veri Girişi
CASE_WS_INDEX = 1       # 2. sayfa: Case Report Takip
LETTER_WS_INDEX = 2     # 3. sayfa: Editöre Mektup

st.set_page_config(page_title="NEÜ-KARDİYO", page_icon="❤️", layout="wide")

# ===================== GOOGLE SHEETS BAĞLANTI =====================
@st.cache_resource
def connect_to_gsheets():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(
        st.secrets["gcp_service_account"], scope
    )
    return gspread.authorize(creds)

# ===================== VERİ ÇEKME =====================
def load_data(sheet_id, worksheet_index=0):
    try:
        client = connect_to_gsheets()
        ws = client.open_by_key(sheet_id).get_worksheet(worksheet_index)
        data = ws.get_all_values()

        if not data or len(data) < 1:
            return pd.DataFrame()

        headers = data[0]
        rows = data[1:]

        # duplicate header fix
        seen = {}
        unique_headers = []
        for h in headers:
            h = str(h).strip()
            if h in seen:
                seen[h] += 1
                unique_headers.append(f"{h}_{seen[h]}")
            else:
                seen[h] = 0
                unique_headers.append(h)

        num_cols = len(unique_headers)
        fixed_rows = []
        for row in rows:
            if len(row) < num_cols:
                row += [""] * (num_cols - len(row))
            fixed_rows.append(row)

        df = pd.DataFrame(fixed_rows, columns=unique_headers)
        return df.astype(str)

    except:
        return pd.DataFrame()

# ===================== SHEET: header yoksa oluştur =====================
def ensure_sheet_has_headers(sheet_id, worksheet_index, headers):
    client = connect_to_gsheets()
    ws = client.open_by_key(sheet_id).get_worksheet(worksheet_index)
    values = ws.get_all_values()
    if not values:
        ws.append_row(headers)
        return

    existing_headers = [str(h).strip() for h in values[0]]
    if existing_headers != headers:
        # Eğer boş/uygunsuzsa, en azından ilk satır boşsa header basalım
        # (Mevcut veri varsa korumak için overwrite yapmıyoruz)
        if len(values) == 1 and all(x.strip() == "" for x in values[0]):
            ws.update("1:1", [headers])

# ===================== KAYIT / GÜNCELLEME (UPSERT) =====================
def save_data_row(sheet_id, worksheet_index, data_dict, unique_col):
    client = connect_to_gsheets()
    ws = client.open_by_key(sheet_id).get_worksheet(worksheet_index)

    clean_data = {str(k).strip(): ("" if v is None else str(v)) for k, v in data_dict.items()}
    all_values = ws.get_all_values()

    if not all_values:
        ws.append_row(list(clean_data.keys()))
        ws.append_row(list(clean_data.values()))
        return

    headers = [str(h).strip() for h in all_values[0]]

    if unique_col not in headers:
        headers.append(unique_col)
        ws.update("1:1", [headers])

    missing_cols = [k for k in clean_data.keys() if k not in headers]
    if missing_cols:
        headers.extend(missing_cols)
        ws.update("1:1", [headers])

    row_to_save = [clean_data.get(h, "") for h in headers]
    uid = clean_data.get(unique_col, "").strip()
    if not uid:
        raise ValueError(f"{unique_col} boş olamaz!")

    uid_col_idx = headers.index(unique_col) + 1
    col_vals = ws.col_values(uid_col_idx)

    row_index_to_update = None
    for i, v in enumerate(col_vals[1:], start=2):
        if str(v).strip() == uid:
            row_index_to_update = i
            break

    if row_index_to_update:
        ws.delete_rows(row_index_to_update)
        time.sleep(0.5)
        ws.append_row(row_to_save)
    else:
        ws.append_row(row_to_save)

# ===================== SİLME (genel) =====================
def delete_row_by_unique(sheet_id, worksheet_index, unique_col, unique_val):
    client = connect_to_gsheets()
    ws = client.open_by_key(sheet_id).get_worksheet(worksheet_index)

    all_values = ws.get_all_values()
    if not all_values:
        return False

    headers = [str(h).strip() for h in all_values[0]]
    if unique_col not in headers:
        return False

    col_idx = headers.index(unique_col) + 1
    col_vals = ws.col_values(col_idx)

    for i, v in enumerate(col_vals[1:], start=2):
        if str(v).strip() == str(unique_val).strip():
            ws.delete_rows(i)
            return True
    return False

# ===================== AUTH (1. EKRAN ŞİFRE) =====================
def require_password_gate():
    if "auth_ok" not in st.session_state:
        st.session_state.auth_ok = False

    app_password = st.secrets.get("app_password", None)
    if not app_password:
        st.error("⚠️ Secrets içine `app_password` eklemelisin.")
        st.stop()

    if st.session_state.auth_ok:
        return

    st.subheader("🔐 Veri Girişi (Şifreli)")
    pw = st.text_input("Şifre", type="password")
    if st.button("Giriş", type="primary"):
        if pw == app_password:
            st.session_state.auth_ok = True
            st.success("✅ Giriş başarılı")
            time.sleep(0.3)
            st.rerun()
        else:
            st.error("❌ Şifre yanlış")
    st.stop()

# ===================== KÜÇÜK MASKELEME =====================
def mask_first_letters(text: str, keep=1):
    t = str(text or "").strip()
    if not t:
        return ""
    # kelime bazlı: her kelimenin ilk harfi kalsın
    parts = t.split()
    masked_parts = []
    for p in parts:
        if len(p) <= keep:
            masked_parts.append(p[:keep] + "*")
        else:
            masked_parts.append(p[:keep] + "*" * (len(p) - keep))
    return " ".join(masked_parts)

# ===================== HEADER / EKG ANİMASYONU =====================
st.markdown(
    """
<style>
.ecg-container {
    background: #000; height: 90px; width: 100%; overflow: hidden; position: relative; 
    border-radius: 10px; border: 2px solid #444; margin-bottom: 20px; display: flex; align-items: center;
    box-shadow: 0 0 10px rgba(0, 255, 0, 0.2);
}
.ecg-line {
    position: absolute; top: 0; left: 0; width: 100%; height: 100%;
    background-image: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="300" height="90" viewBox="0 0 300 90"><path d="M0 50 L20 50 L25 45 L30 50 L40 50 L42 55 L45 10 L48 85 L52 50 L60 50 L65 40 L75 40 L80 50 L300 50" stroke="%2300ff00" stroke-width="2" fill="none"/></svg>');
    background-repeat: repeat-x; animation: scroll-bg 3s linear infinite; z-index: 1; opacity: 0.6;
}
@keyframes scroll-bg { 0% { background-position: 0 0; } 100% { background-position: -300px 0; } }
</style>
<div class="ecg-container"><div class="ecg-line"></div></div>
""",
    unsafe_allow_html=True,
)

st.title("H-TYPE HİPERTANSİYON ÇALIŞMASI")

# ===================== SIDEBAR =====================
with st.sidebar:
    st.title("❤️ NEÜ-KARDİYO")
    menu = st.radio("Menü", ["🏥 Veri Girişi (Şifreli)", "📝 Case Report Takip", "✉️ Editöre Mektup Takip"])

    st.divider()
    quotes = [
        "Halk içinde muteber bir nesne yok devlet gibi,\nOlmaya devlet cihanda bir nefes sıhhat gibi.\n(Kanuni Sultan Süleyman)",
        "Kalp, aklın bilmediği sebeplere sahiptir.\n(Blaise Pascal)",
        "İlim ilim bilmektir, ilim kendin bilmektir.\n(Yunus Emre)",
        "Zahmetsiz rahmet olmaz.",
        "Sabır acidir , meyvesi tatlıdır.",
        "Ne doğrarsan aşına, o gelir kaşığa.",
        "Beden almakla doyar ruh vermekle",
        "Sonum yokluk olsa bu varlık niye",
        "kısmet etmiş ise mevla; el getirir, yel getirir, sel getirir. kısmet etmez ise mevla; el götürür, yel götürür, sel götürür."
    ]
    st.info(f"💡 **Günün Sözü:**\n\n_{random.choice(quotes)}_")

# ===================== EKRAN 2: CASE REPORT =====================
if menu == "📝 Case Report Takip":
    st.header("📝 Case Report Takip")

    # header garanti
    case_headers = ["TarihSaat", "Tarih", "Dosya No", "Hasta", "Doktor", "Not"]
    try:
        ensure_sheet_has_headers(CASE_SHEET_ID, CASE_WS_INDEX, case_headers)
    except:
        pass

    c1, c2 = st.columns([1, 2])

    with c1:
        with st.form("case_form"):
            dosya_no = st.text_input("Dosya No")
            hasta = st.text_input("Hasta")
            doktor = st.text_input("Sorumlu Doktor")
            not_text = st.text_area("Not")

            if st.form_submit_button("Kaydet", type="primary"):
                now = datetime.now()
                payload = {
                    "TarihSaat": now.isoformat(timespec="seconds"),
                    "Tarih": str(now.date()),
                    "Dosya No": dosya_no,
                    "Hasta": hasta,
                    "Doktor": doktor,
                    "Not": not_text,
                }
                save_data_row(CASE_SHEET_ID, CASE_WS_INDEX, payload, unique_col="TarihSaat")
                st.success("✅ Kaydedildi")
                time.sleep(0.5)
                st.rerun()

    with c2:
        dfn = load_data(CASE_SHEET_ID, CASE_WS_INDEX)

        if not dfn.empty:
            q = st.text_input("🔎 Arama (dosya no / hasta / doktor)", "")
            show = dfn.copy()

            # NOT sütununu listeden çıkar
            if "Not" in show.columns:
                show = show.drop(columns=["Not"])

            if q.strip():
                mask = show.apply(lambda row: row.astype(str).str.contains(q, case=False, na=False).any(), axis=1)
                show = show[mask].copy()

            st.dataframe(show, use_container_width=True)

            st.markdown("##### 🗑️ Silme")
            if "TarihSaat" in dfn.columns:
                del_ts = st.selectbox("Silinecek kayıt (TarihSaat):", dfn["TarihSaat"].tolist())
                if st.button("🗑️ Sil", key="del_case"):
                    ok = delete_row_by_unique(CASE_SHEET_ID, CASE_WS_INDEX, "TarihSaat", del_ts)
                    if ok:
                        st.success("Silindi.")
                        time.sleep(0.4)
                        st.rerun()
                    else:
                        st.error("Silinemedi.")
        else:
            st.info("Henüz case report kaydı yok.")

# ===================== EKRAN 3: EDİTÖRE MEKTUP =====================
elif menu == "✉️ Editöre Mektup Takip":
    st.header("✉️ Editöre Mektup Takip")

    letter_headers = ["TarihSaat", "Tarih", "Dergi Adı", "Makale İsmi", "Yazarlar"]
    try:
        ensure_sheet_has_headers(LETTER_SHEET_ID, LETTER_WS_INDEX, letter_headers)
    except:
        pass

    c1, c2 = st.columns([1, 2])

    with c1:
        with st.form("letter_form"):
            dergi = st.text_input("Dergi Adı")
            makale = st.text_input("Makale İsmi")
            yazarlar = st.text_area("Yazarlar")

            if st.form_submit_button("Kaydet", type="primary"):
                now = datetime.now()
                payload = {
                    "TarihSaat": now.isoformat(timespec="seconds"),
                    "Tarih": str(now.date()),
                    "Dergi Adı": dergi,
                    "Makale İsmi": makale,
                    "Yazarlar": yazarlar,
                }
                save_data_row(LETTER_SHEET_ID, LETTER_WS_INDEX, payload, unique_col="TarihSaat")
                st.success("✅ Kaydedildi")
                time.sleep(0.5)
                st.rerun()

    with c2:
        dfl = load_data(LETTER_SHEET_ID, LETTER_WS_INDEX)

        if not dfl.empty:
            # Maskeli görüntü için kopya dataframe
            show = dfl.copy()

            if "Dergi Adı" in show.columns:
                show["Dergi Adı"] = show["Dergi Adı"].apply(lambda x: mask_first_letters(x, keep=1))
            if "Makale İsmi" in show.columns:
                show["Makale İsmi"] = show["Makale İsmi"].apply(lambda x: mask_first_letters(x, keep=1))

            q = st.text_input("🔎 Arama (dergi / makale / yazar)", "")
            if q.strip():
                mask = show.apply(lambda row: row.astype(str).str.contains(q, case=False, na=False).any(), axis=1)
                show = show[mask].copy()

            st.dataframe(show, use_container_width=True)

            st.markdown("##### 🗑️ Silme")
            if "TarihSaat" in dfl.columns:
                del_ts = st.selectbox("Silinecek kayıt (TarihSaat):", dfl["TarihSaat"].tolist())
                if st.button("🗑️ Sil", key="del_letter"):
                    ok = delete_row_by_unique(LETTER_SHEET_ID, LETTER_WS_INDEX, "TarihSaat", del_ts)
                    if ok:
                        st.success("Silindi.")
                        time.sleep(0.4)
                        st.rerun()
                    else:
                        st.error("Silinemedi.")
        else:
            st.info("Henüz editöre mektup kaydı yok.")

# ===================== EKRAN 1: VERİ GİRİŞİ =====================
else:
    require_password_gate()

    # ---- kriterleri boş alana taşıyalım: ana ekranda üstte göster ----
    st.markdown("### 📋 Çalışma Kriterleri (H-Type HT)")
    cc1, cc2 = st.columns(2)
    with cc1:
        st.success("✅ **DAHİL:** Son 6 ayda yeni tanı esansiyel HT")
    with cc2:
        st.error("⛔ **HARİÇ:** Sekonder HT, KY, AKS, Cerrahi, Konjenital, Pulmoner HT, ABY, **AF**")
    st.markdown("---")

    # ---- veri ----
    df = load_data(SHEET_ID, DATA_WS_INDEX)

    col_left, col_right = st.columns([2, 3])

    with col_left:
        st.markdown("##### ⚙️ İşlem Seçimi")
        mode = st.radio("Mod:", ["Yeni Kayıt", "Düzenleme"], horizontal=True, label_visibility="collapsed")

        current = {}
        if mode == "Düzenleme":
            if not df.empty and "Dosya Numarası" in df.columns:
                edit_id = st.selectbox("Düzenlenecek Hasta (Dosya No):", df["Dosya Numarası"].unique())
                if edit_id:
                    current = df[df["Dosya Numarası"] == edit_id].iloc[0].to_dict()
                    st.success(f"Seçildi: {current.get('Dosya Numarası', '')}")
            else:
                st.warning("Düzenlenecek kayıt yok.")

    with col_right:
        with st.expander("📋 KAYITLI HASTA LİSTESİ / ARAMA / SİLME", expanded=True):
            if st.button("🔄 Listeyi Yenile"):
                st.rerun()

            if df.empty:
                st.info("Kayıt yok.")
            else:
                q = st.text_input("🔎 Arama (dosya no / hekim)", "")
                show_df = df.copy()

                # Ad Soyad görünmesin
                if "Adı Soyadı" in show_df.columns:
                    show_df = show_df.drop(columns=["Adı Soyadı"])

                if q.strip():
                    mask = show_df.apply(lambda row: row.astype(str).str.contains(q, case=False, na=False).any(), axis=1)
                    show_df = show_df[mask].copy()

                cols_show = ["Dosya Numarası", "Tarih", "Hekim", "TA Sistol", "TA Diyastol"]
                final_cols = [c for c in cols_show if c in show_df.columns]
                st.dataframe(show_df[final_cols] if final_cols else show_df, use_container_width=True)

                st.markdown("##### 🗑️ Silme")
                if "Dosya Numarası" in df.columns:
                    del_id = st.selectbox("Silinecek Dosya No", df["Dosya Numarası"].unique(), key="del_main")
                    if st.button("🗑️ SİL", type="secondary"):
                        ok = delete_row_by_unique(SHEET_ID, DATA_WS_INDEX, "Dosya Numarası", del_id)
                        if ok:
                            st.success("Silindi!")
                            time.sleep(0.5)
                            st.rerun()
                        else:
                            st.error("Hata!")

    st.divider()

    # ---- FORM HELPERS ----
    def gs(k): return str(current.get(k, ""))
    def gf(k):
        try: return float(current.get(k, 0))
        except: return 0.0
    def gi(k):
        try: return int(float(current.get(k, 0)))
        except: return 0
    def gc(k): return str(current.get(k, "")).lower() == "true"

    # ---- FORM ----
    with st.form("main_form"):
        st.markdown("### 👤 Klinik")
        c1, c2 = st.columns(2)

        with c1:
            dosya_no = st.text_input("Dosya Numarası (Zorunlu)", value=gs("Dosya Numarası"))
            ad_soyad = st.text_input("Adı Soyadı", value=gs("Adı Soyadı"))

            try:
                d_date = datetime.strptime(gs("Tarih"), "%Y-%m-%d")
            except:
                d_date = datetime.now()
            basvuru = st.date_input("Başvuru Tarihi", value=d_date)

            hekim = st.text_input("Veriyi Giren Hekim (Zorunlu)", value=gs("Hekim"))
            iletisim = st.text_input("İletişim", value=gs("İletişim"))

        with c2:
            cy, cc = st.columns(2)
            yas = cy.number_input("Yaş", step=1, value=gi("Yaş"))

            sex_l = ["Erkek", "Kadın"]
            try:
                s_ix = sex_l.index(gs("Cinsiyet"))
            except:
                s_ix = 0
            cinsiyet = cc.radio("Cinsiyet", sex_l, index=s_ix, horizontal=True)

            cb1, cb2, cb3 = st.columns(3)
            boy = cb1.number_input("Boy (cm)", value=gf("Boy"))
            kilo = cb2.number_input("Kilo (kg)", value=gf("Kilo"))

            bmi = kilo / ((boy / 100) ** 2) if boy > 0 else 0
            bsa = (boy * kilo / 3600) ** 0.5 if (boy > 0 and kilo > 0) else 0
            cb3.metric("BMI", f"{bmi:.1f}")

            ct1, ct2 = st.columns(2)
            ta_sis = ct1.number_input("TA Sistol (mmHg)", value=gi("TA Sistol"))
            ta_dia = ct2.number_input("TA Diyastol (mmHg)", value=gi("TA Diyastol"))

        st.markdown("---")
        ekg_l = ["NSR", "LBBB", "RBBB", "VPB", "SVT", "Diğer"]
        try:
            e_ix = ekg_l.index(gs("EKG"))
        except:
            e_ix = 0
        ekg = st.selectbox("EKG", ekg_l, index=e_ix)

        ci1, ci2 = st.columns(2)
        ilaclar = ci1.text_area("Kullandığı İlaçlar", value=gs("İlaçlar"))
        baslanan = ci2.text_area("Başlanan İlaçlar", value=gs("Başlanan"))

        st.markdown("##### Ek Hastalıklar")
        ck1, ck2, ck3, ck4, ck5 = st.columns(5)
        dm = ck1.checkbox("DM", value=gc("DM"))
        kah = ck2.checkbox("KAH", value=gc("KAH"))
        hpl = ck3.checkbox("HPL", value=gc("HPL"))
        inme = ck4.checkbox("İnme", value=gc("İnme"))
        sigara = ck5.checkbox("Sigara", value=gc("Sigara"))
        diger = st.text_input("Diğer", value=gs("Diğer"))

        st.markdown("### 🩸 Laboratuvar")
        l1, l2, l3, l4 = st.columns(4)
        hgb = l1.number_input("Hgb (g/dL)", value=gf("Hgb"))
        hct = l1.number_input("Hct (%)", value=gf("Hct"))
        wbc = l1.number_input("WBC (10³/µL)", value=gf("WBC"))
        plt = l1.number_input("PLT (10³/µL)", value=gf("PLT"))
        neu = l1.number_input("Nötrofil (%)", value=gf("Neu"))
        lym = l1.number_input("Lenfosit (%)", value=gf("Lym"))
        mpv = l1.number_input("MPV (fL)", value=gf("MPV"))
        rdw = l1.number_input("RDW (%)", value=gf("RDW"))

        glukoz = l2.number_input("Glukoz (mg/dL)", value=gf("Glukoz"))
        ure = l2.number_input("Üre (mg/dL)", value=gf("Üre"))
        krea = l2.number_input("Kreatinin (mg/dL)", value=gf("Kreatinin"))
        uric = l2.number_input("Ürik Asit (mg/dL)", value=gf("Ürik Asit"))
        na = l2.number_input("Na (mEq/L)", value=gf("Na"))
        k_val = l2.number_input("K (mEq/L)", value=gf("K"))
        alt = l2.number_input("ALT (U/L)", value=gf("ALT"))
        ast = l2.number_input("AST (U/L)", value=gf("AST"))
        prot = l2.number_input("Tot Prot (g/dL)", value=gf("Tot. Prot"))
        alb = l2.number_input("Albümin (g/dL)", value=gf("Albümin"))

        chol = l3.number_input("Chol (mg/dL)", value=gf("Chol"))
        ldl = l3.number_input("LDL (mg/dL)", value=gf("LDL"))
        hdl = l3.number_input("HDL (mg/dL)", value=gf("HDL"))
        trig = l3.number_input("Trig (mg/dL)", value=gf("Trig"))

        homo = l4.number_input("Homosistein (µmol/L)", value=gf("Homosistein"))
        lpa = l4.number_input("Lp(a) (mg/dL)", value=gf("Lp(a)"))
        folik = l4.number_input("Folik Asit (ng/mL)", value=gf("Folik Asit"))
        b12 = l4.number_input("B12 (pg/mL)", value=gf("B12"))

        st.write("")
        if st.form_submit_button("💾 KAYDET / GÜNCELLE", type="primary"):
            if not dosya_no or not hekim:
                st.error("Dosya No ve Hekim zorunlu!")
            else:
                final_data = {
                    "Dosya Numarası": dosya_no,
                    "Adı Soyadı": ad_soyad,
                    "Tarih": str(basvuru),
                    "Hekim": hekim,
                    "İletişim": iletisim,
                    "Yaş": yas,
                    "Cinsiyet": cinsiyet,
                    "Boy": boy,
                    "Kilo": kilo,
                    "BMI": bmi,
                    "BSA": bsa,
                    "TA Sistol": ta_sis,
                    "TA Diyastol": ta_dia,
                    "EKG": ekg,
                    "İlaçlar": ilaclar,
                    "Başlanan": baslanan,
                    "DM": dm,
                    "KAH": kah,
                    "HPL": hpl,
                    "İnme": inme,
                    "Sigara": sigara,
                    "Diğer": diger,
                    "Hgb": hgb,
                    "Hct": hct,
                    "WBC": wbc,
                    "PLT": plt,
                    "Neu": neu,
                    "Lym": lym,
                    "MPV": mpv,
                    "RDW": rdw,
                    "Glukoz": glukoz,
                    "Üre": ure,
                    "Kreatinin": krea,
                    "Ürik Asit": uric,
                    "Na": na,
                    "K": k_val,
                    "ALT": alt,
                    "AST": ast,
                    "Tot. Prot": prot,
                    "Albümin": alb,
                    "Chol": chol,
                    "LDL": ldl,
                    "HDL": hdl,
                    "Trig": trig,
                    "Lp(a)": lpa,
                    "Homosistein": homo,
                    "Folik Asit": folik,
                    "B12": b12,
                }
                save_data_row(SHEET_ID, DATA_WS_INDEX, final_data, unique_col="Dosya Numarası")
                st.success(f"✅ {dosya_no} kaydedildi / güncellendi!")
                time.sleep(0.6)
                st.rerun()
