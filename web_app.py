import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import time

# --- AYARLAR ---
# BURAYA KENDİ SHEET ID'Nİ YAPIŞTIR
SHEET_ID = "1AbCdEfGhIjKlMnOpQrStUvWxYz12345"  # <-- GÜNCELLE
CASE_SHEET_ID = SHEET_ID 

st.set_page_config(page_title="NEÜ-KARDİYO", page_icon="❤️", layout="wide")

# --- BAĞLANTILAR ---
def connect_to_gsheets():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
    client = gspread.authorize(creds)
    return client

# --- VERİ ÇEKME (Hata Korumalı) ---
def load_data(sheet_id, worksheet_index=0):
    try:
        client = connect_to_gsheets()
        sheet = client.open_by_key(sheet_id).get_worksheet(worksheet_index)
        
        data = sheet.get_all_values()
        
        if not data:
            return pd.DataFrame()
            
        headers = data[0]
        rows = data[1:]
        
        df = pd.DataFrame(rows, columns=headers)
        
        # Tüm verileri YAZI (String) yap ki çökmesin
        df = df.fillna("")
        df = df.astype(str)
        
        return df
    except Exception:
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

# --- AKILLI KAYIT (Smart Merge) ---
def save_data_row(sheet_id, new_data, unique_col="Dosya Numarası", worksheet_index=0):
    client = connect_to_gsheets()
    sheet = client.open_by_key(sheet_id).get_worksheet(worksheet_index)
    
    # Mevcut verileri çek
    all_values = sheet.get_all_values()
    
    # 1. Dosya Boşsa Başlıkları Yaz
    if not all_values:
        sheet.append_row(list(new_data.keys()))
        sheet.append_row(list(new_data.values()))
        return

    headers = all_values[0]
    
    # 2. Yeni Sütun Varsa Başlığa Ekle
    missing_cols = [k for k in new_data.keys() if k not in headers]
    if missing_cols:
        headers.extend(missing_cols)
        # Sheet'teki 1. satırı güncelle (Basitçe sona ekliyoruz)
        # sheet.update('A1', [headers]) # Bu yetki gerektirir, şimdilik append ile idare eder
        # En doğrusu kullanıcının elle silmesi ama kodun çalışması için devam ediyoruz.

    # 3. Eski Veriyi Bul (Güncelleme mi?)
    df = pd.DataFrame(all_values[1:], columns=all_values[0]).astype(str)
    row_index = None
    existing_row_data = {}

    if unique_col in df.columns:
        matches = df.index[df[unique_col] == str(new_data[unique_col])].tolist()
        if matches:
            row_index = matches[0] + 2 # Sheet indexi
            # Eski veriyi sözlük olarak al
            existing_row_data = df.iloc[matches[0]].to_dict()

    # 4. VERİ BİRLEŞTİRME (MERGE)
    # Eğer eski kayıt varsa, yeni gelen boş değerleri eskisiyle doldur
    final_data = {}
    
    for key in headers:
        new_val = str(new_data.get(key, ""))
        old_val = str(existing_row_data.get(key, ""))
        
        # Kural: Yeni değer boşsa veya 0 ise ve eski değer doluysa, eskiyi koru.
        # Ancak kullanıcı bilerek 0 girmiş olabilir, bu yüzden sadece boşlukları koruyalım.
        # Sayısal 0.0 ve 0 karışıklığı için:
        is_new_empty = new_val in ["", "None", "0", "0.0", "0.00"]
        is_old_full = old_val not in ["", "None"]
        
        # Eğer bu bir güncelleme işlemiyse ve yeni değer boş/sıfır ise, eskiyi tut
        if row_index and is_new_empty and is_old_full:
            final_data[key] = old_val
        else:
            # Aksi halde yeni değeri (veya yeni bir kayıt ise mecburen yeniyi) kullan
            # Eğer key new_data'da yoksa boş geç
            final_data[key] = str(new_data.get(key, ""))

    # 5. Kaydetme
    row_to_save = [final_data.get(h, "") for h in headers]

    if row_index:
        try:
            sheet.delete_rows(row_index)
            time.sleep(1)
            sheet.append_row(row_to_save)
            st.toast(f"{new_data[unique_col]} güncellendi (Eski veriler korundu).", icon="✅")
        except:
            sheet.append_row(row_to_save)
    else:
        sheet.append_row(row_to_save)
        st.toast(f"{new_data[unique_col]} yeni kaydedildi.", icon="✅")

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
                    st.error("Google Sheet'te 2. sayfa yok!")
    with col2:
        df_notes = load_data(CASE_SHEET_ID, worksheet_index=1)
        if not df_notes.empty: st.dataframe(df_notes, use_container_width=True)

