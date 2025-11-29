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

# --- VERİ ÇEKME ---
def load_data(sheet_id, worksheet_index=0):
    try:
        client = connect_to_gsheets()
        sheet = client.open_by_key(sheet_id).get_worksheet(worksheet_index)
        data = sheet.get_all_values()
        if not data: return pd.DataFrame()
        
        headers = data[0]
        # Header düzeltme
        seen = {}; unique_headers = []
        for h in headers:
            h = str(h).strip()
            if h in seen: seen[h]+=1; unique_headers.append(f"{h}_{seen[h]}")
            else: seen[h]=0; unique_headers.append(h)
            
        rows = data[1:]
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
    try:
        client = connect_to_gsheets()
        sheet = client.open_by_key(sheet_id).sheet1
        cell = sheet.find(str(dosya_no))
        sheet.delete_rows(cell.row)
        return True
    except: return False

# --- KAYIT ---
def save_data_row(sheet_id, new_data, unique_col="Dosya Numarası", worksheet_index=0):
    client = connect_to_gsheets()
    sheet = client.open_by_key(sheet_id).get_worksheet(worksheet_index)
    all_values = sheet.get_all_values()
    
    if not all_values:
        sheet.append_row(list(new_data.keys())); sheet.append_row(list(new_data.values()))
        return

    headers = all_values[0]
    for k in new_data.keys():
        if k not in headers: headers.append(k)

    row_to_save = []
    # Eski veriyi bul (Merge)
    df = pd.DataFrame(all_values[1:], columns=all_values[0]).astype(str)
    row_index = None
    existing = {}
    
    if unique_col in df.columns:
        matches = df.index[df[unique_col] == str(new_data[unique_col])].tolist()
        if matches:
            row_index = matches[0] + 2
            existing = df.iloc[matches[0]].to_dict()

    for h in headers:
        new_v = str(new_data.get(h, ""))
        old_v = str(existing.get(h, ""))
        # Yeni boşsa eskiyi koru
        if new_v == "" and old_v != "": row_to_save.append(old_v)
        else: row_to_save.append(new_v)

    if row_index:
        try:
            sheet.delete_rows(row_index); time.sleep(1)
            sheet.append_row(row_to_save)
            st.toast("✅ Güncellendi", icon="🔄")
        except: sheet.append_row(row_to_save)
    else:
        sheet.append_row(row_to_save)
        st.toast("✅ Kaydedildi", icon="💾")

# ================= ARAYÜZ =================

# EKG Animasyonu (Tek Satır Haline Getirildi - Hata Riskini Azaltmak İçin)
st.markdown("""<style>.ecg-c{background:#000;height:70px;width:100%;overflow:hidden;position:relative;border-radius:8px;border:1px solid #333;margin-bottom:10px}.ecg-l{background-image:url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="300" height="70" viewBox="0 0 300 70"><path d="M0 35 L20 35 L25 30 L30 35 L40 35 L42 40 L45 5 L48 65 L52 35 L60 35 L65 25 L75 25 L80 35 L300 35" stroke="%2300ff00" stroke-width="2" fill="none"/></svg>');width:200%;height:100%;position:absolute;animation:slide 3s linear infinite;background-repeat:repeat-x}@keyframes slide{from{transform:translateX(0)}to{transform:translateX(-300px)}}</style><div class="ecg-c"><div class="ecg-l"></div></div>""", unsafe_allow_html=True)

st.title("H-TYPE HİPERTANSİYON ÇALIŞMASI")

df = load_data(SHEET_ID, 0)

with st.expander("📋 KAYITLI HASTA LİSTESİ & SİLME", expanded=False):
    c1, c2 = st.columns([3, 1])
    with c
