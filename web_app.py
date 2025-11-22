import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# --- AYARLAR ---
SHEET_NAME = "H_Type_HT_Verileri"
CASE_SHEET_NAME = "Vaka_Takip_Notlari"

st.set_page_config(page_title="NEÜ-KARDİYO", page_icon="❤️", layout="wide")

# --- GOOGLE SHEETS BAĞLANTISI ---
def connect_to_gsheets():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
    client = gspread.authorize(creds)
    return client

def load_data(sheet_name):
    try:
        client = connect_to_gsheets()
        sheet = client.open(sheet_name).sheet1
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        if "Dosya Numarası" in df.columns:
            df["Dosya Numarası"] = df["Dosya Numarası"].astype(str)
        return df
    except Exception as e:
        return pd.DataFrame()

def save_data_row(sheet_name, data_dict, unique_col="Dosya Numarası"):
    client = connect_to_gsheets()
    sheet = client.open(sheet_name).sheet1
    
    # Tüm verileri çek
    all_records = sheet.get_all_records()
    df = pd.DataFrame(all_records)
    
    # Eğer dosya numarası varsa, o satırı bul ve güncelle (Silip yeniden ekleme mantığı)
    if not df.empty and str(data_dict[unique_col]) in df[unique_col].astype(str).values:
        cell = sheet.find(str(data_dict[unique_col]))
        sheet.delete_rows(cell.row)
        st.toast(f"{data_dict[unique_col]} güncelleniyor...", icon="🔄")
    
    # Başlık kontrolü ve Yazma
    if df.empty:
        sheet.append_row(list(data_dict.keys()))
        sheet.append_row(list(data_dict.values()))
    else:
        # Var olan başlık sırasına göre veriyi düzenle
        headers = sheet.row_values(1)
        row_to_add = []
        for header in headers:
            row_to_add.append(str(data_dict.get(header, "")))
        sheet.append_row(row_to_add)

# --- KENAR ÇUBUĞU ---
with st.sidebar:
    st.title("❤️ NEÜ-KARDİYO")
    menu = st.radio("Menü", ["🏥 Veri Girişi (H-Type HT)", "📝 Vaka Takip (Notlar)"])
    st.divider()
    with st.expander("📋 ÇALIŞMA KRİTERLERİ", expanded=True):
        st.success("**✅ DAHİL:** Son 6 ayda yeni tanı esansiyel HT")
        st.error("**⛔ HARİÇ:** Sekonder HT, KY, AKS, Cerrahi, Konjenital, Pulmoner HT, ABY")

# --- MOD 1: VAKA TAKİP ---
if menu == "📝 Vaka Takip (Notlar)":
    st.header("📝 Vaka Takip Defteri")
    
    col1, col2 = st.columns([1, 2])
    with col1:
        with st.form("note_form", clear_on_submit=True):
            st.subheader("Yeni Not")
            n_dosya = st.text_input("Dosya No")
            n_ad = st.text_input("Hasta Adı")
            n_dr = st.text_input("Sorumlu Doktor")
            n_plan = st.text_area("Not / Plan", height=100)
            if st.form_submit_button("Notu Kaydet"):
                note_data = {"Tarih": str(datetime.now().date()), "Dosya No": n_dosya, "Hasta": n_ad, "Doktor": n_dr, "Not": n_plan}
                save_data_row(CASE_SHEET_NAME, note_data, unique_col="Dosya No") # Notlarda update mantığı yerine ekleme de yapılabilir ama şimdilik standart tuttum
                st.success("Kaydedildi")
    
    with col2:
        df_notes = load_data(CASE_SHEET_NAME)
        if not df_notes.empty: st.dataframe(df_notes, use_container_width=True)