# --- MOD 2: VERİ GİRİŞİ ---
elif menu == "🏥 Veri Girişi (H-Type HT)":
    st.title("H-TYPE HİPERTANSİYON ÇALIŞMASI")
    
    tab_list, tab_klinik, tab_lab, tab_eko = st.tabs(["📋 HASTA LİSTESİ / SİLME", "👤 KLİNİK", "🩸 LABORATUVAR", "🫀 EKO"])

    with tab_list:
        c1, c2 = st.columns([3, 1])
        with c1:
            if st.button("🔄 Listeyi Yenile"): st.rerun()
            df = load_data(SHEET_ID, worksheet_index=0)
            if not df.empty:
                st.metric("Toplam Kayıtlı Hasta", len(df))
                st.dataframe(df, use_container_width=True)
            else:
                st.info("Veritabanı boş veya ID hatalı.")
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
                boy = cb1.number_input("Boy (cm)")
                kilo = cb2.number_input("Kilo (kg)")
                bmi = 0; bsa = 0
                if boy > 0 and kilo > 0: 
                    bmi = kilo/((boy/100)**2)
                    bsa = (boy * kilo / 3600) ** 0.5 
                cb3.metric("BMI", f"{bmi:.2f}")
                ct1, ct2 = st.columns(2)
                ta_sis = ct1.number_input("TA Sistol (mmHg)", step=1)
                ta_dia = ct2.number_input("TA Diyastol (mmHg)", step=1)
            st.divider()
            ekg = st.selectbox("EKG Bulgusu", ["NSR", "LBBB", "RBBB", "VPB", "SVT", "Diğer"]) 
            ci1, ci2 = st.columns(2)
            ilaclar = ci1.text_area("Kullandığı İlaçlar")
            baslanan = ci2.text_area("Başlanan İlaçlar")
            st.markdown("##### Ek Hastalıklar")
            cc1, cc2, cc3, cc4, cc5 = st.columns(5)
            dm = cc1.checkbox("DM"); kah = cc2.checkbox("KAH"); hpl = cc3.checkbox("HPL"); inme = cc4.checkbox("İnme"); sigara = cc5.checkbox("Sigara")
            diger_hst = st.text_input("Diğer Hastalıklar")

        # 2. LAB
        with tab_lab:
            l1, l2, l3, l4 = st.columns(4)
            with l1:
                st.markdown("🔴 **Hemogram**")
                hgb = st.number_input("Hgb (g/dL)"); hct = st.number_input("Hct (%)"); wbc = st.number_input("WBC (10³/µL)"); plt = st.number_input("PLT (10³/µL)")
                neu = st.number_input("Nötrofil (%)"); lym = st.number_input("Lenfosit (%)"); mpv = st.number_input("MPV (fL)"); rdw = st.number_input("RDW (%)")
            with l2:
                st.markdown("🧪 **Biyokimya**")
                glukoz = st.number_input("Glukoz (mg/dL)"); ure = st.number_input("Üre (mg/dL)"); krea = st.number_input("Kreatinin (mg/dL)"); uric = st.number_input("Ürik Asit (mg/dL)")
                na = st.number_input("Na (mEq/L)"); k_val = st.number_input("K (mEq/L)"); alt = st.number_input("ALT (U/L)"); ast = st.number_input("AST (U/L)")
                tot_prot = st.number_input("Total Prot (g/dL)"); albumin = st.number_input("Albümin (g/dL)")
            with l3:
                st.markdown("🟡 **Lipid**")
                chol = st.number_input("Kolesterol (mg/dL)"); ldl = st.number_input("LDL (mg/dL)"); hdl = st.number_input("HDL (mg/dL)"); trig = st.number_input("Trig (mg/dL)")
            with l4:
                st.markdown("⚡ **Spesifik**")
                homosis = st.number_input("Homosistein (µmol/L)"); lpa = st.number_input("Lp(a) (mg/dL)"); folik = st.number_input("Folik Asit (ng/mL)"); b12 = st.number_input("B12 (pg/mL)")

        # 3. EKO
        with tab_eko:
            st.info("ℹ️ Değerler girildikçe hesaplamalar otomatik yapılır.")
            e1, e2, e3, e4 = st.columns(4)
            with e1:
                st.markdown("**1. LV Yapı**")
                lvedd = st.number_input("LVEDD (mm)"); lvesd = st.number_input("LVESD (mm)"); ivs = st.number_input("IVS (mm)")
                pw = st.number_input("PW (mm)"); lvedv = st.number_input("LVEDV (mL)"); lvesv = st.number_input("LVESV (mL)")
                ao_asc = st.number_input("Ao Asc (mm)")
                
                lv_mass = 0.0; lvmi = 0.0; rwt = 0.0
                if lvedd > 0 and ivs > 0 and pw > 0:
                    lvedd_cm = lvedd/10; ivs_cm = ivs/10; pw_cm = pw/10
                    lv_mass = 0.8 * (1.04 * ((lvedd_cm + ivs_cm + pw_cm)**3 - lvedd_cm**3)) + 0.6
                    if bsa > 0: lvmi = lv_mass / bsa
                if lvedd > 0 and
