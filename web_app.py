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
        
        data = sheet.get_all_values()
        
        if not data:
            return pd.DataFrame()
            
        headers = data[0]
        rows = data[1:]
        
        # AYNI İSİMLİ SÜTUNLARI DÜZELT
        seen = {}
        unique_headers = []
        for h in headers:
            if h in seen:
                seen[h] += 1
                unique_headers.append(f"{h}_{seen[h]}")
            else:
                seen[h] = 0
                unique_headers.append(h)
        
        # TABLOYU OLUŞTUR VE HEPSİNİ YAZIYA ÇEVİR
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
    
    clean_data = {k: str(v) if v is not None else "" for k, v in data_dict.items()}
    
    all_values = sheet.get_all_values()
    
    if not all_values:
        sheet.append_row(list(clean_data.keys()))
        sheet.append_row(list(clean_data.values()))
        return

    headers = all_values[0]
    
    missing_cols = [key for key in clean_data.keys() if key not in headers]
