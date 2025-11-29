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

# --- YARDIMCI DÖNÜŞTÜRÜCÜLER ---
def safe_float(val):
    try: return float(val)
    except: return 0.0

def safe_int(val):
    try: return int(float(val))
    except: return 0

def is_checked(val):
    return str(val).lower() == "true"

# --- VERİ ÇEKME ---
def load_data(sheet_id, worksheet_index=0):
    try:
        client = connect_to_gsheets()
        sheet = client.open_by_key(sheet_id).get_worksheet(worksheet_index)
        data = sheet.get_all_values()
        
        if not data or len(data) < 1:
            return pd.DataFrame()
            
        headers = data[0]
        # Header Düzeltme
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

# --- KAYIT VE GÜNCELLEME ---
def save_data_row(sheet_id, new_data, unique_col="Dosya Numarası", worksheet_index=0):
    client = connect_to_gsheets()
    sheet = client.open_by_key(sheet_id).get_worksheet(worksheet_index)
    all_values = sheet.get_all_values()
    
    # Temizle
    clean_d = {k: str(v) if v is not None else "" for k, v in new_data.items()}

    if not all_values:
        sheet.append_row(list(clean_d.keys()))
        sheet.append_row(list(clean_d.values()))
        return

    headers = all_values[0]
    # Eksik sütun varsa ekle
    for k in clean_d.keys():
        if k not in headers: headers.append(k)

    row_to_save = []
    # Eski veriyi bul
    df = pd.DataFrame(all_values[1:], columns=all_values[0]).astype(str)
    row_index = None
    existing = {}
    
    if unique_col in df.columns:
        matches = df.index[df[unique_col] == str(clean_d[unique_col])].tolist()
        if matches:
            row_index = matches[0] + 2
            existing = df.iloc[matches[0]].to_dict()

    for h in headers:
        new_v = str(clean_d.get(h, ""))
        old_v = str(existing.get(h, ""))
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

st.markdown("""<style>.ecg-c{background:#000;height:70px;width:100%;overflow:hidden;position:relative;border-radius:8px;border:1px solid #333;margin-bottom:10px}.ecg-l{background-image:url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="300" height="70" viewBox="0 0 300 70"><path d="M0 35 L20 35 L25 30 L30 35 L40 35 L42 40 L45 5 L48 65 L52 35 L60 35 L65 25 L75 25 L80 35 L300 35" stroke="%2300ff00" stroke-width="2" fill="none"/></svg>');width:200%;height:100%;position:absolute;animation:slide 3s linear infinite;background-repeat:repeat-x}@keyframes slide{from{transform:translateX(0)}to{transform:translateX(-300px)}}</style><div class="ecg-c"><div class="ecg-l"></div></div>""", unsafe_allow_html=True)

st.title("H-TYPE HİPERTANSİYON ÇALIŞMASI")

df = load_data(SHEET_ID, 0)

with st.expander("📋 KAYITLI HASTA LİSTESİ & SİLME", expanded=False):
    c1, c2 = st.columns([3, 1])
    with c1:
        if st.button("🔄 Yenile"): st.rerun()
        if not df.empty:
            cols = ["Dosya Numarası", "Adı Soyadı", "Tarih", "Hekim"]
            final = [c for c in cols if c in df.columns]
            st.dataframe(df[final] if final else df, use_container_width=True)
        else: st.info("Kayıt yok.")
    with c2:
        if not df.empty:
            del_id = st.selectbox("Silinecek No", df["Dosya Numarası"].unique())
            if st.button("🗑️ SİL"):
                if delete_patient(SHEET_ID, del_id):
                    st.success("Silindi!"); time.sleep(1); st.rerun()

st.divider()
mode = st.radio("İşlem:", ["Yeni Kayıt", "Düzenleme"], horizontal=True)

cur = {}
if mode == "Düzenleme" and not df.empty:
    edit_id = st.selectbox("Hasta Seç (Dosya No):", df["Dosya Numarası"].unique())
    if edit_id:
        cur = df[df["Dosya Numarası"] == edit_id].iloc[0].to_dict()

# --- KISA VERİ ALICILAR ---
def gs(k): return str(cur.get(k, ""))
def gf(k): 
    try: return float(cur.get(k, 0))
    except: return 0.0
def gi(k): 
    try: return int(float(cur.get(k, 0)))
    except: return 0
def gc(k): return str(cur.get(k, "")).lower() == "true"

