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

DATA_WS_INDEX = 0       # 1. sayfa: Veri Girişi (H-Type HT)
CASE_WS_INDEX = 1       # 2. sayfa: Case Report Takip
LETTER_WS_INDEX = 2     # 3. sayfa: Editöre Mektup

# ✅ Fizyolojik Pacing (LBBAP/HBP)
PACED_SHEET_ID = SHEET_ID
PACED_WS_INDEX = 3      # 4. sayfa: Pacing Study

# ✅ AFMR – TEE LV-GLS
AFMR_SHEET_ID = SHEET_ID
AFMR_WS_INDEX = 4       # 5. sayfa: AFMR_TEE_LVGLS

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
        # güvenli: sadece ilgili sütunda ara
        headers = ws.row_values(1)
        if col_name in headers:
            col_idx = headers.index(col_name) + 1
            col_vals = ws.col_values(col_idx)
            row_to_delete = None
            for i, v in enumerate(col_vals[1:], start=2):
                if str(v).strip() == str(value).strip():
                    row_to_delete = i
                    break
            if row_to_delete:
                ws.delete_rows(row_to_delete)
                return True
            return False

        # fallback: tüm sheet'te find
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
        # header'a eklenmesi için missing_cols içinde zaten yakalanacak ama garanti:
        pass

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
        st.caption("Not: Bu şifre sadece veri ekranları için geçerli.")
    st.stop()

def confirm_delete_with_password(context_key: str) -> bool:
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
        <div class="ecg-name">Çile</div><div class="ecg-name">yoksa</div><div class="ecg-name">mükafat</div><div class="ecg-name">yoktur.</div>
        <div class="ecg-name">Çile</div><div class="ecg-name">yoksa</div><div class="ecg-name">mükafat</div><div class="ecg-name">yoktur.</div>
    </div>
