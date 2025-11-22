import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# --- AYARLAR ---
SHEET_NAME = "H_Type_HT_Verileri"  # Google Sheet dosyanın tam adı
CASE_SHEET_NAME = "Vaka_Takip_Notlari" # İkinci bir sheet açıp adını bu yapmalısın (Opsiyonel)

# Sayfa Ayarları
st.set_page_config(page_title="NEÜ-KARDİYO", page_icon="❤️", layout="wide")

# --- GOOGLE SHEETS BAĞLANTISI ---
def connect_to_gsheets():
    # Streamlit Secrets'tan anahtarı alacağız
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
    client = gspread.authorize(creds)
    return client

def load_data(sheet_name):
    client = connect_to_gsheets()
    try:
        sheet = client.open(sheet_name).sheet1
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        # Dosya numarasını string yap
        if "Dosya Numarası" in df.columns:
            df["Dosya Numarası"] = df["Dosya Numarası"].astype(str)
        return df
    except Exception as e:
        return pd.DataFrame()

def save_data_row(sheet_name, data_dict, unique_col="Dosya Numarası"):
    client = connect_to_gsheets()
    sheet = client.open(sheet_name).sheet1
    
    # Mevcut verileri çek
    all_records = sheet.get_all_records()
    df = pd.DataFrame(all_records)
    
    if not df.empty and str(data_dict[unique_col]) in df[unique_col].astype(str).values:
        # GÜNCELLEME: Satırı bul ve sil, sonra yenisini ekle (Basit yöntem)
        # Gspread'de satır bulmak için hücre araması yapılır
        cell = sheet.find(str(data_dict[unique_col]))
        sheet.delete_rows(cell.row)
        st.toast(f"{data_dict[unique_col]} güncelleniyor...", icon="🔄")
    
    # Yeni veriyi sona ekle
    # DataFrame uyumu için değerleri listeye çevir
    # Ancak Sheet sütun sırası önemli. O yüzden önce header kontrolü yapılmalı.
    # Basitlik için: Eğer sheet boşsa önce başlıkları yaz
    if df.empty:
        sheet.append_row(list(data_dict.keys()))
    
    # Değerleri başlık sırasına göre dizeceğiz (Eğer sheet doluysa)
    if not df.empty:
        headers = sheet.row_values(1)
        row_to_add = []
        for header in headers:
            row_to_add.append(str(data_dict.get(header, "")))
        sheet.append_row(row_to_add)
    else:
        # İlk kayıt
        sheet.append_row(list(data_dict.values()))

# --- KENAR ÇUBUĞU ---
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/2966/2966486.png", width=100)
    st.title("NEÜ-KARDİYO")
    menu = st.radio("Menü", ["🏥 Veri Girişi (H-Type HT)", "📝 Vaka Takip (Notlar)"])
    st.markdown("---")
    st.info("✅ Veriler Google Sheets üzerinde güvenle saklanmaktadır.")
    
    # Kriterler
    with st.expander("📋 ÇALIŞMA KRİTERLERİ"):
        st.success("**DAHİL:** Son 6 ayda yeni tanı esansiyel HT")
        st.error("**HARİÇ:** Sekonder HT, KY, AKS, Cerrahi, Konjenital, Pulmoner HT, ABY")

# --- MOD 1: VAKA TAKİP ---
if menu == "📝 Vaka Takip (Notlar)":
    st.header("📝 Vaka Takip")
    # Not: Bu modül için de Google Sheet'te 'Vaka_Takip_Notlari' adında bir sayfa açmalısın.
    # Şimdilik hata vermemesi için burayı pasif bırakıyorum veya basit gösteriyorum.
    st.warning("Bu modül için Google Sheet'te 'Vaka_Takip_Notlari' adında bir dosya oluşturmalısınız.")

