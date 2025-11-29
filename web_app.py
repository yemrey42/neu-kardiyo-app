import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import time

# --- AYARLAR ---
# Senin verdiğin ID
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

# --- VERİ ÇEKME (TABLO ÇÖKMESİNİ ENGELLEYEN SAĞLAM VERSİYON) ---
def load_data(sheet_id, worksheet_index=0):
    try:
        client = connect_to_gsheets()
        sheet = client.open_by_key(sheet_id).get_worksheet(worksheet_index)
        
        # Tüm verileri ham olarak çek
        data = sheet.get_all_values()
        
        if not data or len(data) < 2:
            return pd.DataFrame()
            
        headers = data[0]
        raw_rows = data[1:]
        
        # 1. AYNI İSİMLİ SÜTUNLARI DÜZELT (Header Fix)
        seen = {}
        unique_headers = []
        for h in headers:
            h = str(h).strip() # Boşlukları temizle
            if h in seen:
                seen[h] += 1
                unique_headers.append(f"{h}_{seen[h]}")
            else:
                seen[h] = 0
                unique_headers.append(h)
        
        # 2. EKSİK HÜCRELERİ DOLDUR (Row Fix)
        # Bazı satırlar kısa gelebilir, onları başlık sayısı kadar uzatıyoruz
        num_cols = len(unique_headers)
        fixed_rows = []
        for row in raw_rows:
            if len(row) < num_cols:
                row += [""] * (num_cols - len(row))
            fixed_rows.append(row)
        
        # 3. TABLOYU OLUŞTUR VE YAZIYA ÇEVİR (Type Fix)
        df = pd.DataFrame(fixed_rows, columns=unique_headers)
        df = df.astype(str) # Her şeyi yazı yap ki çökmesin
        
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

# --- KAYIT İŞLEMİ (AKILLI GÜNCELLEME) ---
def save_data_row(sheet_id, data_dict, unique_col="Dosya Numarası", worksheet_index=0):
    client = connect_to_gsheets()
    sheet = client.open_by_key(sheet_id).get_worksheet(worksheet_index)
    
    # Gelen veriyi temizle (None -> Boş String)
    new_data = {k: str(v) if v is not None else "" for k, v in data_dict.items()}
    
    all_values = sheet.get_all_values()
    
    # Dosya boşsa başlıkları yaz ve çık
    if not all_values:
        sheet.append_row(list(new_data.keys()))
        sheet.append_row(list(new_data.values()))
        return

    headers = all_values[0]
    
    # Eksik sütun varsa header listesine ekle (Sheet'e de yansıması için)
    # Burada basitlik adına yeni sütunları sona ekliyoruz.
    # Not: Sheet'teki 1. satırı güncellemek yerine veriyi kaydırarak ekleyeceğiz.
    # Google Sheets otomatik genişler.
    
    # Yeni veri başlıklarını kontrol et
    for k in new_data.keys():
        if k not in headers:
            headers.append(k)
            # Sheet'in 1. satırını güncellemek gerekir (Opsiyonel ama iyi olur)
            # Şimdilik sadece Python tarafındaki listeyi güncelleyelim, 
            # Google Sheets yeni sütuna veri gelince otomatik açar.

    # --- ESKİ VERİYİ KORUMA (MERGE) ---
    # Dosya numarası var mı kontrol et
    row_index_to_update = None
    existing_row_data = {}
    
    # Pandas ile arama yap (Daha hızlı ve güvenli)
    try:
        # Mevcut veriyi DataFrame'e çevir
        df_temp = pd.DataFrame(all_values[1:], columns=all_values[0]).astype(str)
        if unique_col in df_temp.columns:
            matches = df_temp.index[df_temp[unique_col] == str(new_data[unique_col])].tolist()
            if matches:
                row_index_to_update = matches[0] + 2 # Sheet satır numarası (1-based + header)
                # Eski veriyi al
                existing_row_data = df_temp.iloc[matches[0]].to_dict()
    except:
        pass

    # Kaydedilecek satırı oluştur
    row_to_save = []
    
    for h in headers:
        new_val = str(new_data.get(h, ""))
        old_val = str(existing_row_data.get(h, ""))
        
        # KURAL: Eğer yeni değer BOŞSA ve eski değer DOLUYSA -> Eskiyi Koru
        # (Böylece sadece Lab girerken Klinik silinmez)
        if new_val == "" and old_val != "":
            row_to_save.append(old_val)
        elif new_val != "":
            row_to_save.append(new_val)
        else:
            row_to_save.append("")

    # --- YAZMA İŞLEMİ ---
    if row_index_to_update:
        try:
            # Eski satırı sil
            sheet.delete_rows(row_index_to_update)
            time.sleep(1) # Google'a zaman tanı
            # Güncellenmiş satırı sona ekle
            # (Araya eklemek sütun kaymasına sebep olabilir, sona eklemek en güvenlisidir)
            sheet.append_row(row_to_save)
            st.toast(f"✅ {new_data[unique_col]} güncellendi.", icon="🔄")
        except:
            # Silmede hata olursa direkt ekle
            sheet.append_row(row_to_save)
    else:
        # Yeni kayıt
        sheet.append_row(row_to_save)
        st.toast(f"✅ {new_data[unique_col]} kaydedildi.", icon="CD")