# --- MOD 2: VERİ GİRİŞİ ---
elif menu == "🏥 Veri Girişi (H-Type HT)":
    st.title("H-TYPE HİPERTANSİYON ÇALIŞMASI")
    
    tab_list, tab_klinik, tab_lab, tab_eko, tab_img = st.tabs(["📋 HASTA LİSTESİ", "👤 KLİNİK", "🩸 LABORATUVAR", "🫀 EKO", "🖼️ GÖRÜNTÜ"])

    with tab_list:
        if st.button("🔄 Listeyi Yenile"):
            st.rerun()
        df = load_data(SHEET_NAME)
        if not df.empty:
            st.metric("Toplam Kayıtlı Hasta", len(df))
            st.dataframe(df, use_container_width=True)
        else:
            st.info("Veritabanı boş veya erişilemiyor.")

    # --- FORM BAŞLANGICI ---
    with st.form("main_form"):
        st.caption("Tüm sekmeleri doldurduktan sonra en alttaki KAYDET butonuna basınız.")
        
        # 1. KLİNİK SEKME
        with tab_klinik:
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("##### Kimlik")
                dosya_no = st.text_input("Dosya Numarası (Zorunlu)")
                ad_soyad = st.text_input("Adı Soyadı")
                basvuru = st.date_input("Başvuru Tarihi")
                hekim = st.text_input("Veriyi Giren Hekim")
                iletisim = st.text_input("İletişim")
            with c2:
                st.markdown("##### Fizik Muayene")
                col_y, col_c = st.columns(2)
                yas = col_y.number_input("Yaş", step=1)
                cinsiyet = col_c.radio("Cinsiyet", ["Erkek", "Kadın"], horizontal=True)
                
                cb1, cb2, cb3 = st.columns(3)
                boy = cb1.number_input("Boy (cm)")
                kilo = cb2.number_input("Kilo (kg)")
                bmi = 0
                if boy > 0: bmi = kilo/((boy/100)**2)
                cb3.metric("BMI", f"{bmi:.2f}")
                
                ct1, ct2 = st.columns(2)
                ta_sis = ct1.number_input("TA Sistol (mmHg)", step=1)
                ta_dia = ct2.number_input("TA Diyastol (mmHg)", step=1)
            
            st.divider()
            ekg = st.selectbox("EKG Bulgusu", ["NSR", "AF", "LBBB", "RBBB", "VPB", "SVT", "Diğer"])
            
            ci1, ci2 = st.columns(2)
            ilaclar = ci1.text_area("Kullandığı İlaçlar", height=70)
            baslanan = ci2.text_area("Başlanan İlaçlar", height=70)
            
            st.markdown("##### Ek Hastalıklar")
            cc1, cc2, cc3, cc4, cc5 = st.columns(5)
            dm = cc1.checkbox("DM"); kah = cc2.checkbox("KAH"); hpl = cc3.checkbox("HPL"); ky = cc4.checkbox("KY"); inme = cc5.checkbox("İnme")
            diger_hst = st.text_input("Diğer Hastalıklar")

        # 2. LABORATUVAR SEKME (Full Detay)
        with tab_lab:
            l1, l2, l3, l4 = st.columns(4)
            
            with l1:
                st.markdown("🔴 **Hemogram**")
                hgb = st.number_input("Hgb (g/dL)")
                hct = st.number_input("Hct (%)")
                wbc = st.number_input("WBC (10^3)")
                plt = st.number_input("PLT (10^3)")
                neu = st.number_input("Nötrofil")
                lym = st.number_input("Lenfosit")
                mpv = st.number_input("MPV")
                rdw = st.number_input("RDW")

            with l2:
                st.markdown("🧪 **Rutin Biyokimya**")
                glukoz = st.number_input("Glukoz")
                ure = st.number_input("Üre")
                krea = st.number_input("Kreatinin")
                uric = st.number_input("Ürik Asit")
                na = st.number_input("Sodyum (Na)")
                k_val = st.number_input("Potasyum (K)")
                alt = st.number_input("ALT")
                ast = st.number_input("AST")
                tot_prot = st.number_input("Total Protein")
                albumin = st.number_input("Albümin")

            with l3:
                st.markdown("🟡 **Lipid Paneli**")
                chol = st.number_input("Total Kolesterol")
                ldl = st.number_input("LDL")
                hdl = st.number_input("HDL")
                trig = st.number_input("Trigliserid")
                lpa = st.number_input("Lipoprotein-a")

            with l4:
                st.markdown("⚡ **Spesifik**")
                homosis = st.number_input("Homosistein", help="Çalışma için anahtar parametre")
                crp = st.number_input("CRP")
                folik = st.number_input("Folik Asit")
                b12 = st.number_input("B12 Vitamini")

        # 3. EKO SEKME (Bilimsel Sıralı & Hesaplamalı)
        with tab_eko:
            st.info("ℹ️ Oranlar (LACi, E/A vb.) verileri girince otomatik hesaplanıp kaydedilecektir.")
            e1, e2, e3, e4 = st.columns(4)
            
            with e1:
                st.markdown("**1. LV Boyut & Yapı**")
                lvedd = st.number_input("LV EDD (mm)")
                lvesd = st.number_input("LV ESD (mm)")
                ivs = st.number_input("İVS (mm)")
                pw = st.number_input("PW (mm)")
                lvedv = st.number_input("LVEDV (mL)")
                lvesv = st.number_input("LVESV (mL)")
                mass_idx = st.number_input("LV Kütle İndeksi")
                ao_asc = st.number_input("Asendan Aort (mm)")

            with e2:
                st.markdown("**2. Sistolik Fonksiyon**")
                lvef = st.number_input("LVEF (%)")
                sv = st.number_input("SV (Atım Hacmi)")
                lvot_vti = st.number_input("LVOT VTI")
                gls = st.number_input("GLS Strain %")
                gcs = st.number_input("GCS Strain %")
                sd_ls = st.number_input("SD-LS-syst %")

            with e3:
                st.markdown("**3. Diyastolik & LA**")
                mit_e = st.number_input("Mitral E")
                mit_a = st.number_input("Mitral A")
                sept_e = st.number_input("Septal e'")
                lat_e = st.number_input("Lateral e'")
                laedv = st.number_input("LAEDV (mL)")
                laesv = st.number_input("LAESV (mL)")
                la_strain = st.number_input("LA Strain %")
                
                # Anlık Hesap Gösterimi
                if mit_a > 0: st.caption(f"🔵 E/A: {mit_e/mit_a:.2f}")
                if sept_e > 0: st.caption(f"🔵 E/e': {mit_e/sept_e:.2f}")
                if lvedv > 0: st.caption(f"🔵 LACi: {laedv/lvedv:.2f}")

            with e4:
                st.markdown("**4. Sağ Kalp**")
                tapse = st.number_input("RV TAPSE")
                rv_sm = st.number_input("RV Sm")
                spap = st.number_input("sPAP")
                rvot_vti = st.number_input("RVOT VTI")
                rvot_acct = st.number_input("RVOT accT")
                
                if rv_sm > 0: st.caption(f"🔵 TAPSE/Sm: {tapse/rv_sm:.2f}")

        # 4. GÖRÜNTÜ SEKME
        with tab_img:
            st.warning("Resimleri Google Drive'a yükleyip linklerini buraya yapıştırınız.")
            img_ekg = st.text_input("EKG Linki")
            img_bull = st.text_input("Bull-eye Linki")
            img_holter = st.text_input("Holter Rapor Linki")

        # KAYDET BUTONU
        submitted = st.form_submit_button("💾 KAYDET / GÜNCELLE", type="primary")
        
        if submitted:
            if not dosya_no:
                st.error("Dosya Numarası Girilmelidir!")
            else:
                # Hesaplamalar
                mit_ea = mit_e/mit_a if mit_a>0 else ""
                mit_ee = mit_e/sept_e if sept_e>0 else ""
                laci = laedv/lvedv if lvedv>0 else ""
                tapse_sm = tapse/rv_sm if rv_sm>0 else ""
                
                data_row = {
                    "Dosya Numarası": dosya_no, "Adı Soyadı": ad_soyad, "Tarih": str(basvuru), "Hekim": hekim,
                    "Yaş": yas, "Cinsiyet": cinsiyet, "Boy": boy, "Kilo": kilo, "BMI": bmi,
                    "TA Sistol": ta_sis, "TA Diyastol": ta_dia, "EKG": ekg, 
                    "İlaçlar": ilaclar, "Başlanan İlaçlar": baslanan,
                    "DM": dm, "KAH": kah, "HPL": hpl, "KY": ky, "İnme": inme, "Diğer Hast": diger_hst,
                    # LAB
                    "Hgb": hgb, "Hct": hct, "WBC": wbc, "PLT": plt, "Neu": neu, "Lym": lym, "MPV": mpv, "RDW": rdw,
                    "Glukoz": glukoz, "Üre": ure, "Kreatinin": krea, "Ürik Asit": uric, "Na": na, "K": k_val, 
                    "ALT": alt, "AST": ast, "Tot. Prot": tot_prot, "Albümin": albumin,
                    "Chol": chol, "LDL": ldl, "HDL": hdl, "Trig": trig, "Lp(a)": lpa,
                    "Homosistein": homosis, "CRP": crp, "Folik Asit": folik, "B12": b12,
                    # EKO
                    "LVEDD": lvedd, "LVESD": lvesd, "IVS": ivs, "PW": pw, "LVEDV": lvedv, "LVESV": lvesv, "LV Mass": mass_idx, "Ao Asc": ao_asc,
                    "LVEF": lvef, "SV": sv, "LVOT VTI": lvot_vti, "GLS": gls, "GCS": gcs, "SD-LS": sd_ls,
                    "Mitral E": mit_e, "Mitral A": mit_a, "Mitral E/A": mit_ea, "Septal e'": sept_e, "Lateral e'": lat_e, "Mitral E/e'": mit_ee,
                    "LAEDV": laedv, "LAESV": laesv, "LA Strain": la_strain, "LACi": laci,
                    "TAPSE": tapse, "RV Sm": rv_sm, "TAPSE/Sm": tapse_sm, "sPAP": spap, "RVOT VTI": rvot_vti, "RVOT accT": rvot_acct,
                    # LINKLER
                    "Link_EKG": img_ekg, "Link_BullEye": img_bull, "Link_Holter": img_holter
                }
                
                save_data_row(SHEET_NAME, data_row)
                st.success(f"✅ {dosya_no} nolu hasta başarıyla kaydedildi!")
