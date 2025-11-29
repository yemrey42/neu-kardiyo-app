import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import time

# --- AYARLAR ---
# ID'niz koda gömüldü
SHEET_ID = "1_Jd27n2lvYRl-oKmMOVySd5rGvXLrflDCQJeD_Yz6Y4"
CASE_SHEET_ID = SHEET_ID 

st.set_page_config(page_title="NEÜ-KARDİYO", page_icon="❤️", layout="wide")

# --- BAĞLANTILAR ---
def connect_to_gsheets():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
    client = gspread.authorize(creds)
    return client

# --- VERİ ÇEKME (HATA KORUMALI) ---
def load_data(sheet_id, worksheet_index=0):
    try:
        client = connect_to_gsheets()
        sheet = client.open_by_key(sheet_id).get_worksheet(worksheet_index)
        data = sheet.get_all_values()
        
        # Eğer veri yoksa veya sadece başlık yoksa boş dön
        if not data or len(data) < 1:
            return pd.DataFrame()
            
        headers = data[0]
        # Eğer başlık satırı bozuksa (Dosya Numarası sütunu yoksa) boş dön ki yeniden oluştursun
        if "Dosya Numarası" not in headers:
            return pd.DataFrame()

        rows = data[1:]
        df = pd.DataFrame(rows, columns=headers)
        return df.astype(str) # Hepsini yazı yap (Çökme önleyici)
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
    
    # Veri Temizliği
    clean_data = {k: str(v) if v is not None else "" for k, v in data_dict.items()}
    
    all_values = sheet.get_all_values()
    
    # EĞER DOSYA BOŞSA VEYA BAŞLIKLAR BOZUKSA -> BAŞTAN YAZ
    if not all_values or "Dosya Numarası" not in all_values[0]:
        sheet.clear() # Temizle
        sheet.append_row(list(clean_data.keys())) # Başlıkları yaz
        sheet.append_row(list(clean_data.values())) # İlk veriyi yaz
        return

    headers = all_values[0]
    
    # Eksik sütun kontrolü
    missing_cols = [k for k in clean_data.keys() if k not in headers]
    if missing_cols:
        headers.extend(missing_cols)
        # Sütun ekleme işi karmaşık olduğu için burada basitçe devam ediyoruz,
        # Google Sheets sona eklenen veriyi kabul eder.

    # Veriyi başlık sırasına göre diz
    row_to_save = []
    for h in headers:
        row_to_save.append(clean_data.get(h, ""))
    
    # Yeni eklenen parametreler varsa sona ekle
    for k in clean_data.keys():
        if k not in headers:
            row_to_save.append(clean_data[k])

    # GÜNCELLEME KONTROLÜ
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
    st.title("H-TYPE HİPERTANSİYON ÇALIŞMASI")
    
    tab_list, tab_form = st.tabs(["📋 LİSTE / SİLME", "✍️ VERİ GİRİŞ / DÜZENLE"])

    # LİSTE VE SİLME EKRANI
    with tab_list:
        col_L1, col_L2 = st.columns([3, 1])
        with col_L1:
            if st.button("🔄 Listeyi Yenile"): st.rerun()
            df = load_data(SHEET_ID, 0)
            if not df.empty:
                st.metric("Toplam Kayıt", len(df))
                st.dataframe(df, use_container_width=True)
            else:
                st.info("Henüz kayıt yok veya Google Sheet boş.")
        
        with col_L2:
            st.warning("⚠️ HASTA SİLME")
            if not df.empty:
                del_list = df["Dosya Numarası"].astype(str).tolist()
                del_select = st.selectbox("Silinecek Dosya", del_list)
                if st.button("🗑️ SİL"):
                    if delete_patient(SHEET_ID, del_select):
                        st.success("Silindi!")
                        time.sleep(1)
                        st.rerun()
                    else: st.error("Hata!")

    # VERİ GİRİŞ EKRANI
    with tab_form:
        st.info("💡 **DÜZENLEME:** Var olan bir 'Dosya Numarası'nı girip kaydederseniz, eski kayıt güncellenir.")
        
        with st.form("main"):
            # KLİNİK
            st.markdown("### 👤 Klinik Bilgiler")
            c1, c2 = st.columns(2)
            with c1:
                dosya_no = st.text_input("Dosya Numarası (Zorunlu)")
                ad_soyad = st.text_input("Adı Soyadı")
                basvuru = st.date_input("Başvuru Tarihi")
                hekim = st.text_input("Veriyi Giren Hekim (Zorunlu)")
                iletisim = st.text_input("İletişim")
            with c2:
                col_y, col_c = st.columns(2)
                yas = col_y.number_input("Yaş", step=1)
                cinsiyet = col_c.radio("Cinsiyet", ["Erkek", "Kadın"], horizontal=True)
                cb1, cb2, cb3 = st.columns(3)
                boy = cb1.number_input("Boy (cm)")
                kilo = cb2.number_input("Kilo (kg)")
                bmi = kilo/((boy/100)**2) if boy>0 else 0
                bsa = (boy * kilo / 3600) ** 0.5 if (boy>0 and kilo>0) else 0
                cb3.metric("BMI", f"{bmi:.1f}")
                
                ct1, ct2 = st.columns(2)
                ta_sis = ct1.number_input("TA Sistol", step=1)
                ta_dia = ct2.number_input("TA Diyastol", step=1)
            
            st.divider()
            ekg = st.selectbox("EKG", ["NSR", "LBBB", "RBBB", "VPB", "SVT", "Diğer"])
            ilaclar = st.text_area("Kullandığı İlaçlar", height=60)
            baslanan = st.text_area("Başlanan İlaçlar", height=60)
            
            cc1, cc2, cc3, cc4, cc5 = st.columns(5)
            dm = cc1.checkbox("DM"); kah = cc2.checkbox("KAH"); hpl = cc3.checkbox("HPL"); inme = cc4.checkbox("İnme"); sigara = cc5.checkbox("Sigara")
            diger_hst = st.text_input("Diğer Hastalık")

            # LAB
            st.markdown("### 🩸 Laboratuvar")
            l1, l2, l3, l4 = st.columns(4)
            hgb = l1.number_input("Hgb"); hct = l1.number_input("Hct"); wbc = l1.number_input("WBC"); plt = l1.number_input("PLT")
            neu = l1.number_input("Nötrofil"); lym = l1.number_input("Lenfosit"); mpv = l1.number_input("MPV"); rdw = l1.number_input("RDW")
            
            glukoz = l2.number_input("Glukoz"); ure = l2.number_input("Üre"); krea = l2.number_input("Kreatinin"); uric = l2.number_input("Ürik Asit")
            na = l2.number_input("Na"); k_val = l2.number_input("K"); alt = l2.number_input("ALT"); ast = l2.number_input("AST")
            tot_prot = l2.number_input("Tot Prot"); albumin = l2.number_input("Albümin")
            
            chol = l3.number_input("Chol"); ldl = l3.number_input("LDL"); hdl = l3.number_input("HDL"); trig = l3.number_input("Trig")
            
            homosis = l4.number_input("Homosistein"); lpa = l4.number_input("Lp(a)"); folik = l4.number_input("Folik Asit"); b12 = l4.number_input("B12")

            # EKO
            st.markdown("### 🫀 Eko")
            e1, e2, e3, e4 = st.columns(4)
            with e1:
                st.caption("Yapısal")
                lvedd = st.number_input("LVEDD"); lvesd = st.number_input("LVESD"); ivs = st.number_input("IVS"); pw = st.number_input("PW")
                lvedv = st.number_input("LVEDV"); lvesv = st.number_input("LVESV"); ao_asc = st.number_input("Ao Asc")
                
                lv_mass = 0.0; lvmi = 0.0; rwt = 0.0
                if lvedd>0 and ivs>0 and pw>0:
                    lvedd_c=lvedd/10; ivs_c=ivs/10; pw_c=pw/10
                    lv_mass = 0.8*(1.04*((lvedd_c+ivs_c+pw_c)**3 - lvedd_c**3))+0.6
                    if bsa>0: lvmi = lv_mass/bsa
                if lvedd>0 and pw>0: rwt = (2*pw)/lvedd
                st.markdown(f"🔵 **Mass:** {lv_mass:.0f} | **LVMi:** {lvmi:.0f} | **RWT:** {rwt:.2f}")

            with e2:
                st.caption("Sistolik")
                lvef = st.number_input("LVEF"); sv = st.number_input("SV"); lvot_vti = st.number_input("LVOT VTI")
                gls = st.number_input("GLS"); gcs = st.number_input("GCS"); sd_ls = st.number_input("SD-LS")

            with e3:
                st.caption("Diyastolik")
                mit_e = st.number_input("Mitral E"); mit_a = st.number_input("Mitral A")
                sept_e = st.number_input("Septal e'"); lat_e = st.number_input("Lateral e'")
                laedv = st.number_input("LAEDV"); laesv = st.number_input("LAESV"); la_strain = st.number_input("LA Strain")
                mit_ea = mit_e/mit_a if mit_a>0 else 0
                mit_ee = mit_e/sept_e if sept_e>0 else 0
                laci = laedv/lvedv if lvedv>0 else 0
                st.markdown(f"🔵 **E/A:** {mit_ea:.1f} | **E/e':** {mit_ee:.1f} | **LACi:** {laci:.2f}")

            with e4:
                st.caption("Sağ Kalp")
                tapse = st.number_input("TAPSE"); rv_sm = st.number_input("RV Sm"); spap = st.number_input("sPAP")
                rvot_vti = st.number_input("RVOT VTI"); rvot_acct = st.number_input("RVOT accT")
                tapse_sm = tapse/rv_sm if rv_sm>0 else 0
                st.markdown(f"🔵 **TAPSE/Sm:** {tapse_sm:.2f}")

            st.write("")
            if st.form_submit_button("💾 KAYDET / GÜNCELLE", type="primary"):
                if not dosya_no or not hekim:
                    st.error("Dosya No ve Hekim Zorunlu!")
                else:
                    data = {
                        "Dosya Numarası": dosya_no, "Adı Soyadı": ad_soyad, "Tarih": str(basvuru), "Hekim": hekim,
                        "Yaş": yas, "Cinsiyet": cinsiyet, "Boy": boy, "Kilo": kilo, "BMI": bmi, "BSA": bsa,
                        "TA Sistol": ta_sis, "TA Diyastol": ta_dia, "EKG": ekg, 
                        "İlaçlar": ilaclar, "Başlanan": baslanan,
                        "DM": dm, "KAH": kah, "HPL": hpl, "İnme": inme, "Sigara": sigara, "Diğer": diger_hst,
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
                    save_data_row(SHEET_ID, data, worksheet_index=0)
                    st.success(f"✅ {dosya_no} başarıyla kaydedildi!")
                    time.sleep(1)
                    st.rerun()