with st.form("main_form"):
    st.markdown("### 👤 Klinik")
    c1, c2 = st.columns(2)
    with c1:
        dosya_no = st.text_input("Dosya Numarası (Zorunlu)", value=gs("Dosya Numarası"))
        ad_soyad = st.text_input("Adı Soyadı", value=gs("Adı Soyadı"))
        try: d_date = datetime.strptime(gs("Tarih"), "%Y-%m-%d")
        except: d_date = datetime.now()
        basvuru = st.date_input("Başvuru Tarihi", value=d_date)
        hekim = st.text_input("Veriyi Giren Hekim", value=gs("Hekim"))
        iletisim = st.text_input("İletişim", value=gs("İletişim"))
    
    with c2:
        cy, cc = st.columns(2)
        yas = cy.number_input("Yaş", step=1, value=gi("Yaş"))
        sex_l = ["Erkek", "Kadın"]
        try: s_ix = sex_l.index(gs("Cinsiyet"))
        except: s_ix = 0
        cinsiyet = cc.radio("Cinsiyet", sex_l, index=s_ix, horizontal=True)
        
        cb1, cb2, cb3 = st.columns(3)
        boy = cb1.number_input("Boy (cm)", value=gf("Boy"))
        kilo = cb2.number_input("Kilo (kg)", value=gf("Kilo"))
        bmi = kilo/((boy/100)**2) if boy>0 else 0
        bsa = (boy * kilo / 3600) ** 0.5 if (boy>0 and kilo>0) else 0
        cb3.metric("BMI", f"{bmi:.1f}")

        ct1, ct2 = st.columns(2)
        ta_sis = ct1.number_input("TA Sistol", value=gi("TA Sistol"))
        ta_dia = ct2.number_input("TA Diyastol", value=gi("TA Diyastol"))

    st.markdown("---")
    ekg_l = ["NSR", "LBBB", "RBBB", "VPB", "SVT", "Diğer"]
    try: e_ix = ekg_l.index(gs("EKG"))
    except: e_ix = 0
    ekg = st.selectbox("EKG", ekg_l, index=e_ix)
    
    ci1, ci2 = st.columns(2)
    ilaclar = ci1.text_area("Kullandığı İlaçlar", value=gs("İlaçlar"))
    baslanan = ci2.text_area("Başlanan İlaçlar", value=gs("Başlanan"))

    st.markdown("##### Ek Hastalıklar")
    ck1, ck2, ck3, ck4, ck5 = st.columns(5)
    dm = ck1.checkbox("DM", value=gc("DM"))
    kah = ck2.checkbox("KAH", value=gc("KAH"))
    hpl = ck3.checkbox("HPL", value=gc("HPL"))
    inme = ck4.checkbox("İnme", value=gc("İnme"))
    sigara = ck5.checkbox("Sigara", value=gc("Sigara"))
    diger_hst = st.text_input("Diğer", value=gs("Diğer")) # İsim düzeltildi

    st.markdown("### 🩸 Laboratuvar")
    l1, l2, l3, l4 = st.columns(4)
    hgb = l1.number_input("Hgb", value=gf("Hgb"))
    hct = l1.number_input("Hct", value=gf("Hct"))
    wbc = l1.number_input("WBC", value=gf("WBC"))
    plt = l1.number_input("PLT", value=gf("PLT"))
    neu = l1.number_input("Nötrofil", value=gf("Neu"))
    lym = l1.number_input("Lenfosit", value=gf("Lym"))
    mpv = l1.number_input("MPV", value=gf("MPV"))
    rdw = l1.number_input("RDW", value=gf("RDW"))

    glukoz = l2.number_input("Glukoz", value=gf("Glukoz"))
    ure = l2.number_input("Üre", value=gf("Üre"))
    krea = l2.number_input("Kreatinin", value=gf("Kreatinin"))
    uric = l2.number_input("Ürik Asit", value=gf("Ürik Asit"))
    na = l2.number_input("Na", value=gf("Na"))
    k_val = l2.number_input("K", value=gf("K"))
    alt = l2.number_input("ALT", value=gf("ALT"))
    ast = l2.number_input("AST", value=gf("AST"))
    prot = l2.number_input("Tot Prot", value=gf("Tot. Prot"))
    alb = l2.number_input("Albümin", value=gf("Albümin"))

    chol = l3.number_input("Chol", value=gf("Chol"))
    ldl = l3.number_input("LDL", value=gf("LDL"))
    hdl = l3.number_input("HDL", value=gf("HDL"))
    trig = l3.number_input("Trig", value=gf("Trig"))

    homo = l4.number_input("Homosistein", value=gf("Homosistein"))
    lpa = l4.number_input("Lp(a)", value=gf("Lp(a)"))
    folik = l4.number_input("Folik Asit", value=gf("Folik Asit"))
    b12 = l4.number_input("B12", value=gf("B12"))

    st.markdown("### 🫀 Eko")
    e1, e2, e3, e4 = st.columns(4)
    with e1:
        st.caption("Yapısal")
        lvedd = st.number_input("LVEDD", value=gf("LVEDD"))
        lvesd = st.number_input("LVESD", value=gf("LVESD"))
        ivs = st.number_input("IVS", value=gf("IVS"))
        pw = st.number_input("PW", value=gf("PW"))
        lvedv = st.number_input("LVEDV", value=gf("LVEDV"))
        lvesv = st.number_input("LVESV", value=gf("LVESV"))
        ao = st.number_input("Ao Asc", value=gf("Ao Asc"))
        
        lvm = 0.0; lvmi = 0.0; rwt = 0.0
        if lvedd>0 and ivs>0 and pw>0:
            d_cm = lvedd/10; i_cm = ivs/10; p_cm = pw/10
            lvm = 0.8*(1.04*((d_cm+i_cm+p_cm)**3 - d_cm**3))+0.6
            if bsa>0: lvmi = lvm/bsa
        if lvedd>0 and pw>0: rwt = (2*pw)/lvedd
        st.caption(f"🔵 Mass:{lvm:.0f} | LVMi:{lvmi:.0f} | RWT:{rwt:.2f}")

    with e2:
        st.caption("Sistolik")
        lvef = st.number_input("LVEF", value=gf("LVEF"))
        sv = st.number_input("SV", value=gf("SV"))
        lvot = st.number_input("LVOT VTI", value=gf("LVOT VTI"))
        gls = st.number_input("GLS", value=gf("GLS"))
        gcs = st.number_input("GCS", value=gf("GCS"))
        sdls = st.number_input("SD-LS", value=gf("SD-LS"))

    with e3:
        st.caption("Diyastolik")
        mite = st.number_input("Mitral E", value=gf("Mitral E"))
        mita = st.number_input("Mitral A", value=gf("Mitral A"))
        septe = st.number_input("Septal e'", value=gf("Septal e'"))
        late = st.number_input("Lateral e'", value=gf("Lateral e'"))
        laedv = st.number_input("LAEDV", value=gf("LAEDV"))
        laesv = st.number_input("LAESV", value=gf("LAESV"))
        lastr = st.number_input("LA Strain", value=gf("LA Strain"))
        
        ea = mite/mita if mita>0 else 0
        ee = mite/septe if septe>0 else 0
        laci = laedv/lvedv if lvedv>0 else 0
        st.caption(f"🔵 E/A:{ea:.1f} | E/e':{ee:.1f} | LACi:{laci:.2f}")

    with e4:
        st.caption("Sağ Kalp")
        tapse = st.number_input("TAPSE", value=gf("TAPSE"))
        rvsm = st.number_input("RV Sm", value=gf("RV Sm"))
        spap = st.number_input("sPAP", value=gf("sPAP"))
        rvot = st.number_input("RVOT VTI", value=gf("RVOT VTI"))
        rvota = st.number_input("RVOT accT", value=gf("RVOT accT"))
        tsm = tapse/rvsm if rvsm>0 else 0
        st.caption(f"🔵 TAPSE/Sm:{tsm:.2f}")

    st.write("")
    if st.form_submit_button("💾 KAYDET / GÜNCELLE", type="primary"):
        if not dosya_no or not hekim:
            st.error("Dosya No ve Hekim zorunlu!")
        else:
            final_data = {
                "Dosya Numarası": dosya_no, "Adı Soyadı": ad_soyad, "Tarih": str(basvuru), "Hekim": hekim,
                "Yaş": yas, "Cinsiyet": cinsiyet, "Boy": boy, "Kilo": kilo, "BMI": bmi, "BSA": bsa,
                "TA Sistol": ta_sis, "TA Diyastol": ta_dia, "EKG": ekg, 
                "İlaçlar": ilaclar, "Başlanan": baslanan,
                "DM": dm, "KAH": kah, "HPL": hpl, "İnme": inme, "Sigara": sigara, "Diğer": diger_hst,
                "Hgb": hgb, "Hct": hct, "WBC": wbc, "PLT": plt, "Neu": neu, "Lym": lym, "MPV": mpv, "RDW": rdw,
                "Glukoz": glukoz, "Üre": ure, "Kreatinin": krea, "Ürik Asit": uric, "Na": na, "K": k_val, 
                "ALT": alt, "AST": ast, "Tot. Prot": prot, "Albümin": alb,
                "Chol": chol, "LDL": ldl, "HDL": hdl, "Trig": trig, 
                "Lp(a)": lpa, "Homosistein": homo, "Folik Asit": folik, "B12": b12,
                "LVEDD": lvedd, "LVESD": lvesd, "IVS": ivs, "PW": pw, "LVEDV": lvedv, "LVESV": lvesv, 
                "LV Mass": lvm, "LVMi": lvmi, "RWT": rwt, "Ao Asc": ao,
                "LVEF": lvef, "SV": sv, "LVOT VTI": lvot, "GLS": gls, "GCS": gcs, "SD-LS": sdls,
                "Mitral E": mite, "Mitral A": mita, "Mitral E/A": ea, "Septal e'": septe, "Lateral e'": late, "Mitral E/e'": ee,
                "LAEDV": laedv, "LAESV": laesv, "LA Strain": lastr, "LACi": laci,
                "TAPSE": tapse, "RV Sm": rvsm, "TAPSE/Sm": tsm, "sPAP": spap, "RVOT VTI": rvot, "RVOT accT": rvota
            }
            save_data_row(SHEET_ID, final_data, worksheet_index=0)
            st.success(f"✅ {dosya_no} kaydedildi!")
            time.sleep(1)
            st.rerun()
