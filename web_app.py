import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import time

# --- AYARLAR ---
SHEET_ID = "1_Jd27n2lvYRl-oKmMOVySd5rGvXLrflDCQJeD_Yz6Y4"
CASE_SHEET_ID = SHEET_ID 

st.set_page_config(page_title="NEÜ-KARDİYO", page_icon="❤️", layout="wide")

# --- BAĞLANTILAR ---
@st.cache_resource
def connect_to_gsheets():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
    client = gspread.authorize(creds)
    return client

# --- GÜVENLİ VERİ ÇEKME ---
def load_data(sheet_id, worksheet_index=0):
    try:
        client = connect_to_gsheets()
        sheet = client.open_by_key(sheet_id).get_worksheet(worksheet_index)
        data = sheet.get_all_values()
        if not data: return pd.DataFrame()
        headers = data[0]
        rows = data[1:]
        # Header düzeltme (Duplicate prevention)
        seen = {}; unique_headers = []
        for h in headers:
            h = str(h).strip()
            if h in seen: seen[h]+=1; unique_headers.append(f"{h}_{seen[h]}")
            else: seen[h]=0; unique_headers.append(h)
        
        # Satır Dengeleme
        num_cols = len(unique_headers)
        fixed_rows = []
        for row in rows:
            if len(row) < num_cols: row += [""] * (num_cols - len(row))
            fixed_rows.append(row)

        df = pd.DataFrame(fixed_rows, columns=unique_headers)
        return df.astype(str)
    except: return pd.DataFrame()

# --- YARDIMCI: SAYI ÇEVİRME (HATA ÖNLEYİCİ) ---
def safe_float(val):
    try: return float(val)
    except: return 0.0

def safe_int(val):
    try: return int(float(val))
    except: return 0

# --- KAYIT ---
def save_data_row(sheet_id, data_dict, unique_col="Dosya Numarası", worksheet_index=0):
    client = connect_to_gsheets()
    sheet = client.open_by_key(sheet_id).get_worksheet(worksheet_index)
    
    clean_data = {k: str(v) if v is not None else "" for k, v in data_dict.items()}
    all_values = sheet.get_all_values()
    
    if not all_values:
        sheet.append_row(list(clean_data.keys())); sheet.append_row(list(clean_data.values()))
        return

    headers = all_values[0]
    # Eksik sütun varsa ekle
    for k in clean_data.keys():
        if k not in headers: headers.append(k) # Basitçe listeye ekle, sheet'e yansımaz ama kod çalışır

    row_to_save = []
    for h in headers: row_to_save.append(clean_data.get(h, ""))

    # Güncelleme Kontrolü
    row_index = None
    # Pandas ile bul
    df = pd.DataFrame(all_values[1:], columns=all_values[0]).astype(str)
    if unique_col in df.columns:
        matches = df.index[df[unique_col] == str(clean_data[unique_col])].tolist()
        if matches: row_index = matches[0] + 2

    if row_index:
        sheet.delete_rows(row_index)
        time.sleep(1)
        sheet.append_row(row_to_save)
        st.toast(f"✅ {clean_data[unique_col]} GÜNCELLENDİ", icon="🔄")
    else:
        sheet.append_row(row_to_save)
        st.toast(f"✅ {clean_data[unique_col]} KAYDEDİLDİ", icon="💾")

# --- SİLME ---
def delete_patient(sheet_id, dosya_no):
    client = connect_to_gsheets()
    sheet = client.open_by_key(sheet_id).sheet1
    try:
        cell = sheet.find(str(dosya_no))
        sheet.delete_rows(cell.row)
        return True
    except: return False

# ================= ARAYÜZ BAŞLANGICI =================

# --- 1. EKG ANİMASYONU ---
st.markdown("""
<style>
.ecg-container { background: #000; height: 70px; width: 100%; overflow: hidden; position: relative; border-radius: 8px; border: 1px solid #333; margin-bottom: 10px; }
.ecg-line {
    background-image: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="300" height="70" viewBox="0 0 300 70"><path d="M0 35 L20 35 L25 30 L30 35 L40 35 L42 40 L45 5 L48 65 L52 35 L60 35 L65 25 L75 25 L80 35 L300 35" stroke="%2300ff00" stroke-width="2" fill="none"/></svg>');
    width: 200%; height: 100%; position: absolute; animation: slide 3s linear infinite; background-repeat: repeat-x;
}
@keyframes slide { from { transform: translateX(0); } to { transform: translateX(-300px); } }
</style>
<div class="ecg-container"><div class="ecg-line"></div></div>
""", unsafe_allow_html=True)

st.title("H-TYPE HİPERTANSİYON ÇALIŞMASI")

# --- 2. VERİ ÇEKME & LİSTELEME ---
df = load_data(SHEET_ID, 0)

with st.expander("📋 KAYITLI HASTA LİSTESİ & SİLME İŞLEMİ", expanded=False):
    c1, c2 = st.columns([3, 1])
    with c1:
        if st.button("🔄 Listeyi Yenile"): st.rerun()
        if not df.empty:
            # Sadece önemli sütunları göster
            cols_show = ["Dosya Numarası", "Adı Soyadı", "Tarih", "Hekim", "Yaş", "Cinsiyet"]
            final_cols = [c for c in cols_show if c in df.columns]
            st.dataframe(df[final_cols] if final_cols else df, use_container_width=True)
        else:
            st.info("Kayıt yok.")
    
    with c2:
        if not df.empty:
            st.error("HASTA SİL")
            del_id = st.selectbox("Silinecek No", df["Dosya Numarası"].unique())
            if st.button("🗑️ SİL"):
                if delete_patient(SHEET_ID, del_id):
                    st.success("Silindi!"); time.sleep(1); st.rerun()
                else: st.error("Hata!")

