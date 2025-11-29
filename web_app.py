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

# --- YARDIMCI DÖNÜŞTÜRÜCÜLER (Düzenleme Modu İçin Şart) ---
def safe_float(val):
    try: return float(val)
    except: return 0.0

def safe_int(val):
    try: return int(float(val))
    except: return 0

def is_checked(val):
    return str(val).upper() == "TRUE"

# --- VERİ ÇEKME ---
def load_data(sheet_id, worksheet_index=0):
    try:
        client = connect_to_gsheets()
        sheet = client.open_by_key(sheet_id).get_worksheet(worksheet_index)
        data = sheet.get_all_values()
        
        if not data or len(data) < 1:
            return pd.DataFrame()
            
        headers = data[0]
        if "Dosya Numarası" not in headers:
            return pd.DataFrame()

        rows = data[1:]
        
        # Header Düzeltme
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
    except:
        return pd.DataFrame()

# --- SİLME ---
def delete_patient(sheet_id, dosya_no):
    try:
        client = connect_to_gsheets()
        sheet = client.open_by_key(sheet_id).sheet1
        cell = sheet.find(str(dosya_no))
        sheet.delete_rows(cell.row)
        return True
    except:
        return False

# --- KAYIT VE GÜNCELLEME ---
def save_data_row(sheet_id, data_dict, unique_col="Dosya Numarası", worksheet_index=0):
    client = connect_to_gsheets()
    sheet = client.open_by_key(sheet_id).get_worksheet(worksheet_index)
    
    clean_data = {k: str(v) if v is not None else "" for k, v in data_dict.items()}
    all_values = sheet.get_all_values()
    
    if not all_values or "Dosya Numarası" not in all_values[0]:
        sheet.clear()
        sheet.append_row(list(clean_data.keys()))
        sheet.append_row(list(clean_data.values()))
        return

    headers = all_values[0]
    missing_cols = [k for k in clean_data.keys() if k not in headers]
    if missing_cols: headers.extend(missing_cols)

    row_to_save = []
    for h in headers: row_to_save.append(clean_data.get(h, ""))
    
    # Yeni eklenenler
    for k in clean_data.keys():
        if k not in headers: row_to_save.append(clean_data[k])

    df = pd.DataFrame(all_values[1:], columns=all_values[0]).astype(str)
    row_index_to_update = None
    
    if unique_col in df.columns:
        matches = df.index[df[unique_col] == str(clean_data[unique_col])].tolist()
        if matches: row_index_to_update = matches[0] + 2

    if row_index_to_update:
        try:
            sheet.delete_rows(row_index_to_update)
            time.sleep(1)
            sheet.append_row(row_to_save)
            st.toast(f"✅ {clean_data[unique_col]} güncellendi.", icon="🔄")
        except:
            sheet.append_row(row_to_save)
    else:
        sheet.append_row(row_to_save)

# --- ARAYÜZ ---
with st.sidebar:
    st.title("❤️ NEÜ-KARDİYO")
    menu = st.radio("Menü", ["🏥 Veri Girişi (H-Type HT)", "📝 Vaka Takip (Notlar)"])
    st.divider()
    with st.expander("📋 ÇALIŞMA KRİTERLERİ", expanded=True):
        st.success("**✅ DAHİL:** Son 6 ayda yeni tanı esansiyel HT")
        st.error("**⛔ HARİÇ:** Sekonder HT, KY, AKS, Cerrahi, Konjenital, Pulmoner HT, ABY, **AF**")

# --- MOD 1: VAKA TAKİP ---
if menu == "📝 Vaka Takip (Notlar)":
    st.header("📝 Vaka Takip Defteri")
    c1, c2 = st.columns([1, 2])
    with c1:
        with st.form("note"):
            n_dosya = st.text_input("Dosya No")
            n_ad = st.text_input("Hasta")
            n_not = st.text_area("Not")
            if st.form_submit_button("Kaydet"):
                try:
                    save_data_row(CASE_SHEET_ID, {"Tarih":str(datetime.now().date()), "Dosya No":n_dosya, "Hasta":n_ad, "Not":n_not}, "Dosya No", 1)
                    st.success("Kaydedildi")
                except: st.error("Google Sheet'te 2. Sayfa Yok!")
    with c2:
        dfn = load_data(CASE_SHEET_ID, 1)
        if not dfn.empty: st.dataframe(dfn, use_container_width=True)

# --- MOD 2: VERİ GİRİŞİ ---
elif menu == "🏥 Veri Girişi (H-Type HT)":
    
    # 1. EKG ANİMASYONU (EKLEME YAPILDI)
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
    
    # Verileri Çek (Liste ve Düzenleme için)
    df = load_data(SHEET_ID, 0)

    tab_list, tab_form = st.tabs(["📋 LİSTE / SİLME", "✍️ VERİ GİRİŞ / DÜZENLE"])

    # LİSTE VE SİLME EKRANI
    with tab_list:
        col_L1, col_L2 = st.columns([3, 1])
        with col_L1:
            if st.button("🔄 Listeyi Yenile"): st.rerun()
            if not df.empty:
                st.metric("Toplam Kayıt", len(df))
                st.dataframe(df, use_container_width=True)
            else:
                st.info("Henüz kayıt yok.")
        
        with col_L2:
            st.warning("⚠️ HASTA SİLME")
            if not df.empty:
                del_list = df["Dosya Numarası"].astype(str).tolist()
                del_select = st.selectbox("Silinecek Dosya", del_list)
                if st.button("🗑️ SİL"):
                    if delete_patient(SHEET_ID, del_select):
                        st.success("Silindi!"); time.sleep(1); st.rerun()
                    else: st.error("Hata!")

    # VERİ GİRİŞ EKRANI
    with tab_form:
        # --- DÜZENLEME SEÇİMİ (EKLEME YAPILDI) ---
        edit_mode = st.checkbox("📋 Listeden Hasta Seçip Düzenle")
        current_data = {}
        
        if edit_mode and not df.empty:
            edit_id = st.selectbox("Düzenlenecek Hasta Seç (Dosya No):", df["Dosya Numarası"].unique())
            if
