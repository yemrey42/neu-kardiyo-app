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

# --- GÜVENLİ VERİ ÇEKME ---
def load_data(sheet_id, worksheet_index=0):
    try:
        client = connect_to_gsheets()
        sheet = client.open_by_key(sheet_id).get_worksheet(worksheet_index)
        
        data = sheet.get_all_values()
        
        if not data:
            return pd.DataFrame()
            
        headers = data[0]
        rows = data[1:]
        
        # Sütun isimleri çakışmasın
        seen = {}
        unique_headers = []
        for h in headers:
            if h in seen:
                seen[h] += 1
                unique_headers.append(f"{h}_{seen[h]}")
            else:
                seen[h] = 0
                unique_headers.append(h)
        
        df = pd.DataFrame(rows, columns=unique_headers)
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

# --- KAYIT ---
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
    if missing_cols:
        headers.extend(missing_cols)

    row_to_save = []
    for h in headers:
        row_to_save.append(clean_data.get(h, ""))
    for k in clean_data.keys():
        if k not in headers:
            row_to_save.append(clean_data[k])

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
                
                # --- SADELEŞTİRİLMİŞ LİSTE GÖRÜNÜMÜ ---
                # Sadece önemli sütunları seçelim
                onemli_sutunlar = ["Dosya Numarası", "Adı Soyadı", "Tarih", "Hekim", "Yaş", "Cinsiyet"]
                # Eğer veritabanında bu sütunlar varsa, sadece onları göster
                mevcut_sutunlar = [col for col in onemli_sutunlar if col in df.columns]
                
                if mevcut_sutunlar:
                    st.dataframe(df[mevcut_sutunlar], use_container_width=True)
                else:
                    # Sütun isimleri uyuşmazsa yine de hepsini göster (Yedek plan)
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
                if lvedd > 0 and pw > 0: rwt = (2 * pw) / lvedd
                st.markdown(f"🔵 **Mass:** {lv_mass:.1f} g | **LVMi:** {lvmi:.1f} | **RWT:** {rwt:.2f}")

            with e2:
                st.markdown("**2. Sistolik**")
                lvef = st.number_input("LVEF (%)"); sv = st.number_input("SV (mL)"); lvot_vti = st.number_input("LVOT VTI (cm)")
                gls = st.number_input("GLS Strain (%)"); gcs = st.number_input("GCS Strain (%)"); sd_ls = st.number_input("SD-LS (%)")

            with e3:
                st.markdown("**3. Diyastolik**")
                mit_e = st.number_input("Mitral E (cm/sn)"); mit_a = st.number_input("Mitral A (cm/sn)")
                sept_e = st.number_input("Septal e' (cm/sn)"); lat_e = st.number_input("Lateral e' (cm/sn)")
                laedv = st.number_input("LAEDV (mL)"); laesv = st.number_input("LAESV (mL)"); la_strain = st.number_input("LA Strain (%)")
                mit_ea = mit_e/mit_a if mit_a > 0 else 0.0
                mit_ee = mit_e/sept_e if sept_e > 0 else 0.0
                laci = laedv/lvedv if lvedv > 0 else 0.0
                st.markdown(f"🔵 **E/A:** {mit_ea:.2f} | **E/e':** {mit_ee:.2f} | **LACi:** {laci:.2f}")

            with e4:
                st.markdown("**4. Sağ Kalp**")
                tapse = st.number_input("TAPSE (mm)"); rv_sm = st.number_input("RV Sm (cm/sn)")
                spap = st.number_input("sPAP (mmHg)"); rvot_vti = st.number_input("RVOT VTI (cm)"); rvot_acct = st.number_input("RVOT accT (ms)")
                tapse_sm = tapse/rv_sm if rv_sm > 0 else 0.0
                st.markdown(f"🔵 **TAPSE/Sm:** {tapse_sm:.2f}")

        st.write("") 
        submitted = st.form_submit_button("💾 KAYDET / GÜNCELLE", type="primary")
        
        if submitted:
            if not dosya_no or not hekim:
                st.error("⚠️ Dosya No ve Hekim zorunlu!")
            else:
                mit_ea = mit_e/mit_a if mit_a>0 else 0.0
                mit_ee = mit_e/sept_e if sept_e>0 else 0.0
                laci = laedv/lvedv if lvedv>0 else 0.0
                tapse_sm = tapse/rv_sm if rv_sm>0 else 0.0
                
                data_row = {
                    "Dosya Numarası": dosya_no, "Adı Soyadı": ad_soyad, "Tarih": str(basvuru), "Hekim": hekim,
                    "Yaş": yas, "Cinsiyet": cinsiyet, "Boy": boy, "Kilo": kilo, "BMI": bmi, "BSA": bsa,
                    "TA Sistol": ta_sis, "TA Diyastol": ta_dia, "EKG": ekg, 
                    "İlaçlar": ilaclar, "Başlanan İlaçlar": baslanan,
                    "DM": dm, "KAH": kah, "HPL": hpl, "İnme": inme, "Sigara": sigara, "Diğer Hast": diger_hst,
                    "Hgb": hgb, "Hct": hct, "WBC": wbc, "PLT": plt, "Neu": neu, "Lym": lym, "MPV": mpv, "RDW": rdw,
                    "Glukoz": glukoz, "Üre": ure, "Kreatinin": krea, "Ürik Asit": uric, "Na": na, "K": k_val, 
                    "ALT": alt, "AST": ast, "Tot. Prot": tot_prot, "Albümin": albumin,
                    "Chol": chol, "LDL": ldl, "HDL": hdl, "Trig": trig, 
                    "Lp(a)": lpa, "Homosistein": homosis, "Folik Asit": folik, "B12": b12,
                    "LVEDD": lvedd, "LVESD": lvesd, "IVS": ivs, "PW": pw, "LVEDV": lvedv, "LVESV": lvesv, 
                    "LV Mass": lv_mass, "LVMi": lvmi, "RWT": rwt, "Ao Asc": ao_asc,
                    "LVEF": lvef, "SV": sv, "LVOT VTI": lvot_vti, "GLS": gls, "GCS": gcs, "SD-LS": sd_ls,
                    "Mitral E": mit_e, "Mitral A": mit_a, "Mitral E/A": mit_ea, "Septal e'": sept_e, "Lateral e'": lat_e, "Mitral E/e'": mit_ee,
                    "LAEDV": laedv, "LAESV": laesv, "LA Strain": la_strain, "LACi": laci,
                    "TAPSE": tapse, "RV Sm": rv_sm, "TAPSE/Sm": tapse_sm, "sPAP": spap, "RVOT VTI": rvot_vti, "RVOT accT": rvot_acct
                }
                
                save_data_row(SHEET_ID, data_row, worksheet_index=0)
                st.success(f"✅ {dosya_no} kaydedildi!")