# --- 3. DÜZENLEME MODU SEÇİMİ ---
st.divider()
col_mode1, col_mode2 = st.columns([1, 3])
with col_mode1:
    mode = st.radio("İşlem Türü:", ["Yeni Kayıt", "Düzenleme"], horizontal=True)

# Düzenleme için değişkenleri hazırla
current_data = {}

if mode == "Düzenleme":
    if not df.empty:
        with col_mode2:
            edit_id = st.selectbox("Düzenlenecek Hasta (Dosya No):", df["Dosya Numarası"].unique())
            # Seçilen hastanın verilerini çek
            if edit_id:
                current_data = df[df["Dosya Numarası"] == edit_id].iloc[0].to_dict()
                st.success(f"Seçilen Hasta: {current_data.get('Adı Soyadı', '')}")
    else:
        st.warning("Düzenlenecek kayıt bulunamadı.")

# --- 4. VERİ GİRİŞ FORMU ---
with st.form("main_form"):
    
    # --- KLİNİK ---
    st.markdown("### 👤 Klinik Bilgiler")
    c1, c2 = st.columns(2)
    with c1:
        # Value değerlerini current_data'dan alıyoruz (Varsa dolu gelir, yoksa boş)
        dosya_no = st.text_input("Dosya Numarası (Zorunlu)", value=current_data.get("Dosya Numarası", ""))
        ad_soyad = st.text_input("Adı Soyadı", value=current_data.get("Adı Soyadı", ""))
        
        # Tarih işleme
        try:
            def_date = datetime.strptime(current_data.get("Tarih", str(datetime.now().date())), "%Y-%m-%d")
        except:
            def_date = datetime.now()
        basvuru = st.date_input("Başvuru Tarihi", value=def_date)
        
        hekim = st.text_input("Veriyi Giren Hekim", value=current_data.get("Hekim", ""))
        iletisim = st.text_input("İletişim", value=current_data.get("İletişim", ""))
    
    with c2:
        col_y, col_c = st.columns(2)
        yas = col_y.number_input("Yaş", step=1, value=safe_int(current_data.get("Yaş", 0)))
        
        # Cinsiyet Index Bulma
        sex_opts = ["Erkek", "Kadın"]
        try: sex_idx = sex_opts.index(current_data.get("Cinsiyet", "Erkek"))
        except: sex_idx = 0
        cinsiyet = col_c.radio("Cinsiyet", sex_opts, index=sex_idx, horizontal=True)
        
        cb1, cb2, cb3 = st.columns(3)
        boy = cb1.number_input("Boy (cm)", value=safe_float(current_data.get("Boy", 0)))
        kilo = cb2.number_input("Kilo (kg)", value=safe_float(current_data.get("Kilo", 0)))
        
        # BMI/BSA Anlık Hesap
        bmi = kilo/((boy/100)**2) if boy>0 else 0
        bsa = (boy * kilo / 3600) ** 0.5 if (boy>0 and kilo>0) else 0
        cb3.metric("BMI", f"{bmi:.1f}")

        ct1, ct2 = st.columns(2)
        ta_sis = ct1.number_input("TA Sistol (mmHg)", value=safe_int(current_data.get("TA Sistol", 0)))
        ta_dia = ct2.number_input("TA Diyastol (mmHg)", value=safe_int(current_data.get("TA Diyastol", 0)))

    st.markdown("---")
    
    # EKG Index
    ekg_opts = ["NSR", "LBBB", "RBBB", "VPB", "SVT", "Diğer"]
    try: ekg_idx = ekg_opts.index(current_data.get("EKG", "NSR"))
    except: ekg_idx = 0
    ekg = st.selectbox("EKG Bulgusu", ekg_opts, index=ekg_idx)
    
    ci1, ci2 = st.columns(2)
    ilaclar = ci1.text_area("Kullandığı İlaçlar", value=current_data.get("İlaçlar", ""))
    baslanan = ci2.text_area("Başlanan İlaçlar", value=current_data.get("Başlanan İlaçlar", ""))

    st.markdown("##### Ek Hastalıklar")
    cc1, cc2, cc3, cc4, cc5 = st.columns(5)
    # Checkbox değerleri string "True" ise True yap
    def is_checked(key): return str(current_data.get(key, "")).lower() == "true"
    
    dm = cc1.checkbox("DM", value=is_checked("DM"))
    kah = cc2.checkbox("KAH", value=is_checked("KAH"))
    hpl = cc3.checkbox("HPL", value=is_checked("HPL"))
    inme = cc4.checkbox("İnme", value=is_checked("İnme"))
    sigara = cc5.checkbox("Sigara", value=is_checked("Sigara"))
    diger_hst = st.text_input("Diğer Hastalıklar", value=current_data.get("Diğer Hast", ""))

    # --- LAB ---
    st.markdown("### 🩸 Laboratuvar")
    l1, l2, l3, l4 = st.columns(4)
    hgb = l1.number_input("Hgb (g/dL)", value=safe_float(current_data.get("Hgb", 0)))
    hct = l1.number_input("Hct (%)", value=safe_float(current_data.