# --- MOD 2: VERİ GİRİŞİ ---
elif menu == "🏥 Veri Girişi (H-Type HT)":
    st.title("❤️ H-TYPE HİPERTANSİYON ÇALIŞMASI")
    
    tab_list, tab_form = st.tabs(["📋 HASTA LİSTESİ", "✍️ YENİ KAYIT / DÜZENLE"])

    with tab_list:
        st.button("🔄 Listeyi Yenile")
        df = load_data(SHEET_NAME)
        if not df.empty:
            st.metric("Toplam Hasta", len(df))
            st.dataframe(df, use_container_width=True)
        else:
            st.info("Veritabanı boş veya erişilemiyor.")

    with tab_form:
        with st.form("entry_form"):
            st.markdown("### 👤 Kimlik & Klinik")
            c1, c2 = st.columns(2)
            dosya_no = c1.text_input("Dosya Numarası (Zorunlu)")
            ad_soyad = c1.text_input("Adı Soyadı")
            hekim = c1.text_input("Veriyi Giren Hekim")
            basvuru = c1.date_input("Başvuru Tarihi", datetime.now())
            
            yas = c2.number_input("Yaş", step=1)
            cinsiyet = c2.radio("Cinsiyet", ["Erkek", "Kadın"], horizontal=True)
            boy = c2.number_input("Boy (cm)")
            kilo = c2.number_input("Kilo (kg)")
            if boy > 0: c2.caption(f"BMI: {kilo/((boy/100)**2):.2f}")
            
            st.markdown("---")
            col_ta1, col_ta2 = st.columns(2)
            ta_sis = col_ta1.number_input("TA Sistol", step=1)
            ta_dia = col_ta2.number_input("TA Diyastol", step=1)
            
            ekg = st.selectbox("EKG", ["NSR", "AF", "LBBB", "RBBB", "VPB", "SVT", "Diğer"])
            ilac = st.text_area("Kullandığı İlaçlar", height=60)
            baslanan = st.text_area("Başlanan İlaçlar", height=60)
            
            st.markdown("##### Komorbiditeler")
            cc1, cc2, cc3, cc4 = st.columns(4)
            dm = cc1.checkbox("DM"); kah = cc2.checkbox("KAH"); hpl = cc3.checkbox("HPL"); ky = cc4.checkbox("KY")
            inme = st.checkbox("İnme / TIA")
            diger = st.text_input("Diğer Hastalık")

            st.markdown("### 🩸 Laboratuvar")
            l1, l2, l3 = st.columns(3)
            hgb = l1.number_input("Hgb"); hct = l1.number_input("Hct"); wbc = l1.number_input("WBC")
            glukoz = l2.number_input("Glukoz"); krea = l2.number_input("Kreatinin"); na = l2.number_input("Na"); k_val = l2.number_input("K")
            ldl = l3.number_input("LDL"); hdl = l3.number_input("HDL"); trig = l3.number_input("Trig")
            homosis = st.number_input("Homosistein", help="Önemli Parametre")
            
            st.markdown("### 🫀 Eko")
            e1, e2, e3 = st.columns(3)
            lvef = e1.number_input("LVEF %"); lvedv = e1.number_input("LVEDV"); gls = e1.number_input("GLS %")
            mit_e = e2.number_input("Mitral E"); mit_a = e2.number_input("Mitral A"); sept_e = e2.number_input("Septal e'")
            tapse = e3.number_input("TAPSE"); spap = e3.number_input("sPAP")
            
            st.markdown("### 🖼️ Görüntü Linkleri")
            st.caption("Bulut sisteminde resim dosyası saklamak yerine, resimleri Google Drive'a yükleyip linkini buraya yapıştırınız.")
            img_link_ekg = st.text_input("EKG Drive Linki")
            img_link_eko = st.text_input("Eko/Bullseye Drive Linki")

            submitted = st.form_submit_button("💾 KAYDET (Google Sheets)", type="primary")
            
            if submitted:
                if not dosya_no:
                    st.error("Dosya numarası zorunludur!")
                else:
                    # Veri Sözlüğü
                    data = {
                        "Dosya Numarası": dosya_no, "Adı Soyadı": ad_soyad, "Tarih": str(basvuru), "Hekim": hekim,
                        "Yaş": yas, "Cinsiyet": cinsiyet, "Boy": boy, "Kilo": kilo,
                        "TA Sistol": ta_sis, "TA Diyastol": ta_dia, "EKG": ekg,
                        "İlaçlar": ilac, "Başlanan": baslanan,
                        "DM": dm, "KAH": kah, "HPL": hpl, "KY": ky, "İnme": inme, "Diğer": diger,
                        "Hgb": hgb, "Hct": hct, "Glukoz": glukoz, "Krea": krea, "Na": na, "K": k_val,
                        "LDL": ldl, "Homosistein": homosis,
                        "LVEF": lvef, "LVEDV": lvedv, "GLS": gls, "Mitral E": mit_e, "TAPSE": tapse,
                        "EKG_Link": img_link_ekg, "EKO_Link": img_link_eko
                    }
                    
                    save_data_row(SHEET_NAME, data)
                    st.success("✅ Kayıt Başarılı! Google Sheet güncellendi.")
