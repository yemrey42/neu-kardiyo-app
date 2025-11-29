import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import time

# --- AYARLAR ---
# Senin verdiğin ID buraya sabitlendi
SHEET_ID = "1_Jd27n2lvYRl-oKmMOVySd5rGvXLrflDCQJeD_Yz6Y4"
CASE_SHEET_ID = SHEET_ID 

st.set_page_config(page_title="NEÜ-KARDİYO", page_icon="❤️", layout="wide")

# --- BAĞLANTILAR ---
def connect_to_gsheets():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
    client = gspread.authorize(creds)
    return client

# --- GÜVENLİ VERİ ÇEKME (TABLO ÇÖKMESİNİ ENGELLEYEN KOD) ---
def load_data(sheet_id, worksheet_index=0):
    try:
        client = connect_to_gsheets()
        sheet = client.open_by_key(sheet_id).get_worksheet(worksheet_index)
        
        # Tüm verileri ham olarak çek
        data = sheet.get_all_values()
        
        if not data:
            return pd.DataFrame()
            
        headers = data[0]
        rows = data[1:]
        
        # AYNI İSİMLİ SÜTUNLARI DÜZELT (Çökme Önleyici 1)
        seen = {}
        unique_headers = []
        for h in headers:
            if h in seen:
                seen[h] += 1
                unique_headers.append(f"{h}_{seen[h]}")
            else:
                seen[h] = 0
                unique_headers.append(h)
        
        # TABLOYU OLUŞTUR VE HEPSİNİ YAZIYA ÇEVİR (Çökme Önleyici 2)
        df = pd.DataFrame(rows, columns=unique_headers)
        df = df.astype(str)
        
        return df
    except Exception:
        return pd.DataFrame()

# --- SİLME İŞLEMİ ---
def delete_patient(sheet_id, dosya_no):
    try:
        client = connect_to_gsheets()
        sheet = client.open_by_key(sheet_id).sheet1
        cell = sheet.find(str(dosya_no))
        sheet.delete_rows(cell.row)
        return True
    except:
        return False

# --- KAYIT İŞLEMİ ---
def save_data_row(sheet_id, data_dict, unique_col="Dosya Numarası", worksheet_index=0):
    client = connect_to_gsheets()
    sheet = client.open_by_key(sheet_id).get_worksheet(worksheet_index)
    
    # Verileri temizle
    clean_data = {k: str(v) if v is not None else "" for k, v in data_dict.items()}
    
    all_values = sheet.get_all_values()
    
    if not all_values:
        sheet.append_row(list(clean_data.keys()))
        sheet.append_row(list(clean_data.values()))
        return

    headers = all_values[0]
    
    # Eksik sütun varsa ekle
    missing_cols = [key for key in clean_data.keys() if key not in headers]
    if missing_cols:
        headers.extend(missing_cols)

    row_to_save = []
    for h in headers:
        row_to_save.append(clean_data.get(h, ""))
    
    # Yeni eklenenler
    for k in clean_data.keys():
        if k not in headers:
            row_to_save.append(clean_data[k])

    # Güncelleme Kontrolü
    df = pd.DataFrame(all_values[1:], columns=all_values[0]).astype(str)
    
    row_index_to_update = None
    if unique_col in df.columns:
        matches = df.index[df[unique_col] == str(clean_data[unique_col])].tolist()
        if matches:
            row_index_to_update = matches[0] + 2

    if row_index_to_update:
        try:
            sheet.delete_rows(row_index_to_update)
            time.sleep(1)
            sheet.append_row(row_to_save)
            st.toast(f"{clean_data[unique_col]} güncellendi.", icon="🔄")
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
        st.error("**⛔ HARİÇ:** Sekonder HT, KY, AKS, Cerrahi, Konjenital, Pulmoner HT, ABY, **AF (Atriyal Fibrilasyon)**")

# --- MOD 1: VAKA TAKİP ---
if menu == "📝 Vaka Takip (Notlar)":
    st.header("📝 Vaka Takip Defteri")
    col1, col2 = st.columns([1, 2])
    with col1:
        with st.form("note_form", clear_on_submit=True):
            n_dosya = st.text_input("Dosya No")
            n_ad = st.text_input("Hasta Adı")
            n_dr = st.text_input("Sorumlu Doktor")
            n_plan = st.text_area("Not / Plan")
            if st.form_submit_button("Notu Kaydet"):
                note_data = {"Tarih": str(datetime.now().date()), "Dosya No": n_dosya, "Hasta": n_ad, "Doktor": n_dr, "Not": n_plan}
                try:
                    save_data_row(CASE_SHEET_ID, note_data, unique_col="Dosya No", worksheet_index=1)
                    st.success("Kaydedildi")
                except:
                    st.error("Google Sheet dosyanızda 2. bir sayfa (Vaka Takip) olduğundan emin olun!")
    with col2:
        df_notes = load_data(CASE_SHEET_ID, worksheet_index=1)
        if not df_notes.empty: st.dataframe(df_notes, use_container_width=True)

# --- MOD 2: VERİ GİRİŞİ ---
elif menu == "🏥 Veri Girişi (H-Type HT)":
    
    # --- EKG ANİMASYONU ---
    ecg_monitor_html = """
    <style>
    .monitor-container {
        background-color: #000; border: 2px solid #333; border-radius: 8px;
        padding: 0; margin-bottom: 15px; overflow: hidden; position: relative;
        height: 80px; width: 100%;
    }
    .ecg-grid {
        background-image: linear-gradient(#111 1px, transparent 1px), linear-gradient(90deg, #111 1px, transparent 1px);
        background-size: 20px 20px; width: 100%; height: 100%; position: absolute;
    }
    .ecg-wave {
        background-image: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="300" height="80" viewBox="0 0 300 80"><path d="M0 40 L20 40 L25 35 L30 40 L40 40 L42 45 L45 10 L48 70 L52 40 L60 40 L65 30 L75 30 L80 40 L300 40" stroke="%2300ff00" stroke-width="2" fill="none"/></svg>');
        background-repeat: repeat-x; width: 200%; height: 100%; position: absolute;
        animation: slide-left 3s linear infinite;
    }
    @keyframes slide-left { 0% { transform: translateX(0); } 100% { transform: translateX(-300px
