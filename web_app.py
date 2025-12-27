import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import time
import random
from io import BytesIO

# ===================== AYARLAR =====================
SHEET_ID = "1_Jd27n2lvYRl-oKmMOVySd5rGvXLrflDCQJeD_Yz6Y4"
CASE_SHEET_ID = SHEET_ID
LETTER_SHEET_ID = SHEET_ID

DATA_WS_INDEX = 0       # 1. sayfa: Veri Girişi
CASE_WS_INDEX = 1       # 2. sayfa: Case Report Takip
LETTER_WS_INDEX = 2     # 3. sayfa: Editöre Mektup

st.set_page_config(page_title="NEÜ-KARDİYO", page_icon="❤️", layout="wide")

# ===================== GOOGLE SHEETS BAĞLANTI =====================
@st.cache_resource
def connect_to_gsheets():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(
        st.secrets["gcp_service_account"], scope
    )
    return gspread.authorize(creds)

# ===================== YARDIMCI =====================
def safe_float(val):
    try:
        return float(val)
    except:
        return 0.0

def safe_int(val):
    try:
        return int(float(val))
    except:
        return 0

def colnum_to_letter(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s

def to_excel_bytes(df: pd.DataFrame, sheet_name="Sheet1") -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    return output.getvalue()

def mask_text(x: str) -> str:
    """Dergi/Makale adını maskeler: her kelimenin ilk harfi + ***"""
    if not x:
        return ""
    parts = str(x).split()
    return " ".join([(w[0] + "***") if len(w) > 0 else "" for w in parts])

# ===================== VERİ ÇEKME =====================
def load_data(sheet_id, worksheet_index=0, required_col=None):
    try:
        client = connect_to_gsheets()
        ws = client.open_by_key(sheet_id).get_worksheet(worksheet_index)
        data = ws.get_all_values()

        if not data or len(data) < 1:
            return pd.DataFrame()

        headers = [str(h).strip() for h in data[0]]

        if required_col and required_col not in headers:
            return pd.DataFrame()

        rows = data[1:]

        # Duplicate header fix
        seen = {}
        unique_headers = []
        for h in headers:
            if h in seen:
                seen[h] += 1
                unique_headers.append(f"{h}_{seen[h]}")
            else:
                seen[h] = 0
                unique_headers.append(h)

        num_cols = len(unique_headers)
        fixed_rows = []
        for row in rows:
            if len(row) < num_cols:
                row += [""] * (num_cols - len(row))
            fixed_rows.append(row)

        df = pd.DataFrame(fixed_rows, columns=unique_headers)
        return df.astype(str)

    except:
        return pd.DataFrame()

# ===================== SİLME =====================
def delete_row_by_value(sheet_id, worksheet_index, col_name, value):
    client = connect_to_gsheets()
    ws = client.open_by_key(sheet_id).get_worksheet(worksheet_index)
    try:
        cell = ws.find(str(value))
        ws.delete_rows(cell.row)
        return True
    except:
        return False

# ===================== KAYIT / GÜNCELLEME (UPSERT) =====================
def save_data_row(sheet_id, data_dict, unique_col, worksheet_index=0):
    client = connect_to_gsheets()
    ws = client.open_by_key(sheet_id).get_worksheet(worksheet_index)

    clean_data = {str(k).strip(): ("" if v is None else str(v)) for k, v in data_dict.items()}
    all_values = ws.get_all_values()

    if not all_values:
        ws.append_row(list(clean_data.keys()))
        ws.append_row(list(clean_data.values()))
        st.toast("✅ İlk kayıt oluşturuldu.", icon="💾")
        return

    headers = [str(h).strip() for h in all_values[0]]

    if unique_col not in headers:
        headers.append(unique_col)

    missing_cols = [k for k in clean_data.keys() if k not in headers]
    if missing_cols:
        headers.extend(missing_cols)
        ws.update("1:1", [headers])

    row_to_save = [clean_data.get(h, "") for h in headers]

    uid = clean_data.get(unique_col, "").strip()
    if not uid:
        raise ValueError(f"{unique_col} boş olamaz!")

    uid_col_idx = headers.index(unique_col) + 1
    col_vals = ws.col_values(uid_col_idx)

    row_index_to_update = None
    for i, v in enumerate(col_vals[1:], start=2):
        if str(v).strip() == uid:
            row_index_to_update = i
            break

    end_col = colnum_to_letter(len(headers))

    if row_index_to_update:
        ws.update(f"A{row_index_to_update}:{end_col}{row_index_to_update}", [row_to_save])
        st.toast(f"✅ Güncellendi: {uid}", icon="🔄")
    else:
        ws.append_row(row_to_save)
        st.toast(f"✅ Kaydedildi: {uid}", icon="💾")

# ===================== AUTH (VERİ GİRİŞİ ŞİFRE) =====================
def require_password_gate():
    if "auth_ok" not in st.session_state:
        st.session_state.auth_ok = False

    app_password = st.secrets.get("app_password", None)
    if not app_password:
        st.error('⚠️ Şifre tanımlı değil. Secrets içine:  app_password = "...."  ekle.')
        st.stop()

    if st.session_state.auth_ok:
        return

    st.subheader("🔐 Veri Girişi (Şifreli)")
    pw = st.text_input("Şifre", type="password")
    c1, c2 = st.columns([1, 2])
    with c1:
        if st.button("Giriş", type="primary"):
            if pw == app_password:
                st.session_state.auth_ok = True
                st.success("✅ Giriş başarılı")
                time.sleep(0.4)
                st.rerun()
            else:
                st.error("❌ Şifre yanlış")
    with c2:
        st.caption("Not: Bu şifre sadece Veri Girişi ekranı için geçerli.")
    st.stop()

def confirm_delete_with_password(context_key: str) -> bool:
    """
    Silme işlemlerini şifreler.
    context_key: 'case' / 'letter' vb. session_state key için.
    """
    app_password = st.secrets.get("app_password", None)
    if not app_password:
        st.error('⚠️ Secrets içinde app_password yok.')
        return False

    key_ok = f"del_ok_{context_key}"
    if key_ok not in st.session_state:
        st.session_state[key_ok] = False

    if st.session_state[key_ok]:
        st.success("✅ Silme yetkisi açık")
        if st.button("🔒 Silme Kilidini Kapat", key=f"lock_{context_key}"):
            st.session_state[key_ok] = False
            st.rerun()
        return True

    with st.expander("🔐 Silme için şifre gir", expanded=True):
        pw = st.text_input("Silme Şifresi", type="password", key=f"pw_{context_key}")
        if st.button("Onayla", key=f"ok_{context_key}", type="primary"):
            if pw == app_password:
                st.session_state[key_ok] = True
                st.success("✅ Doğrulandı")
                time.sleep(0.3)
                st.rerun()
            else:
                st.error("❌ Şifre yanlış")

    return False

# ===================== HEADER / EKG ANİMASYONU =====================
st.markdown(
    """
<style>
.ecg-container {
    background: #000; height: 90px; width: 100%; overflow: hidden; position: relative;
    border-radius: 10px; border: 2px solid #444; margin-bottom: 20px; display: flex; align-items: center;
    box-shadow: 0 0 10px rgba(0, 255, 0, 0.2);
}
.ecg-line {
    position: absolute; top: 0; left: 0; width: 100%; height: 100%;
    background-image: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="300" height="90" viewBox="0 0 300 90"><path d="M0 50 L20 50 L25 45 L30 50 L40 50 L42 55 L45 10 L48 85 L52 50 L60 50 L65 40 L75 40 L80 50 L300 50" stroke="%2300ff00" stroke-width="2" fill="none"/></svg>');
    background-repeat: repeat-x; animation: scroll-bg 3s linear infinite; z-index: 1; opacity: 0.6;
}
.ecg-text-track { display: flex; position: absolute; top: 30px; left: 0; white-space: nowrap;
    animation: scroll-text 12s linear infinite; z-index: 2; }
.ecg-name {
    display: inline-block; width: 300px;
    font-family: 'Courier New', monospace; font-weight: 900; font-size: 20px; text-align: center;
    text-shadow: 2px 2px 0px #000;
    animation: bounce 1s infinite alternate, color-shift 5s infinite linear;
}
.ecg-name:nth-child(1) { color: #FFFF00; animation-delay: 0s, 0s; }
.ecg-name:nth-child(2) { color: #00FFFF; animation-delay: 0.2s, 1s; }
.ecg-name:nth-child(3) { color: #FF00FF; animation-delay: 0.4s, 2s; }
.ecg-name:nth-child(4) { color: #FFA500; animation-delay: 0.6s, 3s; }
.ecg-name:nth-child(5) { color: #FFFF00; animation-delay: 0s, 0s; }
.ecg-name:nth-child(6) { color: #00FFFF; animation-delay: 0.2s, 1s; }
.ecg-name:nth-child(7) { color: #FF00FF; animation-delay: 0.4s, 2s; }
.ecg-name:nth-child(8) { color: #FFA500; animation-delay: 0.6s, 3s; }
@keyframes scroll-bg { 0% { background-position: 0 0; } 100% { background-position: -300px 0; } }
@keyframes scroll-text { 0% { transform: translateX(0); } 100% { transform: translateX(-1200px); } }
@keyframes bounce { 0% { transform: translateY(0); } 100% { transform: translateY(-8px); } }
@keyframes color-shift { 0% { filter: hue-rotate(0deg); } 100% { filter: hue-rotate(360deg); } }
</style>
<div class="ecg-container">
    <div class="ecg-line"></div>
    <div class="ecg-text-track">
        <div class="ecg-name">FATİH</div><div class="ecg-name">ZEYNEP</div><div class="ecg-name">NURAY</div><div class="ecg-name">LEYLA</div>
        <div class="ecg-name">FATİH</div><div class="ecg-name">ZEYNEP</div><div class="ecg-name">NURAY</div><div class="ecg-name">LEYLA</div>
    </div>
</div>
""",
    unsafe_allow_html=True,
)

st.title("H-TYPE HİPERTANSİYON ÇALIŞMASI")

# ===================== SIDEBAR =====================
with st.sidebar:
    st.title("❤️ NEÜ-KARDİYO")

    menu = st.radio(
        "Menü",
        ["🏥 Veri Girişi (H-Type HT) [Şifreli]", "📝 Case Report Takip", "✉️ Editöre Mektup"],
    )

    st.divider()

    quotes = [
        "Halk içinde muteber bir nesne yok devlet gibi,\nOlmaya devlet cihanda bir nefes sıhhat gibi.\n(Kanuni Sultan Süleyman)",
        "Kalp, aklın bilmediği sebeplere sahiptir.\n(Blaise Pascal)",
        "İlim ilim bilmektir, ilim kendin bilmektir.\n(Yunus Emre)",
        "Zahmetsiz rahmet olmaz.",
        "Sabır acidir , meyvesi tatlıdır.",
        "Ne doğrarsan aşına, o gelir kaşığa.",
        "Batı gibi hayvanca kalkınacağımıza, insanca geri kalalım.\n(Barış Manço)",
    ]
    st.info(f"💡 **Günün Sözü:**\n\n_{random.choice(quotes)}_")

# =========================================================
# ===================== EKRAN 2: CASE REPORT =====================
# =========================================================
if menu == "📝 Case Report Takip":
    st.header("📝 Case Report Takip")

    left, right = st.columns([1, 2])

    with left:
        with st.form("case_form"):
            n_dosya = st.text_input("Dosya No")
            n_ad = st.text_input("Hasta")
            n_dr = st.text_input("Sorumlu Doktor")
            n_not = st.text_area("Not")

            if st.form_submit_button("Kaydet", type="primary"):
                try:
                    now = datetime.now()
                    payload = {
                        "Tarih": str(now.date()),
                        "TarihSaat": now.isoformat(timespec="seconds"),
                        "Dosya No": n_dosya,
                        "Hasta": n_ad,
                        "Doktor": n_dr,
                        "Not": n_not,
                    }
                    save_data_row(CASE_SHEET_ID, payload, unique_col="TarihSaat", worksheet_index=CASE_WS_INDEX)
                    st.success("✅ Kaydedildi")
                    time.sleep(0.6)
                    st.rerun()
                except Exception as e:
                    st.error(f"Hata: {e}")

    with right:
        dfn = load_data(CASE_SHEET_ID, CASE_WS_INDEX, required_col="TarihSaat")
        if not dfn.empty:
            q = st.text_input("🔎 Arama (dosya no / hasta / doktor)", "")
            dfn_show = dfn.copy()

            # NOT listelenmesin
            if "Not" in dfn_show.columns:
                dfn_show = dfn_show.drop(columns=["Not"])

            if q.strip():
                mask = dfn_show.apply(
                    lambda row: row.astype(str).str.contains(q, case=False, na=False).any(),
                    axis=1,
                )
                dfn_show = dfn_show[mask].copy()

            st.dataframe(dfn_show, use_container_width=True)

            st.divider()
            st.markdown("### 🗑️ Silme (Şifreli)")

            # Şifre doğrulama olmadan silme açılmasın
            if confirm_delete_with_password("case"):
                del_ts = st.selectbox("Silinecek kayıt (TarihSaat)", dfn["TarihSaat"].unique(), key="case_del_ts")
                if st.button("🗑️ Sil", key="case_del_btn", type="secondary"):
                    if delete_row_by_value(SHEET_ID, CASE_WS_INDEX, "TarihSaat", del_ts):
                        st.success("Silindi")
                        time.sleep(0.4)
                        st.rerun()
                    else:
                        st.error("Hata!")
        else:
            st.info("Henüz case report kaydı yok veya 2. sheet yok/başlık uyumsuz.")

# =========================================================
# ===================== EKRAN 3: EDİTÖRE MEKTUP =====================
# =========================================================
elif menu == "✉️ Editöre Mektup":
    st.header("✉️ Editöre Mektup Takip")

    left, right = st.columns([1, 2])

    with left:
        with st.form("letter_form"):
            dergi = st.text_input("Dergi Adı")
            makale = st.text_input("Makale İsmi")
            yazarlar = st.text_area("Yazarlar")

            if st.form_submit_button("Kaydet", type="primary"):
                try:
                    now = datetime.now()
                    payload = {
                        "Tarih": str(now.date()),
                        "TarihSaat": now.isoformat(timespec="seconds"),
                        "Dergi Adı": dergi,
                        "Makale İsmi": makale,
                        "Yazarlar": yazarlar,
                    }
                    save_data_row(LETTER_SHEET_ID, payload, unique_col="TarihSaat", worksheet_index=LETTER_WS_INDEX)
                    st.success("✅ Kaydedildi (3. sayfaya yazıldı)")
                    time.sleep(0.6)
                    st.rerun()
                except Exception as e:
                    st.error(f"Hata: {e}")

    with right:
        dfl = load_data(LETTER_SHEET_ID, LETTER_WS_INDEX, required_col="TarihSaat")
        if not dfl.empty:
            dfl_show = dfl.copy()

            # Dergi adı + makale adı maskeli
            if "Dergi Adı" in dfl_show.columns:
                dfl_show["Dergi Adı"] = dfl_show["Dergi Adı"].apply(mask_text)
            if "Makale İsmi" in dfl_show.columns:
                dfl_show["Makale İsmi"] = dfl_show["Makale İsmi"].apply(mask_text)

            q = st.text_input("🔎 Arama (dergi / makale / yazar)", "")
            if q.strip():
                mask = dfl_show.apply(
                    lambda row: row.astype(str).str.contains(q, case=False, na=False).any(),
                    axis=1,
                )
                dfl_show = dfl_show[mask].copy()

            st.dataframe(dfl_show, use_container_width=True)

            st.divider()
            st.markdown("### 🗑️ Silme (Şifreli)")

            if confirm_delete_with_password("letter"):
                del_ts = st.selectbox("Silinecek kayıt (TarihSaat)", dfl["TarihSaat"].unique(), key="letter_del_ts")
                if st.button("🗑️ Sil", key="letter_del_btn", type="secondary"):
                    if delete_row_by_value(SHEET_ID, LETTER_WS_INDEX, "TarihSaat", del_ts):
                        st.success("Silindi")
                        time.sleep(0.4)
                        st.rerun()
                    else:
                        st.error("Hata!")
        else:
            st.info("Henüz editöre mektup kaydı yok veya 3. sheet yok/başlık uyumsuz.")

# =========================================================
# ===================== EKRAN 1: VERİ GİRİŞİ (ŞİFRELİ) =====================
# =========================================================
else:
    require_password_gate()

    df = load_data(SHEET_ID, DATA_WS_INDEX, required_col="Dosya Numarası")

    # Çalışma kriterleri: ana ekrana taşındı
    st.markdown("### 📋 Çalışma Kriterleri")
    k1, k2 = st.columns(2)
    with k1:
        st.success("**✅ DAHİL:** Son 6 ayda yeni tanı esansiyel HT")
    with k2:
        st.error("**⛔ HARİÇ:** Sekonder HT, KY, AKS, Cerrahi, Konjenital, Pulmoner HT, ABY, **AF**")
    st.markdown("---")

    col_left, col_right = st.columns([2, 3])

    with col_left:
        st.markdown("##### ⚙️ İşlem Seçimi")
        mode = st.radio("Mod:", ["Yeni Kayıt", "Düzenleme"], horizontal=True, label_visibility="collapsed")

        current = {}
        if mode == "Düzenleme":
            if not df.empty:
                edit_id = st.selectbox("Düzenlenecek Hasta (Dosya No):", df["Dosya Numarası"].unique())
                if edit_id:
                    current = df[df["Dosya Numarası"] == edit_id].iloc[0].to_dict()
                    st.success(f"Seçildi: {current.get('Adı Soyadı', '')}")
            else:
                st.warning("Düzenlenecek kayıt yok.")

    with col_right:
        with st.expander("📋 KAYITLI HASTA LİSTESİ / ARAMA / SİLME", expanded=True):
            if st.button("🔄 Listeyi Yenile"):
                st.rerun()

            if df.empty:
                st.info("Kayıt yok.")
            else:
                q = st.text_input("🔎 Arama (dosya no / hekim)", "")
                show_df = df.copy()

                # Ad Soyad listede görünmesin
                if "Adı Soyadı" in show_df.columns:
                    show_df = show_df.drop(columns=["Adı Soyadı"])

                # TA sistol/diyastol listeden kalksın (isteğin)
                for c in ["TA Sistol", "TA Diyastol"]:
                    if c in show_df.columns:
                        show_df = show_df.drop(columns=[c])

                if q.strip():
                    mask = show_df.apply(
                        lambda row: row.astype(str).str.contains(q, case=False, na=False).any(),
                        axis=1,
                    )
                    show_df = show_df[mask].copy()

                cols_show = ["Dosya Numarası", "Tarih", "Hekim"]
                final_cols = [c for c in cols_show if c in show_df.columns]
                st.dataframe(show_df[final_cols], use_container_width=True)

                st.divider()
                st.markdown("##### 🗑️ Silme")
                del_id = st.selectbox("Silinecek Dosya No", df["Dosya Numarası"].unique(), key="data_del_id")
                if st.button("🗑️ SİL", type="secondary", key="data_del_btn"):
                    if delete_row_by_value(SHEET_ID, DATA_WS_INDEX, "Dosya Numarası", del_id):
                        st.success("Silindi!")
                        time.sleep(0.4)
                        st.rerun()
                    else:
                        st.error("Hata!")

    st.divider()

    # ---- FORM HELPER ----
    def gs(k): return str(current.get(k, ""))
    def gf(k):
        try: return float(current.get(k, 0))
        except: return 0.0
    def gi(k):
        try: return int(float(current.get(k, 0)))
        except: return 0
    def gc(k): return str(current.get(k, "")).lower() == "true"

    # ---- VERİ GİRİŞ FORMU ----
    with st.form("main_form"):
        st.markdown("### 👤 Klinik")
        c1, c2 = st.columns(2)

        with c1:
            dosya_no = st.text_input("Dosya Numarası (Zorunlu)", value=gs("Dosya Numarası"))
            ad_soyad = st.text_input("Adı Soyadı", value=gs("Adı Soyadı"))

            try:
                d_date = datetime.strptime(gs("Tarih"), "%Y-%m-%d")
            except:
                d_date = datetime.now()
            basvuru = st.date_input("Başvuru Tarihi", value=d_date)

            hekim = st.text_input("Veriyi Giren Hekim (Zorunlu)", value=gs("Hekim"))
            iletisim = st.text_input("İletişim", value=gs("İletişim"))

        with c2:
            cy, cc = st.columns(2)
            yas = cy.number_input("Yaş", step=1, value=gi("Yaş"))

            sex_l = ["Erkek", "Kadın"]
            try:
                s_ix = sex_l.index(gs("Cinsiyet"))
            except:
                s_ix = 0
            cinsiyet = cc.radio("Cinsiyet", sex_l, index=s_ix, horizontal=True)

            cb1, cb2, cb3 = st.columns(3)
            boy = cb1.number_input("Boy (cm)", value=gf("Boy"))
            kilo = cb2.number_input("Kilo (kg)", value=gf("Kilo"))

            bmi = kilo / ((boy / 100) ** 2) if boy > 0 else 0
            bsa = (boy * kilo / 3600) ** 0.5 if (boy > 0 and kilo > 0) else 0
            cb3.metric("BMI", f"{bmi:.1f}")

            ct1, ct2 = st.columns(2)
            ta_sis = ct1.number_input("TA Sistol (mmHg)", value=gi("TA Sistol"))
            ta_dia = ct2.number_input("TA Diyastol (mmHg)", value=gi("TA Diyastol"))

        st.markdown("---")
        ekg_l = ["NSR", "LBBB", "RBBB", "VPB", "SVT", "Diğer"]
        try:
            e_ix = ekg_l.index(gs("EKG"))
        except:
            e_ix = 0
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
        diger = st.text_input("Diğer", value=gs("Diğer"))

        st.markdown("### 🩸 Laboratuvar")
        l1, l2, l3, l4 = st.columns(4)

        hgb = l1.number_input("Hgb (g/dL)", value=gf("Hgb"))
        hct = l1.number_input("Hct (%)", value=gf("Hct"))
        wbc = l1.number_input("WBC (10³/µL)", value=gf("WBC"))
        plt = l1.number_input("PLT (10³/µL)", value=gf("PLT"))
        neu = l1.number_input("Nötrofil (%)", value=gf("Neu"))
        lym = l1.number_input("Lenfosit (%)", value=gf("Lym"))
        mpv = l1.number_input("MPV (fL)", value=gf("MPV"))
        rdw = l1.number_input("RDW (%)", value=gf("RDW"))

        glukoz = l2.number_input("Glukoz (mg/dL)", value=gf("Glukoz"))
        ure = l2.number_input("Üre (mg/dL)", value=gf("Üre"))
        krea = l2.number_input("Kreatinin (mg/dL)", value=gf("Kreatinin"))
        uric = l2.number_input("Ürik Asit (mg/dL)", value=gf("Ürik Asit"))
        na = l2.number_input("Na (mEq/L)", value=gf("Na"))
        k_val = l2.number_input("K (mEq/L)", value=gf("K"))
        alt = l2.number_input("ALT (U/L)", value=gf("ALT"))
        ast = l2.number_input("AST (U/L)", value=gf("AST"))
        prot = l2.number_input("Tot Prot (g/dL)", value=gf("Tot. Prot"))
        alb = l2.number_input("Albümin (g/dL)", value=gf("Albümin"))

        chol = l3.number_input("Chol (mg/dL)", value=gf("Chol"))
        ldl = l3.number_input("LDL (mg/dL)", value=gf("LDL"))
        hdl = l3.number_input("HDL (mg/dL)", value=gf("HDL"))
        trig = l3.number_input("Trig (mg/dL)", value=gf("Trig"))

        homo = l4.number_input("Homosistein (µmol/L)", value=gf("Homosistein"))
        lpa = l4.number_input("Lp(a) (mg/dL)", value=gf("Lp(a)"))
        folik = l4.number_input("Folik Asit (ng/mL)", value=gf("Folik Asit"))
        b12 = l4.number_input("B12 (pg/mL)", value=gf("B12"))

        # EKO parametreleri (eski set geri)
        st.markdown("### 🫀 Eko")
        e1, e2, e3, e4 = st.columns(4)

        with e1:
            st.caption("Yapısal")
            lvedd = st.number_input("LVEDD (mm)", value=gf("LVEDD"))
            lvesd = st.number_input("LVESD (mm)", value=gf("LVESD"))
            ivs = st.number_input("IVS (mm)", value=gf("IVS"))
            pw = st.number_input("PW (mm)", value=gf("PW"))
            lvedv = st.number_input("LVEDV (mL)", value=gf("LVEDV"))
            lvesv = st.number_input("LVESV (mL)", value=gf("LVESV"))
            ao = st.number_input("Ao Asc (mm)", value=gf("Ao Asc"))

            lvm = 0.0
            lvmi = 0.0
            rwt = 0.0
            if lvedd > 0 and ivs > 0 and pw > 0:
                d_cm = lvedd / 10
                i_cm = ivs / 10
                p_cm = pw / 10
                lvm = 0.8 * (1.04 * ((d_cm + i_cm + p_cm) ** 3 - d_cm ** 3)) + 0.6
                if bsa > 0:
                    lvmi = lvm / bsa
            if lvedd > 0 and pw > 0:
                rwt = (2 * pw) / lvedd
            st.caption(f"🔵 Mass:{lvm:.0f} | LVMi:{lvmi:.0f} | RWT:{rwt:.2f}")

        with e2:
            st.caption("Sistolik")
            lvef = st.number_input("LVEF (%)", value=gf("LVEF"))
            sv = st.number_input("SV (mL)", value=gf("SV"))
            lvot = st.number_input("LVOT VTI (cm)", value=gf("LVOT VTI"))
            gls = st.number_input("GLS (%)", value=gf("GLS"))
            gcs = st.number_input("GCS (%)", value=gf("GCS"))
            sdls = st.number_input("SD-LS (%)", value=gf("SD-LS"))

        with e3:
            st.caption("Diyastolik")
            mite = st.number_input("Mitral E (cm/sn)", value=gf("Mitral E"))
            mita = st.number_input("Mitral A (cm/sn)", value=gf("Mitral A"))
            septe = st.number_input("Septal e' (cm/sn)", value=gf("Septal e'"))
            late = st.number_input("Lateral e' (cm/sn)", value=gf("Lateral e'"))
            laedv = st.number_input("LAEDV (mL)", value=gf("LAEDV"))
            laesv = st.number_input("LAESV (mL)", value=gf("LAESV"))
            lastr = st.number_input("LA Strain (%)", value=gf("LA Strain"))

            ea = mite / mita if mita > 0 else 0
            ee = mite / septe if septe > 0 else 0
            laci = laedv / lvedv if lvedv > 0 else 0
            st.caption(f"🔵 E/A:{ea:.1f} | E/e':{ee:.1f} | LACi:{laci:.2f}")

        with e4:
            st.caption("Sağ Kalp")
            tapse = st.number_input("TAPSE (mm)", value=gf("TAPSE"))
            rvsm = st.number_input("RV Sm (cm/sn)", value=gf("RV Sm"))
            spap = st.number_input("sPAP (mmHg)", value=gf("sPAP"))
            tyvel = st.number_input("TY vel. (m/sn)", value=gf("TY vel."))
            rvot = st.number_input("RVOT VTI (cm)", value=gf("RVOT VTI"))
            rvota = st.number_input("RVOT accT (ms)", value=gf("RVOT accT"))

            tsm = tapse / rvsm if rvsm > 0 else 0
            tspap = tapse / spap if spap > 0 else 0
            st.caption(f"🔵 TAPSE/Sm: {tsm:.2f} | TAPSE/sPAP: {tspap:.2f}")

        st.write("")
        if st.form_submit_button("💾 KAYDET / GÜNCELLE", type="primary"):
            if not dosya_no or not hekim:
                st.error("Dosya No ve Hekim zorunlu!")
            else:
                final_data = {
                    "Dosya Numarası": dosya_no,
                    "Adı Soyadı": ad_soyad,
                    "Tarih": str(basvuru),
                    "Hekim": hekim,
                    "İletişim": iletisim,
                    "Yaş": yas,
                    "Cinsiyet": cinsiyet,
                    "Boy": boy,
                    "Kilo": kilo,
                    "BMI": bmi,
                    "BSA": bsa,
                    "TA Sistol": ta_sis,
                    "TA Diyastol": ta_dia,
                    "EKG": ekg,
                    "İlaçlar": ilaclar,
                    "Başlanan": baslanan,
                    "DM": dm,
                    "KAH": kah,
                    "HPL": hpl,
                    "İnme": inme,
                    "Sigara": sigara,
                    "Diğer": diger,
                    "Hgb": hgb,
                    "Hct": hct,
                    "WBC": wbc,
                    "PLT": plt,
                    "Neu": neu,
                    "Lym": lym,
                    "MPV": mpv,
                    "RDW": rdw,
                    "Glukoz": glukoz,
                    "Üre": ure,
                    "Kreatinin": krea,
                    "Ürik Asit": uric,
                    "Na": na,
                    "K": k_val,
                    "ALT": alt,
                    "AST": ast,
                    "Tot. Prot": prot,
                    "Albümin": alb,
                    "Chol": chol,
                    "LDL": ldl,
                    "HDL": hdl,
                    "Trig": trig,
                    "Lp(a)": lpa,
                    "Homosistein": homo,
                    "Folik Asit": folik,
                    "B12": b12,
                    "LVEDD": lvedd,
                    "LVESD": lvesd,
                    "IVS": ivs,
                    "PW": pw,
                    "LVEDV": lvedv,
                    "LVESV": lvesv,
                    "LV Mass": lvm,
                    "LVMi": lvmi,
                    "RWT": rwt,
                    "Ao Asc": ao,
                    "LVEF": lvef,
                    "SV": sv,
                    "LVOT VTI": lvot,
                    "GLS": gls,
                    "GCS": gcs,
                    "SD-LS": sdls,
                    "Mitral E": mite,
                    "Mitral A": mita,
                    "Mitral E/A": ea,
                    "Septal e'": septe,
                    "Lateral e'": late,
                    "Mitral E/e'": ee,
                    "LAEDV": laedv,
                    "LAESV": laesv,
                    "LA Strain": lastr,
                    "LACi": laci,
                    "TAPSE": tapse,
                    "RV Sm": rvsm,
                    "TAPSE/Sm": tsm,
                    "sPAP": spap,
                    "TY vel.": tyvel,
                    "TAPSE/sPAP": tspap,
                    "RVOT VTI": rvot,
                    "RVOT accT": rvota,
                }
                save_data_row(SHEET_ID, final_data, unique_col="Dosya Numarası", worksheet_index=DATA_WS_INDEX)
                st.success(f"✅ {dosya_no} kaydedildi / güncellendi!")
                time.sleep(0.6)
                st.rerun()