</div>
""",
    unsafe_allow_html=True,
)

# ===================== SIDEBAR =====================
with st.sidebar:
    st.title("❤️ NEÜ-KARDİYO")

    menu = st.radio(
        "Menü",
        [
            "🏥 H-Type HT Çalışması",
            "📝 Case Report Takip",
            "✉️ Editöre Mektup",
            "🫀 Fizyolojik Pacing Çalışması",
            "🫀 AFMR – TEE LV-GLS",
        ],
    )

    st.divider()

    quotes = [
        "Halk içinde muteber bir nesne yok devlet gibi,\nOlmaya devlet cihanda bir nefes sıhhat gibi.\n(Kanuni Sultan Süleyman)",
        "Kalp, aklın bilmediği sebeplere sahiptir.\n(Blaise Pascal)",
        "İlim ilim bilmektir, ilim kendin bilmektir.\n(Yunus Emre)",
        "Zahmetsiz rahmet olmaz.",
        "Sabır acidir , meyvesi tatlıdır.",
        "Ne doğrarsan aşına, o gelir kaşığa.",
        "kısmet etmiş ise mevla; el getirir, yel getirir, sel getirir. kısmet etmez ise mevla; el götürür, yel götürür, sel götürür.",
        "Beden almakla doyar ruh vermekle",
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
            n_ad = st.text_input("Vaka")
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
            q = st.text_input("🔎 Arama (dosya no / vaka / doktor)", "")
            dfn_show = dfn.copy()

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
# =========== EKRAN 4: FİZYOLOJİK PACING ÇALIŞMASI =========
# =========================================================
elif menu == "🫀 Fizyolojik Pacing Çalışması":
    require_password_gate()

    st.header("🫀 Fizyolojik Pacing (LBBAP / HBP) Çalışması")
    st.caption("AV blok nedeniyle fizyolojik pacing yapılan hastalarda TTE+STE ile LV/RV fonksiyonları ve klinik sonlanımlar (NT-proBNP, yatış, mortalite).")

    # ✅ Unique key KayıtID olacak (DosyaNo + Ziyaret)
    dfp = load_data(PACED_SHEET_ID, PACED_WS_INDEX, required_col="KayıtID")

    col_left, col_right = st.columns([2, 3])

    with col_left:
        st.markdown("##### ⚙️ İşlem Seçimi")
        mode = st.radio("Mod:", ["Yeni Kayıt", "Düzenleme"], horizontal=True, label_visibility="collapsed", key="pacing_mode")

        current = {}
        if mode == "Düzenleme":
            if not dfp.empty and "KayıtID" in dfp.columns:
                edit_key = st.selectbox("Düzenlenecek Kayıt (KayıtID):", dfp["KayıtID"].unique(), key="pacing_edit_key")
                if edit_key:
                    current = dfp[dfp["KayıtID"] == edit_key].iloc[0].to_dict()
                    st.success(f"Seçildi: {current.get('Dosya Numarası','')} | {current.get('Ziyaret','')}")
            else:
                st.warning("Düzenlenecek kayıt yok.")

    with col_right:
        with st.expander("📋 KAYITLI LİSTE / ARAMA / SİLME", expanded=True):
            if st.button("🔄 Listeyi Yenile", key="pacing_refresh"):
                st.rerun()

            if dfp.empty:
                st.info("Kayıt yok (veya sheet yok/başlık uyumsuz).")
            else:
                q = st.text_input("🔎 Arama (dosya no / hekim / ziyaret)", "", key="pacing_search")
                show_df = dfp.copy()

                if "Adı Soyadı" in show_df.columns:
                    show_df = show_df.drop(columns=["Adı Soyadı"])

                if q.strip():
                    mask = show_df.apply(
                        lambda row: row.astype(str).str.contains(q, case=False, na=False).any(),
                        axis=1,
                    )
                    show_df = show_df[mask].copy()

                cols_show = ["KayıtID", "Dosya Numarası", "Ziyaret", "Tarih", "Hekim", "Pacing Tipi"]
                final_cols = [c for c in cols_show if c in show_df.columns]
                st.dataframe(show_df[final_cols], use_container_width=True)

                st.divider()
                st.markdown("##### 🗑️ Silme (Şifreli)")
                if confirm_delete_with_password("pacing"):
                    del_key = st.selectbox("Silinecek KayıtID", dfp["KayıtID"].unique(), key="pacing_del_key")
                    if st.button("🗑️ SİL", type="secondary", key="pacing_del_btn"):
                        if delete_row_by_value(PACED_SHEET_ID, PACED_WS_INDEX, "KayıtID", del_key):
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

    VISIT_LABELS = ["1. Başlangıç", "2. Kontrol"]
    VISIT_CODE = {"1. Başlangıç": "BASLANGIC", "2. Kontrol": "KONTROL"}

    with st.form("pacing_main_form"):
        st.markdown("### 👤 Klinik")
        c1, c2 = st.columns(2)

        with c1:
            dosya_no = st.text_input("Dosya Numarası (Zorunlu)", value=gs("Dosya Numarası"))

            prev_visit = gs("Ziyaret")
            visit_ix = VISIT_LABELS.index(prev_visit) if prev_visit in VISIT_LABELS else 0
            ziyaret = st.selectbox("Ziyaret", VISIT_LABELS, index=visit_ix)

            kayit_id = f"{dosya_no.strip()}_{VISIT_CODE.get(ziyaret,'BASLANGIC')}".strip("_")
            st.caption(f"🆔 KayıtID: {kayit_id}")

            ad_soyad = st.text_input("Adı Soyadı", value=gs("Adı Soyadı"))

            try:
                d_date = datetime.strptime(gs("Tarih"), "%Y-%m-%d").date()
            except:
                d_date = datetime.now().date()
            basvuru = st.date_input("Başvuru Tarihi", value=d_date)

            hekim = st.text_input("Veriyi Giren Hekim (Zorunlu)", value=gs("Hekim"))
            iletisim = st.text_input("İletişim", value=gs("İletişim"))

            pacing_tipi_l = ["LBBAP", "HBP", "Diğer"]
            pt = gs("Pacing Tipi")
            pacing_tipi = st.selectbox(
                "Pacing Tipi",
                pacing_tipi_l,
                index=(pacing_tipi_l.index(pt) if pt in pacing_tipi_l else 0),
            )

            st.markdown("##### Pacing Endikasyonu")
            av_tam = st.checkbox("AV Tam Blok", value=gc("Pacing Endikasyonu: AV Tam Blok"))
            av_2 = st.checkbox("2. Derece AV Blok", value=gc("Pacing Endikasyonu: 2. Derece AV Blok"))

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

        ntprobnp = l4.number_input("NT-proBNP (pg/mL)", value=gf("NT-proBNP"))
        hs_trop = l4.number_input("hs-Troponin (ng/L)", value=gf("hs-Troponin"))

        st.markdown("### 🫀 Eko / STE")
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
            st.caption("Sistolik / STE")
            lvef = st.number_input("LVEF (%)", value=gf("LVEF"))
            sv = st.number_input("SV (mL)", value=gf("SV"))
            lvot = st.number_input("LVOT VTI (cm)", value=gf("LVOT VTI"))
            gls = st.number_input("GLS (%)", value=gf("GLS"))
            gcs = st.number_input("GCS (%)", value=gf("GCS"))

            lv_grs = st.number_input("LV GRS (%)", value=gf("LV GRS"))
            sd_ts_syst = st.number_input("SD-TS-SYST (%)", value=gf("SD-TS-SYST"))
            sd_ls_syst = st.number_input("SD-LS-SYST (%)", value=gf("SD-LS-SYST"))

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
            st.caption("Sağ Kalp / RV-STE")
            tapse = st.number_input("TAPSE (mm)", value=gf("TAPSE"))
            rvsm = st.number_input("RV Sm (cm/sn)", value=gf("RV Sm"))
            spap = st.number_input("sPAP (mmHg)", value=gf("sPAP"))
            tyvel = st.number_input("TY vel. (m/sn)", value=gf("TY vel."))
            rvot = st.number_input("RVOT VTI (cm)", value=gf("RVOT VTI"))
            rvota = st.number_input("RVOT accT (ms)", value=gf("RVOT accT"))

            rv_fw_ls = st.number_input("RV Free-Wall Longitudinal Strain (%)", value=gf("RV FWLS"))
            rv_fac = st.number_input("RV FAC (%)", value=gf("RV FAC"))
            rv_grs = st.number_input("RV GRS (%)", value=gf("RV GRS"))

            tsm = tapse / rvsm if rvsm > 0 else 0
            tspap = tapse / spap if spap > 0 else 0
            st.caption(f"🔵 TAPSE/Sm: {tsm:.2f} | TAPSE/sPAP: {tspap:.2f}")

        st.write("")
        if st.form_submit_button("💾 KAYDET / GÜNCELLE", type="primary"):
            if not dosya_no or not hekim:
                st.error("Dosya No ve Hekim zorunlu!")
            else:
                final_data = {
                    "KayıtID": kayit_id,
                    "Dosya Numarası": dosya_no,
                    "Ziyaret": ziyaret,
                    "Adı Soyadı": ad_soyad,
                    "Tarih": str(basvuru),
                    "Hekim": hekim,
                    "İletişim": iletisim,

                    "Pacing Tipi": pacing_tipi,
                    "Pacing Endikasyonu: AV Tam Blok": av_tam,
                    "Pacing Endikasyonu: 2. Derece AV Blok": av_2,

                    "Yaş": yas,
                    "Cinsiyet": cinsiyet,
                    "Boy": boy,
                    "Kilo": kilo,
                    "BMI": bmi,
                    "BSA": bsa,
                    "TA Sistol": ta_sis,
                    "TA Diyastol": ta_dia,

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

                    "NT-proBNP": ntprobnp,
                    "hs-Troponin": hs_trop,

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
                    "LV GRS": lv_grs,

                    "SD-TS-SYST": sd_ts_syst,
                    "SD-LS-SYST": sd_ls_syst,

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

                    "RV FWLS": rv_fw_ls,
                    "RV FAC": rv_fac,
                    "RV GRS": rv_grs,
                }

                save_data_row(PACED_SHEET_ID, final_data, unique_col="KayıtID", worksheet_index=PACED_WS_INDEX)
                st.success(f"✅ {kayit_id} kaydedildi / güncellendi!")
                time.sleep(0.6)
                st.rerun()

# =========================================================
# ===================== EKRAN 5: AFMR – TEE LV-GLS =====================
# =========================================================
elif menu == "🫀 AFMR – TEE LV-GLS":
    require_password_gate()

    st.header("🫀 AFMR – TEE ile LV-GLS (TTE ile karşılaştırma)")
    st.caption("Atrial sekonder MR (AFMR): TEE-LVGLS ↔ TTE-LVGLS uyumu, MR şiddeti ayrımı, AF vs SR alt grupları.")

    dfa = load_data(AFMR_SHEET_ID, AFMR_WS_INDEX, required_col="KayıtID")

    left, right = st.columns([2, 3])

    with left:
        st.markdown("##### ⚙️ İşlem Seçimi")
        mode = st.radio("Mod:", ["Yeni Kayıt", "Düzenleme"], horizontal=True, label_visibility="collapsed", key="afmr_mode")

        current = {}
        if mode == "Düzenleme":
            if not dfa.empty and "KayıtID" in dfa.columns:
                edit_key = st.selectbox("Düzenlenecek kayıt (KayıtID):", dfa["KayıtID"].unique(), key="afmr_edit_key")
                if edit_key:
                    current = dfa[dfa["KayıtID"] == edit_key].iloc[0].to_dict()
                    st.success(f"Seçildi: {current.get('Dosya No','')} | {current.get('Ziyaret','')} | {current.get('Ritim','')}")
            else:
                st.warning("Düzenlenecek kayıt yok (veya sheet boş).")

    with right:
        with st.expander("📋 Kayıtlı Liste / Arama / Silme", expanded=True):
            if st.button("🔄 Listeyi Yenile", key="afmr_refresh"):
                st.rerun()

            if dfa.empty:
                st.info("Kayıt yok (veya AFMR sheet index yanlış / başlıklar oluşmadı). İlk kaydı girince başlıklar otomatik oluşur.")
            else:
                q = st.text_input("🔎 Arama (dosya no / hekim / ritim)", "", key="afmr_search")
                show_df = dfa.copy()

                for c in ["Hasta", "Adı Soyadı"]:
                    if c in show_df.columns:
                        show_df = show_df.drop(columns=[c])

                if q.strip():
                    mask = show_df.apply(lambda row: row.astype(str).str.contains(q, case=False, na=False).any(), axis=1)
                    show_df = show_df[mask].copy()

                cols_show = ["KayıtID", "Dosya No", "Tarih", "Ziyaret", "Ritim", "Hekim", "MR (TEE) Derece"]
                final_cols = [c for c in cols_show if c in show_df.columns]
                st.dataframe(show_df[final_cols], use_container_width=True)

                st.divider()
                st.markdown("##### 🗑️ Silme (Şifreli)")
                if confirm_delete_with_password("afmr"):
                    del_key = st.selectbox("Silinecek KayıtID", dfa["KayıtID"].unique(), key="afmr_del_key")
                    if st.button("🗑️ SİL", type="secondary", key="afmr_del_btn"):
                        if delete_row_by_value(AFMR_SHEET_ID, AFMR_WS_INDEX, "KayıtID", del_key):
                            st.success("Silindi!")
                            time.sleep(0.4)
                            st.rerun()
                        else:
                            st.error("Hata!")

    st.divider()

    def gs(k): return str(current.get(k, ""))
    def gf(k):
        try: return float(current.get(k, 0))
        except: return 0.0
    def gi(k):
        try: return int(float(current.get(k, 0)))
        except: return 0
    def gc(k): return str(current.get(k, "")).lower() == "true"

    VISIT_LABELS = ["1. Başlangıç", "2. Kontrol"]
    VISIT_CODE = {"1. Başlangıç": "BASLANGIC", "2. Kontrol": "KONTROL"}

    with st.form("afmr_form"):
        st.markdown("### ✅ Dahil / ⛔ Dışlama / Ritim")
        a1, a2, a3 = st.columns(3)

        with a1:
            inc_age = st.checkbox("≥18 yaş", value=gc("Dahil: ≥18"))
            inc_afmr = st.checkbox("AFMR tanısı (primer leaflet patolojisi yok)", value=gc("Dahil: AFMR"))
            inc_tee_ind = st.checkbox("Klinik TEE endikasyonu mevcut", value=gc("Dahil: TEE endikasyonu"))
        with a2:
            inc_mr = st.checkbox("MR: orta/ileri", value=gc("Dahil: MR orta/ileri"))
            consent = st.checkbox("Gönüllü onam", value=gc("Onam"))
        with a3:
            ritim = st.radio("Ritim grubu", ["AF", "SR"], index=(0 if gs("Ritim") != "SR" else 1), horizontal=True)

        st.markdown("### 👤 Demografi ve Klinik")
        c1, c2 = st.columns(2)

        with c1:
            hasta = st.text_input("Hasta (opsiyonel)", value=gs("Hasta"))
            dosya_no = st.text_input("Dosya No (Zorunlu)", value=gs("Dosya No"))

            prev_visit = gs("Ziyaret")
            visit_ix = VISIT_LABELS.index(prev_visit) if prev_visit in VISIT_LABELS else 0
            ziyaret = st.selectbox("Ziyaret", VISIT_LABELS, index=visit_ix)

            try:
                d_date = datetime.strptime(gs("Tarih"), "%Y-%m-%d").date()
            except:
                d_date = datetime.now().date()
            tarih = st.date_input("Tarih", value=d_date)

            kayit_id = f"{dosya_no.strip()}_{VISIT_CODE.get(ziyaret,'BASLANGIC')}_{tarih.strftime('%Y%m%d')}".strip("_")
            st.caption(f"🆔 KayıtID: {kayit_id}")

            hekim = st.text_input("Hekim", value=gs("Hekim"))
            yas = st.number_input("Yaş", step=1, value=gi("Yaş"))
            cinsiyet = st.radio("Cinsiyet", ["Kadın", "Erkek"], index=(0 if gs("Cinsiyet") != "Erkek" else 1), horizontal=True)

        with c2:
            boy = st.number_input("Boy (cm)", value=gf("Boy"))
            kilo = st.number_input("Kilo (kg)", value=gf("Kilo"))
            bmi = kilo / ((boy / 100) ** 2) if boy > 0 else 0
            bsa = (boy * kilo / 3600) ** 0.5 if (boy > 0 and kilo > 0) else 0
            st.metric("BMI", f"{bmi:.1f}")
            st.metric("BSA", f"{bsa:.2f}")

            nyha = st.selectbox("NYHA", ["I", "II", "III", "IV"],
                                index=(["I","II","III","IV"].index(gs("NYHA")) if gs("NYHA") in ["I","II","III","IV"] else 0))

            st.markdown("##### Semptomlar")
            s1, s2, s3, s4 = st.columns(4)
            sym_dispne = s1.checkbox("Dispne", value=gc("Semptom: Dispne"))
            sym_carpinti = s2.checkbox("Çarpıntı", value=gc("Semptom: Çarpıntı"))
            sym_yorgunluk = s3.checkbox("Yorgunluk", value=gc("Semptom: Yorgunluk"))
            sym_diger = s4.text_input("Diğer", value=gs("Semptom: Diğer"))

        st.markdown("### 🫀 AF Öyküsü (varsa)")
        if ritim == "AF":
            af1, af2, af3 = st.columns(3)
            af_sure = af1.number_input("AF süresi (ay)", value=gf("AF süresi (ay)"))
            af_tipi = af2.selectbox("AF tipi", ["Paroksismal", "Persistan", "Permanen"],
                                    index=(["Paroksismal","Persistan","Permanen"].index(gs("AF tipi"))
                                           if gs("AF tipi") in ["Paroksismal","Persistan","Permanen"] else 0))
            af_not = af3.text_input("AF not (opsiyonel)", value=gs("AF not"))
        else:
            af_sure, af_tipi, af_not = 0, "", ""

        st.markdown("### 🧾 Tıbbi Öykü")
        k1, k2, k3, k4 = st.columns(4)
        hx_ht = k1.checkbox("Hipertansiyon", value=gc("Öykü: HT"))
        hx_dm = k1.checkbox("Diyabet", value=gc("Öykü: DM"))
        hx_kah = k2.checkbox("KAH / MI", value=gc("Öykü: KAH/MI"))
        hx_kby = k2.checkbox("KBY (eGFR<60)", value=gc("Öykü: KBY"))
        hx_koah = k3.checkbox("KOAH/Astım", value=gc("Öykü: KOAH/Astım"))
        hx_obez = k3.checkbox("Obezite (BMI≥30)", value=gc("Öykü: Obezite"))
        hx_osa = k4.checkbox("Uyku apnesi", value=gc("Öykü: Uyku apnesi"))
        hx_tiroid = k4.checkbox("Tiroid hastalığı", value=gc("Öykü: Tiroid"))
        hx_diger = st.text_input("Diğer (öykü)", value=gs("Öykü: Diğer"))

        st.markdown("### 💊 Güncel Tedavi")
        t1, t2, t3 = st.columns(3)
        med_bb = t1.checkbox("Beta bloker", value=gc("Tedavi: BB"))
        med_ace = t1.checkbox("ACEi/ARB/ARNI", value=gc("Tedavi: ACEi/ARB/ARNI"))
        med_mra = t2.checkbox("MRA", value=gc("Tedavi: MRA"))
        med_sglt2 = t2.checkbox("SGLT2 inhibitörü", value=gc("Tedavi: SGLT2"))
        med_diur = t3.checkbox("Diüretik", value=gc("Tedavi: Diüretik"))
        med_antitrom = t3.checkbox("Antikoagülan/Antiplatelet", value=gc("Tedavi: Antitrombotik"))
        med_antitrom_detay = st.text_input("Antitrombotik (hangisi?)", value=gs("Tedavi: Antitrombotik detay"))
        med_diger = st.text_input("Diğer (tedavi)", value=gs("Tedavi: Diğer"))

        st.markdown("### 🩸 Laboratuvar (opsiyonel)")
        l1, l2, l3 = st.columns(3)
        lab_hb = l1.number_input("Hb (g/dL)", value=gf("Hb"))
        lab_krea = l1.number_input("Kreatinin (mg/dL)", value=gf("Kreatinin"))
        lab_egfr = l1.number_input("eGFR (mL/dk/1.73m²)", value=gf("eGFR"))

        bnp_type = l2.selectbox("BNP tipi", ["NT-proBNP", "BNP"], index=(0 if gs("BNP tipi") != "BNP" else 1))
        lab_bnp = l2.number_input(f"{bnp_type} değeri", value=gf(bnp_type))
        lab_bnp_unit = l2.text_input("Birim", value=(gs("BNP birim") if gs("BNP birim") else "pg/mL"))
        lab_diger = l3.text_input("Diğer (lab)", value=gs("Lab: Diğer"))

        st.markdown("### 🧠 Görüntüleme Seansı – Hemodinami & Sedasyon")
        h1, h2, h3 = st.columns(3)
        sed_ilac = h1.text_input("Sedasyon ilacı", value=(gs("Sedasyon ilacı") if gs("Sedasyon ilacı") else "Midazolam"))
        sed_doz = h1.number_input("Doz (mg)", value=gf("Sedasyon doz (mg)"))
        sed_saat = h1.text_input("Uygulama saati (HH:MM)", value=gs("Sedasyon saat"))
        pre_bp = h2.text_input("TEE öncesi BP", value=gs("TEE öncesi BP"))
        pre_hr = h2.text_input("TEE öncesi HR", value=gs("TEE öncesi HR"))
        pre_spo2 = h2.text_input("TEE öncesi SpO2", value=gs("TEE öncesi SpO2"))
        tee_avg_bp = h3.text_input("TEE sırasında ort. BP", value=gs("TEE ort BP"))
        tee_avg_hr = h3.text_input("TEE sırasında ort. HR", value=gs("TEE ort HR"))
        post_bp_hr = h3.text_input("TEE sonrası BP/HR", value=gs("TEE sonrası BP/HR"))

        tte_bp_hr = st.text_input("TTE (TEE hemen sonrası) BP/HR", value=gs("TTE sonrası BP/HR"))
        tee_rhythm = st.radio("TEE sırasında ritim", ["AF", "SR"], index=(0 if gs("TEE ritim") != "SR" else 1), horizontal=True)
        tee_hr = st.number_input("TEE sırasında HR", value=gi("TEE HR"))

        st.markdown("### 🩻 TEE – MR Kantitasyonu & Morfoloji")
        m1, m2, m3 = st.columns(3)
        mr_deg_tee = m1.selectbox("MR (TEE) Derece (integratif)", ["Orta", "İleri"],
                                  index=(["Orta","İleri"].index(gs("MR (TEE) Derece")) if gs("MR (TEE) Derece") in ["Orta","İleri"] else 0))
        mr_jet = m1.selectbox("MR jet tipi", ["Santral", "Eksantrik", "Multijet"],
                              index=(["Santral","Eksantrik","Multijet"].index(gs("MR jet tipi")) if gs("MR jet tipi") in ["Santral","Eksantrik","Multijet"] else 0))
        mr_jet_yon = m1.text_input("Jet yön (ops.)", value=gs("Jet yön"))
        vc = m2.number_input("Vena contracta (mm)", value=gf("VC (mm)"))
        vca3d = m2.number_input("3D VCA (cm²)", value=gf("3D VCA (cm2)"))
        eroa = m2.number_input("EROA (mm²)", value=gf("EROA (mm2)"))
        rvol = m3.number_input("Regürjitan volüm (mL)", value=gf("RVol (mL)"))
        rfrac = m3.number_input("Regürjitan fraksiyon (%)", value=gf("RFrac (%)"))
        pv_flow = m3.selectbox("Pulmoner ven akımı", ["S baskın", "D baskın", "Sistolik reversiyon"],
                               index=(["S baskın","D baskın","Sistolik reversiyon"].index(gs("PV akım")) if gs("PV akım") in ["S baskın","D baskın","Sistolik reversiyon"] else 0))
        pv_sd = m3.number_input("PV S/D oranı", value=gf("PV S/D"))
        pisa_r = st.number_input("PISA yarıçapı (mm)", value=gf("PISA r (mm)"))
        alias_v = st.number_input("Aliasing V (cm/sn)", value=gf("Aliasing V (cm/s)"))

        st.markdown("#### Mitral annulus / leaflet ölçümleri")
        g1, g2, g3, g4 = st.columns(4)
        ap_d = g1.number_input("AP diameter (mm)", value=gf("AP diameter (mm)"))
        cc_d = g2.number_input("CC diameter (mm)", value=gf("CC diameter (mm)"))
        circ = g3.number_input("3D circumference (mm)", value=gf("3D circumference (mm)"))
        coapt_area = g4.number_input("Coaptation Area (mm²)", value=gf("Coaptation Area (mm2)"))

        g5, g6, g7, g8 = st.columns(4)
        coapt_len = g5.number_input("Coaptation Length (mm)", value=gf("Coaptation Length (mm)"))
        coapt_depth = g6.number_input("Coaptation Depth (mm)", value=gf("Coaptation Depth (mm)"))
        coapt_dist = g7.number_input("Coaptation Distance (posterior) (mm)", value=gf("Coaptation Distance (mm)"))
        aml_len = g8.number_input("AML Length (mm)", value=gf("AML Length (mm)"))
        pml_len = st.number_input("PML Length (mm)", value=gf("PML Length (mm)"))

        st.markdown("### 🫀 TEE – LV Fonksiyon & Strain")
        s1, s2, s3 = st.columns(3)
        lvef = s1.number_input("LVEF (%)", value=gf("TEE LVEF"))
        lvef_met = s1.selectbox("LVEF yöntemi", ["Biplan Simpson", "Gözlemsel", "3D", "Diğer"],
                                index=(["Biplan Simpson","Gözlemsel","3D","Diğer"].index(gs("LVEF yöntem")) if gs("LVEF yöntem") in ["Biplan Simpson","Gözlemsel","3D","Diğer"] else 0))
        lvedv = s2.number_input("LVEDV (mL)", value=gf("TEE LVEDV"))
        lvesv = s2.number_input("LVESV (mL)", value=gf("TEE LVESV"))
        sv = s2.number_input("SV (mL)", value=gf("TEE SV"))
        tee_gls = s3.number_input("LV-GLS (TEE) (%)", value=gf("TEE LVGLS"))
        fr = s3.number_input("Frame rate (fps)", value=gf("Frame rate"))
        ivs = s3.number_input("IVS (mm)", value=gf("IVS (mm)"))
        pw = s3.number_input("PW (mm)", value=gf("PW (mm)"))

        st.markdown("### 🫁 TTE (TEE Sonrası) – Karşılaştırma")
        t1, t2, t3 = st.columns(3)
        mr_deg_tte = t1.selectbox("MR (TTE) Derece (integratif)", ["Hafif", "Orta", "İleri"],
                                  index=(["Hafif","Orta","İleri"].index(gs("MR (TTE) Derece")) if gs("MR (TTE) Derece") in ["Hafif","Orta","İleri"] else 1))
        tte_lvef = t1.number_input("LVEF (TTE) (%)", value=gf("TTE LVEF"))
        tte_lvedv = t2.number_input("LVEDV (TTE) (mL)", value=gf("TTE LVEDV"))
        tte_lvesv = t2.number_input("LVESV (TTE) (mL)", value=gf("TTE LVESV"))
        tte_sv = t2.number_input("SV (TTE) (mL)", value=gf("TTE SV"))
        tte_gls = t3.number_input("LV-GLS (TTE) (%)", value=gf("TTE LVGLS"))
        laesv = t3.number_input("LAESV (mL)", value=gf("LAESV"))

        tr_deg = st.selectbox("TY/TR derecesi (integratif)", ["Hafif", "Orta", "İleri"],
                              index=(["Hafif","Orta","İleri"].index(gs("TR derece")) if gs("TR derece") in ["Hafif","Orta","İleri"] else 0))
        tr_vmax = st.number_input("TR Vmax (m/sn)", value=gf("TR Vmax"))
        spap = st.number_input("Tahmini sPAP (mmHg)", value=gf("sPAP"))
        tapse = st.number_input("TAPSE (mm)", value=gf("TAPSE"))

        st.write("")
        if st.form_submit_button("💾 KAYDET / GÜNCELLE", type="primary"):
            if not dosya_no or not hekim:
                st.error("Dosya No ve Hekim zorunlu!")
            else:
                payload = {
                    "KayıtID": kayit_id,
                    "Hasta": hasta,
                    "Dosya No": dosya_no,
                    "Tarih": str(tarih),
                    "Ziyaret": ziyaret,
                    "Hekim": hekim,

                    "Dahil: ≥18": inc_age,
                    "Dahil: AFMR": inc_afmr,
                    "Dahil: TEE endikasyonu": inc_tee_ind,
                    "Dahil: MR orta/ileri": inc_mr,
                    "Onam": consent,

                    "Yaş": yas,
                    "Cinsiyet": cinsiyet,
                    "Boy": boy,
                    "Kilo": kilo,
                    "BMI": bmi,
                    "BSA": bsa,
                    "NYHA": nyha,

                    "Semptom: Dispne": sym_dispne,
                    "Semptom: Çarpıntı": sym_carpinti,
                    "Semptom: Yorgunluk": sym_yorgunluk,
                    "Semptom: Diğer": sym_diger,

                    "Ritim": ritim,
                    "AF süresi (ay)": af_sure,
                    "AF tipi": af_tipi,
                    "AF not": af_not,

                    "Öykü: HT": hx_ht,
                    "Öykü: DM": hx_dm,
                    "Öykü: KAH/MI": hx_kah,
                    "Öykü: KBY": hx_kby,
                    "Öykü: KOAH/Astım": hx_koah,
                    "Öykü: Obezite": hx_obez,
                    "Öykü: Uyku apnesi": hx_osa,
                    "Öykü: Tiroid": hx_tiroid,
                    "Öykü: Diğer": hx_diger,

                    "Tedavi: BB": med_bb,
                    "Tedavi: ACEi/ARB/ARNI": med_ace,
                    "Tedavi: MRA": med_mra,
                    "Tedavi: SGLT2": med_sglt2,
                    "Tedavi: Diüretik": med_diur,
                    "Tedavi: Antitrombotik": med_antitrom,
                    "Tedavi: Antitrombotik detay": med_antitrom_detay,
                    "Tedavi: Diğer": med_diger,

                    "Hb": lab_hb,
                    "Kreatinin": lab_krea,
                    "eGFR": lab_egfr,
                    "BNP tipi": bnp_type,
                    "NT-proBNP": (lab_bnp if bnp_type == "NT-proBNP" else ""),
                    "BNP": (lab_bnp if bnp_type == "BNP" else ""),
                    "BNP birim": lab_bnp_unit,
                    "Lab: Diğer": lab_diger,

                    "Sedasyon ilacı": sed_ilac,
                    "Sedasyon doz (mg)": sed_doz,
                    "Sedasyon saat": sed_saat,
                    "TEE öncesi BP": pre_bp,
                    "TEE öncesi HR": pre_hr,
                    "TEE öncesi SpO2": pre_spo2,
                    "TEE ort BP": tee_avg_bp,
                    "TEE ort HR": tee_avg_hr,
                    "TEE sonrası BP/HR": post_bp_hr,
                    "TTE sonrası BP/HR": tte_bp_hr,
                    "TEE ritim": tee_rhythm,
                    "TEE HR": tee_hr,

                    "MR (TEE) Derece": mr_deg_tee,
                    "MR jet tipi": mr_jet,
                    "Jet yön": mr_jet_yon,
                    "VC (mm)": vc,
                    "3D VCA (cm2)": vca3d,
                    "EROA (mm2)": eroa,
                    "RVol (mL)": rvol,
                    "RFrac (%)": rfrac,
                    "PV akım": pv_flow,
                    "PV S/D": pv_sd,
                    "PISA r (mm)": pisa_r,
                    "Aliasing V (cm/s)": alias_v,

                    "AP diameter (mm)": ap_d,
                    "CC diameter (mm)": cc_d,
                    "3D circumference (mm)": circ,
                    "Coaptation Area (mm2)": coapt_area,
                    "Coaptation Length (mm)": coapt_len,
                    "Coaptation Depth (mm)": coapt_depth,
                    "Coaptation Distance (mm)": coapt_dist,
                    "AML Length (mm)": aml_len,
                    "PML Length (mm)": pml_len,

                    "TEE LVEF": lvef,
                    "LVEF yöntem": lvef_met,
                    "TEE LVEDV": lvedv,
                    "TEE LVESV": lvesv,
                    "TEE SV": sv,
                    "TEE LVGLS": tee_gls,
                    "Frame rate": fr,
                    "IVS (mm)": ivs,
                    "PW (mm)": pw,

                    "MR (TTE) Derece": mr_deg_tte,
                    "TTE LVEF": tte_lvef,
                    "TTE LVEDV": tte_lvedv,
                    "TTE LVESV": tte_lvesv,
                    "TTE SV": tte_sv,
                    "TTE LVGLS": tte_gls,
                    "LAESV": laesv,
                    "TR derece": tr_deg,
                    "TR Vmax": tr_vmax,
                    "sPAP": spap,
                    "TAPSE": tapse,
                }

                save_data_row(AFMR_SHEET_ID, payload, unique_col="KayıtID", worksheet_index=AFMR_WS_INDEX)
                st.success(f"✅ Kaydedildi/Güncellendi: {kayit_id}")
                time.sleep(0.5)
                st.rerun()

# =========================================================
# ===================== EKRAN 1: H-TYPE VERİ GİRİŞİ =====================
# =========================================================
elif menu == "🏥 H-Type HT Çalışması":
    require_password_gate()

    st.header("🏥 H-Type HT Çalışması")

    df = load_data(SHEET_ID, DATA_WS_INDEX, required_col="Dosya Numarası")

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
        mode = st.radio("Mod:", ["Yeni Kayıt", "Düzenleme"], horizontal=True, label_visibility="collapsed", key="htype_mode")

        current = {}
        if mode == "Düzenleme":
            if not df.empty:
                edit_id = st.selectbox("Düzenlenecek Hasta (Dosya No):", df["Dosya Numarası"].unique(), key="htype_edit_id")
                if edit_id:
                    current = df[df["Dosya Numarası"] == edit_id].iloc[0].to_dict()
                    st.success(f"Seçildi: {current.get('Adı Soyadı', '')}")
            else:
                st.warning("Düzenlenecek kayıt yok.")

    with col_right:
        with st.expander("📋 KAYITLI HASTA LİSTESİ / ARAMA / SİLME", expanded=True):
            if st.button("🔄 Listeyi Yenile", key="htype_refresh"):
                st.rerun()

            if df.empty:
                st.info("Kayıt yok.")
            else:
                q = st.text_input("🔎 Arama (dosya no / hekim)", "", key="htype_search")
                show_df = df.copy()

                if "Adı Soyadı" in show_df.columns:
                    show_df = show_df.drop(columns=["Adı Soyadı"])

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

    def gs(k): return str(current.get(k, ""))
    def gf(k):
        try: return float(current.get(k, 0))
        except: return 0.0
    def gi(k):
        try: return int(float(current.get(k, 0)))
        except: return 0
    def gc(k): return str(current.get(k, "")).lower() == "true"

    with st.form("main_form"):
        st.markdown("### 👤 Klinik")
        c1, c2 = st.columns(2)

        with c1:
            dosya_no = st.text_input("Dosya Numarası (Zorunlu)", value=gs("Dosya Numarası"))
            ad_soyad = st.text_input("Adı Soyadı", value=gs("Adı Soyadı"))

            try:
                d_date = datetime.strptime(gs("Tarih"), "%Y-%m-%d").date()
            except:
                d_date = datetime.now().date()
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

# =========================================================
# ===================== FALLBACK ==========================
# =========================================================
else:
    st.warning("Menü seçimi tanınmadı.")
