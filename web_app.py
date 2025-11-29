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

# --- YARDIMCI FONKSİYONLAR (HATA ÖNLEYİCİ) ---
def safe_float(val):
    try:
        return float(val)
    except:
        return 0.0

def safe_int(val):
    try:
        return int(float(val))
    except:
        return 0

# --- VERİ ÇEKME ---
def load_data(sheet_id, worksheet_index=0):
    try:
        client = connect_to_gsheets()
        sheet = client.open_by_key(sheet_id).get_worksheet(worksheet_index)
        data = sheet.get_all_values()
        
        if not data: return pd.DataFrame()
            
        headers = data[0]
        rows = data[1:]
        
        # Header düzeltme
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

# --- SİLME ---
def delete_patient(sheet_id, dosya_no):
    client = connect_to_gsheets()
    sheet = client.open_by_key(sheet_id).sheet1
    try:
        cell = sheet.find(str(dosya_no))
        sheet.delete_rows(cell.row)
        return True
    except: return False

# --- KAYIT (AKILLI GÜNCELLEME) ---
def save_data_row(sheet_id, new_data, unique_col="Dosya Numarası", worksheet_index=0):
    client = connect_to_gsheets()
    sheet = client.open_by_key(sheet_id).get_worksheet(worksheet_index)
    
    all_values = sheet.get_all_values()
    
    if not all_values:
        sheet.append_row(list(new_data.keys()))
        sheet.append_row(list(new_data.values()))
        return

    headers = all_values[0]
    # Eksik sütun varsa ekle
    for k in new_data.keys():
        if k not in headers: headers.append(k)

    # Eski veriyi bul (Merge işlemi için)
    row_index = None
    existing_row_data = {}
    
    df = pd.DataFrame(all_values[1:], columns=all_values[0]).astype(str)
    if unique_col in df.columns:
        matches = df.index[df[unique_col] == str(new_data[unique_col])].tolist()
        if matches:
            row_index = matches[0] + 2
            existing_row_data = df.iloc[matches[0]].to_dict()

    # Satırı oluştur (Eski veriyi koruyarak)
    row_to_save = []
    for h in headers:
        new_val = str(new_data.get(h, ""))
        old_val = str(existing_row_data.get(h, ""))
        
        # Eğer yeni değer boşsa ve eski değer doluysa -> Eskiyi Koru
        if new_val == "" and old_val != "":
            row_to_save.append(old_val)
        else:
            row_to_save.append(new_val)

    if row_index:
        try:
            sheet.delete_rows(row_index)
            time.sleep(1)
            sheet.append_row(row_to_save)
            st.toast(f"✅ {new_data[unique_col]} GÜNCELLENDİ", icon="🔄")
        except:
            sheet.append_row(row_to_save)
    else:
        sheet.append_row(row_to_save)
        st.toast(f"✅ {new_data[unique_col]} KAYDEDİLDİ", icon="💾")

# ================= ARAYÜZ =================

# EKG Animasyonu
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

# --- LİSTE VE SEÇİM ---
df = load_data(SHEET_ID, 0)

with st.expander("📋 KAYITLI HASTA LİSTESİ & SİLME", expanded=False):
    c1, c2 = st.columns([3, 1])
    with c1:
        if st.button("🔄 Yenile"): st.rerun()
        if not df.empty:
            cols_show = ["Dosya Numarası", "Adı Soyadı", "Tarih", "Hekim"]
            final_cols = [c for c in cols_show if c in df.columns]
            st.dataframe(df[final_cols] if final_cols else df, use_container_width=True)
        else:
            st.info("Kayıt yok.")
    
    with c2:
        if not df.empty:
            del_id = st.selectbox("Silinecek No", df["Dosya Numarası"].unique())
            if st.button("🗑️ SİL"):
                if delete_patient(SHEET_ID, del_id):
                    st.success("Silindi!"); time.sleep(1); st.rerun()

# --- MOD SEÇİMİ (YENİ / DÜZENLE) ---
st.divider()
col_mode1, col_mode2 = st.columns([1, 3])
with col_mode1:
    mode = st.radio("İşlem:", ["Yeni Kayıt", "Düzenleme"], horizontal=True)

current_data = {}
if mode == "Düzenleme" and not df.empty:
    with col_mode2:
        edit_id = st.selectbox("Hasta Seç (Dosya No):", df["Dosya Numarası"].unique())
        if edit_id:
            # Seçilen hastanın verilerini sözlüğe al
            current_data = df[df["Dosya Numarası"] == edit_id].iloc[0].to_dict()

# --- FORM ---
with st.form("main_form"):
    
    # KLİNİK
    st.markdown("### 👤 Klinik")
    c1, c2 = st.columns(2)
    with c1:
        dosya_no = st.text_input("Dosya Numarası (Zorunlu)", value=current_data.get("Dosya Numarası", ""))
        ad_soyad = st.text_input("Adı Soyadı", value=current_data.get("Adı Soyadı", ""))
        
        try: def_date = datetime.strptime(current_data.get("Tarih", str(datetime.now().date())), "%Y-%m-%d")
        except: def_date = datetime.now()
        basvuru = st.date_input("Başvuru Tarihi", value=def_date)
        
        hekim = st.text_input("Veriyi Giren Hekim", value=current_data.get("Hekim", ""))
        iletisim = st.text_input("İletişim", value=current_data.get("İletişim", ""))
    
    with c2:
        col_y, col_c = st.columns(2)
        yas = col_y.number_input("Yaş", step=1, value=safe_int(current_data.get("Yaş", 0)))
        
        sex_opts = ["Erkek", "Kadın"]
        try: sex_idx = sex_opts.index(current_data.get("Cinsiyet", "Erkek"))
        except: sex_idx = 0
        cinsiyet = col_c.radio("Cinsiyet", sex_opts, index=sex_idx, horizontal=True)
        
        cb1, cb2, cb3 = st.columns(3)
        boy = cb1.number_input("Boy (cm)", value=safe_float(current_data.get("Boy", 0)))
        kilo = cb2.number_input("Kilo (kg)", value=safe_float(current_data.get("Kilo", 0)))
        
        bmi = kilo/((boy/100)**2) if boy>0 else 0
        bsa = (boy * kilo / 3600) ** 0.5 if (boy>0 and kilo>0) else 0
        cb3.metric("BMI", f"{bmi:.1f}")

        ct1, ct2 = st.columns(2)
        ta_sis = ct1.number_input("TA Sistol", value=safe_int(current_data.get("TA Sistol", 0)))
        ta_dia = ct2.number_input("TA Diyastol", value=safe_int(current_data.get("TA Diyastol", 0)))

    st.markdown("---")
    
    ekg_opts = ["NSR", "LBBB", "RBBB", "VPB", "SVT", "Diğer"]
    try: ekg_idx = ekg_opts.index(current_data.get("EKG", "NSR"))
    except: ekg_idx = 0
    ekg = st.selectbox("EKG", ekg_opts, index=ekg_idx)
    
    ci1, ci2 = st.columns(2)
    ilaclar = ci1.text_area("Kullandığı İ