# --- ARAYÜZ ---
with st.sidebar:
    st.title("❤️ NEÜ-KARDİYO")
    menu = st.radio("Menü", ["🏥 Veri Girişi (H-Type HT)", "📝 Vaka Takip (Notlar)"])
    st.divider()
    with st.expander("📋 ÇALIŞMA KRİTERLERİ", expanded=True):
        st.success("**✅ DAHİL:** Son 6 ayda yeni tanı esansiyel HT")
        st.error("**⛔ HARİÇ:** Sekonder HT, KY, AKS, Cerrahi, Konjenital, Pulmoner HT, ABY, **AF**")

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
                    st.error("Google Sheet'te 2. sayfa yok!")
    with col2:
        df_notes = load_data(CASE_SHEET_ID, worksheet_index=1)
        if not df_notes.empty: st.dataframe(df_notes, use_container_width=True)

elif menu == "🏥 Veri Girişi (H-Type HT)":
    
    # --- EKG ANİMASYONU ---
    st.markdown("""
    <style>
    .ecg-container { background: #000; height: 80px; width: 100%; overflow: hidden; position: relative; border-radius: 8px; border: 1px solid #333; margin-bottom: 10px; }
    .ecg-line {
        background-image: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="300" height="80" viewBox="0 0 300 80"><path d="M0 40 L20 40 L25 35 L30 40 L40 40 L42 45 L45 10 L48 70 L52 40 L60 40 L65 30 L75 30 L80 40 L300 40" stroke="%2300ff00" stroke-width="2" fill="none"/></svg>');
        width: 200%; height: 100%; position: absolute; animation: slide 3s linear infinite; background-repeat: repeat-x;
    }
    @keyframes slide { from { transform: translateX(0); } to { transform: translateX(-300px); } }
    </style>
    <div class="ecg-container"><div class="ecg-line"></div></div>
    """, unsafe_allow_html=True)
    
    st.title("H-TYPE HİPERTANSİYON ÇALIŞMASI")
    
    tab_list, tab_klinik, tab_lab, tab_eko = st.tabs(["📋 HASTA LİSTESİ / SİLME", "👤 KLİNİK", "🩸 LABORATUVAR", "🫀 EKO"])

    with tab_list:
        c1, c2 = st.columns([3, 1])
        with c1:
            if st.button("🔄 Listeyi Yenile"): st.rerun()
            df = load_data(SHEET_ID, worksheet_index=0)
            if not df.empty:
                st.metric("Toplam Kayıtlı Hasta", len(df))
                
                # Sadeleştirilmiş Liste
                cols_to_show = ["Dosya Numarası", "Adı Soyadı", "Tarih", "Hekim", "Yaş", "Cinsiyet"]
                # Mevcut sütunları filtrele
                final_cols = [c for c in cols_to_show if c in df.columns]
                
                if final_cols:
                    st.dataframe(df[final_cols], use_container_width=True)
                else:
                    st.dataframe(df, use_container_width=True)
            else:
                st.info("Veritabanı boş.")
        
        with c2:
            st.error("⚠️ SİLME")
            if not df.empty:
                try:
                    del_list = df["Dosya Numarası"].astype(str).tolist()
                    del_select = st.selectbox("Dosya No Seç", del_list)
                    if st.button("🗑️ SİL"):
                        if delete_patient(SHEET_ID, del_select):
                            st.success("Silindi!"); st.rerun()
                        else: st.error("Hata!")
                except: pass

    with st.form("main_form"):
        # 1. KLİNİK
        with tab_klinik:
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("##### Kimlik")
                dosya_no = st.text_input("Dosya Numarası (Zorunlu)")
                ad_soyad = st.text_input("Adı Soyadı")
                basvuru = st.date_input("Başvuru Tarihi")
                hekim = st.text_input("Veriyi Giren Hekim (Zorunlu)")
                iletisim = st.text_input("İletişim")
            with c2:
                st.markdown("##### Fizik Muayene")
                col_y, col_c = st.columns(2)
                yas = col_y.number_input("Yaş", step=1)
                cinsiyet = col_c.radio("Cinsiyet", ["Erkek", "Kadın"], horizontal=True)
                cb1, cb2, cb3 = st.columns(3)
                boy = cb1.number
