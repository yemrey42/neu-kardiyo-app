# web_app.py
# NEÜ-KARDİYO | Streamlit + Google Sheets (CRUD)
# Not: Excel/CSV indirme YOK (isteğe göre kaldırıldı)

import time
import random
from datetime import datetime
from typing import Dict, Any, Optional, List

import pandas as pd
import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials


# ===================== AYARLAR =====================
st.set_page_config(page_title="NEÜ-KARDİYO", page_icon="❤️", layout="wide")

# Tek bir Google Sheet içinde sekmeler:
SHEET_ID = "1_Jd27n2lvYRl-oKmMOVySd5rGvXLrflDCQJeD_Yz6Y4"
DATA_WS_INDEX = int(st.secrets.get("data_ws_index", 0))     # H-Type HT
CASE_WS_INDEX = int(st.secrets.get("case_ws_index", 1))     # Case Report
LETTER_WS_INDEX = int(st.secrets.get("letter_ws_index", 2)) # Editöre mektup
PACED_WS_INDEX = int(st.secrets.get("paced_ws_index", 3))   # Fizyolojik pacing
AFMR_WS_INDEX = int(st.secrets.get("afmr_ws_index", 4))     # AFMR
CVABL_WS_INDEX = int(st.secrets.get("cvabl_ws_index", 5))  # Kardiyoversiyon-Ablasyon / TEE-GLS

APP_TITLE = "❤️ NEÜ-KARDİYO"


# ===================== HELPERS =====================
def _safe_str(x) -> str:
    if x is None:
        return ""
    return str(x)

def _clamp_number(value, min_v=None, max_v=None, default=None):
    """Streamlit number_input min/max hatasını engellemek için."""
    try:
        v = float(value)
    except:
        v = default if default is not None else 0.0

    if min_v is not None and v < min_v:
        v = min_v
    if max_v is not None and v > max_v:
        v = max_v
    return v

def colnum_to_letter(n: int) -> str:
    """1->A, 27->AA"""
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s

def _get_service_account_info() -> Dict[str, Any]:
    """
    Streamlit secrets'ten SA json'ı güvenli şekilde al.
    - Tercih edilen: st.secrets["gcp_service_account"] (dict)
    - Alternatif: kök seviyede anahtarlar (type, project_id, private_key_id, ...)
    """
    # 1) En sağlıklısı: [gcp_service_account] bölümünden almak
    if "gcp_service_account" in st.secrets:
        info = dict(st.secrets["gcp_service_account"])
        # Streamlit bazen SecretStr döndürebilir, stringe çevir
        info = {k: (_safe_str(v) if v is not None else v) for k, v in info.items()}
        return info

    # 2) Kökten filtrele (app_password vs karışmasın)
    allowed = {
        "type", "project_id", "private_key_id", "private_key", "client_email",
        "client_id", "auth_uri", "token_uri", "auth_provider_x509_cert_url",
        "client_x509_cert_url", "universe_domain"
    }
    info = {}
    for k in allowed:
        if k in st.secrets:
            info[k] = _safe_str(st.secrets.get(k))
    return info

@st.cache_resource(show_spinner=False)
def connect_to_gsheets() -> gspread.Client:
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    info = _get_service_account_info()

    # Kritik: type doğru mu?
    if not info or info.get("type", "") != "service_account":
        st.error(
            "⚠️ Google Service Account credentials bulunamadı veya hatalı.\n\n"
            "Secrets içinde şu yapıyı kullan:\n"
            "[gcp_service_account]\n"
            "type='service_account'\n"
            "project_id='...'\n"
            "private_key='...'\n"
            "client_email='...'\n"
            "...\n\n"
            "Ayrıca sheet_id de secrets içinde olmalı."
        )
        st.stop()

    creds = ServiceAccountCredentials.from_json_keyfile_dict(info, scope)
    return gspread.authorize(creds)

def get_ws(sheet_id: str, worksheet_index: int):
    client = connect_to_gsheets()
    sh = client.open_by_key(sheet_id)
    return sh.get_worksheet(worksheet_index)

def load_data(sheet_id: str, worksheet_index: int, required_col: Optional[str] = None) -> pd.DataFrame:
    try:
        ws = get_ws(sheet_id, worksheet_index)
        values = ws.get_all_values()
        if not values:
            return pd.DataFrame()

        headers = [str(h).strip() for h in values[0]]
        rows = values[1:]
        df = pd.DataFrame(rows, columns=headers)

        # Boş header varsa temizle
        df = df.loc[:, [c for c in df.columns if str(c).strip() != ""]]

        if required_col and required_col not in df.columns:
            return pd.DataFrame()

        return df
    except Exception:
        return pd.DataFrame()

def save_data_row(sheet_id: str, data_dict: Dict[str, Any], unique_col: str, worksheet_index: int = 0):
    ws = get_ws(sheet_id, worksheet_index)

    # hepsi string olsun (bool dahil) -> sheets uyumu
    clean = {str(k).strip(): ("" if v is None else str(v)) for k, v in data_dict.items()}
    all_values = ws.get_all_values()

    # ilk kayıt
    if not all_values:
        ws.append_row(list(clean.keys()))
        ws.append_row(list(clean.values()))
        st.toast("✅ İlk kayıt oluşturuldu.", icon="💾")
        return

    headers = [str(h).strip() for h in all_values[0]]

    # yeni kolon varsa ekle
    missing_cols = [k for k in clean.keys() if k not in headers]
    if missing_cols:
        headers.extend(missing_cols)
        ws.update("1:1", [headers])

    uid = str(clean.get(unique_col, "")).strip()
    if not uid:
        raise ValueError(f"{unique_col} boş olamaz!")

    uid_col_idx = headers.index(unique_col) + 1
    col_vals = ws.col_values(uid_col_idx)

    row_idx = None
    for i, v in enumerate(col_vals[1:], start=2):
        if str(v).strip() == uid:
            row_idx = i
            break

    row_to_save = [clean.get(h, "") for h in headers]
    end_col = colnum_to_letter(len(headers))

    if row_idx:
        ws.update(f"A{row_idx}:{end_col}{row_idx}", [row_to_save])
        st.toast(f"✅ Güncellendi: {uid}", icon="🔄")
    else:
        ws.append_row(row_to_save)
        st.toast(f"✅ Kaydedildi: {uid}", icon="💾")

def delete_row_by_value(sheet_id: str, worksheet_index: int, col_name: str, value: str) -> bool:
    try:
        ws = get_ws(sheet_id, worksheet_index)
        values = ws.get_all_values()
        if not values:
            return False

        headers = [str(h).strip() for h in values[0]]
        if col_name not in headers:
            return False

        # ilgili kolonda hızlı arama
        col_idx = headers.index(col_name) + 1
        col_vals = ws.col_values(col_idx)
        target = str(value).strip()

        for i, v in enumerate(col_vals[1:], start=2):
            if str(v).strip() == target:
                ws.delete_rows(i)
                return True

        # fallback
        cell = ws.find(target)
        ws.delete_rows(cell.row)
        return True
    except Exception:
        return False

def require_password_gate():
    if "auth_ok" not in st.session_state:
        st.session_state.auth_ok = False

    app_password = st.secrets.get("app_password", None)
    if not app_password:
        st.error('⚠️ Secrets içine app_password ekle:  app_password="...."')
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
                time.sleep(0.2)
                st.rerun()
            else:
                st.error("❌ Şifre yanlış")
    with c2:
        st.caption("Not: Bu şifre sadece veri ekranları için geçerli.")
    st.stop()

def confirm_delete_with_password(context_key: str) -> bool:
    app_password = st.secrets.get("app_password", None)
    if not app_password:
        st.error("⚠️ Secrets içinde app_password yok.")
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
                time.sleep(0.2)
                st.rerun()
            else:
                st.error("❌ Şifre yanlış")
    return False


# ===================== HEADER / EKG ANİMASYONU =====================
st.markdown(
    """
<style>
.ecg-container {
    background:#000; height:90px; width:100%; overflow:hidden; position:relative;
    border-radius:10px; border:2px solid #444; margin-bottom:18px; display:flex; align-items:center;
    box-shadow:0 0 10px rgba(0,255,0,0.2);
}
.ecg-line {
    position:absolute; top:0; left:0; width:100%; height:100%;
    background-image:url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="300" height="90" viewBox="0 0 300 90"><path d="M0 50 L20 50 L25 45 L30 50 L40 50 L42 55 L45 10 L48 85 L52 50 L60 50 L65 40 L75 40 L80 50 L300 50" stroke="%2300ff00" stroke-width="2" fill="none"/></svg>');
    background-repeat:repeat-x; animation:scroll-bg 3s linear infinite; z-index:1; opacity:0.6;
}
.ecg-text-track { display:flex; position:absolute; top:30px; left:0; white-space:nowrap;
    animation:scroll-text 12s linear infinite; z-index:2; }
.ecg-name {
    display:inline-block; width:300px;
    font-family:'Courier New', monospace; font-weight:900; font-size:20px; text-align:center;
    text-shadow:2px 2px 0px #000;
    animation:bounce 1s infinite alternate, color-shift 5s infinite linear;
}
.ecg-name:nth-child(1){ color:#FFFF00; animation-delay:0s,0s; }
.ecg-name:nth-child(2){ color:#00FFFF; animation-delay:0.2s,1s; }
.ecg-name:nth-child(3){ color:#FF00FF; animation-delay:0.4s,2s; }
.ecg-name:nth-child(4){ color:#FFA500; animation-delay:0.6s,3s; }
.ecg-name:nth-child(5){ color:#FFFF00; animation-delay:0s,0s; }
.ecg-name:nth-child(6){ color:#00FFFF; animation-delay:0.2s,1s; }
.ecg-name:nth-child(7){ color:#FF00FF; animation-delay:0.4s,2s; }
.ecg-name:nth-child(8){ color:#FFA500; animation-delay:0.6s,3s; }
@keyframes scroll-bg { 0%{ background-position:0 0; } 100%{ background-position:-300px 0; } }
@keyframes scroll-text { 0%{ transform:translateX(0); } 100%{ transform:translateX(-1200px); } }
@keyframes bounce { 0%{ transform:translateY(0); } 100%{ transform:translateY(-8px); } }
@keyframes color-shift { 0%{ filter:hue-rotate(0deg); } 100%{ filter:hue-rotate(360deg); } }
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
    st.title(APP_TITLE)

    menu = st.radio(
        "Menü",
        [
            "🏥 H-Type HT Çalışması",
            "📝 Case Report Takip",
            "✉️ Editöre Mektup",
            "🫀 Fizyolojik Pacing Çalışması",
            "🫀 AFMR – TEE LV-GLS",
            "⚡ Kardiyoversiyon-Ablasyon / TEE-GLS",
        ],
    )

    st.divider()

    quotes = [
        "Halk içinde muteber bir nesne yok devlet gibi,\nOlmaya devlet cihanda bir nefes sıhhat gibi.\n(Kanuni Sultan Süleyman)",
        "Kalp, aklın bilmediği sebeplere sahiptir.\n(Blaise Pascal)",
        "İlim ilim bilmektir, ilim kendin bilmektir.\n(Yunus Emre)",
        "Zahmetsiz rahmet olmaz.",
        "Sabır acidir, meyvesi tatlıdır.",
        "Ne doğrarsan aşına, o gelir kaşığa.",
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
            n_vaka = st.text_input("Vaka")
            n_dr = st.text_input("Sorumlu Doktor")
            n_not = st.text_area("Not")

            submitted = st.form_submit_button("Kaydet", type="primary")
            if submitted:
                try:
                    now = datetime.now()
                    payload = {
                        "Tarih": str(now.date()),
                        "TarihSaat": now.isoformat(timespec="seconds"),
                        "Dosya No": n_dosya,
                        "Vaka": n_vaka,
                        "Doktor": n_dr,
                        "Not": n_not,
                    }
                    save_data_row(SHEET_ID, payload, unique_col="TarihSaat", worksheet_index=CASE_WS_INDEX)
                    st.success("✅ Kaydedildi")
                    time.sleep(0.3)
                    st.rerun()
                except Exception as e:
                    st.error(f"Hata: {e}")

    with right:
        df = load_data(SHEET_ID, CASE_WS_INDEX, required_col="TarihSaat")
        if df.empty:
            st.info("Henüz case report kaydı yok (veya sheet yok/başlık uyumsuz).")
        else:
            q = st.text_input("🔎 Arama (dosya no / vaka / doktor / not)", "")
            show = df.copy()
            if q.strip():
                mask = show.apply(lambda r: r.astype(str).str.contains(q, case=False, na=False).any(), axis=1)
                show = show[mask].copy()

            st.dataframe(show, use_container_width=True)

            st.divider()
            st.markdown("### 🗑️ Silme (Şifreli)")
            if confirm_delete_with_password("case"):
                del_ts = st.selectbox("Silinecek kayıt (TarihSaat)", df["TarihSaat"].unique(), key="case_del_ts")
                if st.button("🗑️ Sil", key="case_del_btn", type="secondary"):
                    if delete_row_by_value(SHEET_ID, CASE_WS_INDEX, "TarihSaat", del_ts):
                        st.success("Silindi")
                        time.sleep(0.2)
                        st.rerun()
                    else:
                        st.error("Hata!")


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

            submitted = st.form_submit_button("Kaydet", type="primary")
            if submitted:
                try:
                    now = datetime.now()
                    payload = {
                        "Tarih": str(now.date()),
                        "TarihSaat": now.isoformat(timespec="seconds"),
                        "Dergi Adı": dergi,
                        "Makale İsmi": makale,
                        "Yazarlar": yazarlar,
                    }
                    save_data_row(SHEET_ID, payload, unique_col="TarihSaat", worksheet_index=LETTER_WS_INDEX)
                    st.success("✅ Kaydedildi")
                    time.sleep(0.3)
                    st.rerun()
                except Exception as e:
                    st.error(f"Hata: {e}")

    with right:
        df = load_data(SHEET_ID, LETTER_WS_INDEX, required_col="TarihSaat")
        if df.empty:
            st.info("Henüz editöre mektup kaydı yok (veya sheet yok/başlık uyumsuz).")
        else:
            q = st.text_input("🔎 Arama (dergi / makale / yazar)", "")
            show = df.copy()
            if q.strip():
                mask = show.apply(lambda r: r.astype(str).str.contains(q, case=False, na=False).any(), axis=1)
                show = show[mask].copy()

            st.dataframe(show, use_container_width=True)

            st.divider()
            st.markdown("### 🗑️ Silme (Şifreli)")
            if confirm_delete_with_password("letter"):
                del_ts = st.selectbox("Silinecek kayıt (TarihSaat)", df["TarihSaat"].unique(), key="letter_del_ts")
                if st.button("🗑️ Sil", key="letter_del_btn", type="secondary"):
                    if delete_row_by_value(SHEET_ID, LETTER_WS_INDEX, "TarihSaat", del_ts):
                        st.success("Silindi")
                        time.sleep(0.2)
                        st.rerun()
                    else:
                        st.error("Hata!")


# =========================================================
# =========== EKRAN 4: FİZYOLOJİK PACING ÇALIŞMASI =========
# =========================================================
elif menu == "🫀 Fizyolojik Pacing Çalışması":
    require_password_gate()

    st.header("🫀 Fizyolojik Pacing (LBBAP / HBP) Çalışması")
    st.caption("AV blok nedeniyle fizyolojik pacing yapılan hastalarda klinik + RV parametreleri.")

    dfp = load_data(SHEET_ID, PACED_WS_INDEX, required_col="KayıtID")

    col_left, col_right = st.columns([2, 3])

    # ---- edit seçimi ----
    with col_left:
        st.markdown("##### ⚙️ İşlem Seçimi")
        mode = st.radio("Mod:", ["Yeni Kayıt", "Düzenleme"], horizontal=True, label_visibility="collapsed", key="pacing_mode")

        current = {}
        if mode == "Düzenleme" and not dfp.empty and "KayıtID" in dfp.columns:
            edit_key = st.selectbox("Düzenlenecek KayıtID", dfp["KayıtID"].unique(), key="pacing_edit_key")
            if edit_key:
                current = dfp[dfp["KayıtID"] == edit_key].iloc[0].to_dict()
                st.success(f"Seçildi: {current.get('Dosya Numarası','')} | {current.get('Ziyaret','')}")
        elif mode == "Düzenleme":
            st.warning("Düzenlenecek kayıt yok.")

    # ---- liste/arama/silme ----
    with col_right:
        with st.expander("📋 KAYITLI LİSTE / ARAMA / SİLME", expanded=True):
            if st.button("🔄 Listeyi Yenile", key="pacing_refresh"):
                st.rerun()

            if dfp.empty:
                st.info("Kayıt yok (veya sheet yok/başlık uyumsuz).")
            else:
                q = st.text_input("🔎 Arama (dosya no / hekim / ziyaret)", "", key="pacing_search")
                show = dfp.copy()
                if q.strip():
                    mask = show.apply(lambda r: r.astype(str).str.contains(q, case=False, na=False).any(), axis=1)
                    show = show[mask].copy()

                cols_show = [c for c in ["KayıtID", "Dosya Numarası", "Ziyaret", "Tarih", "Hekim", "Pacing Tipi"] if c in show.columns]
                st.dataframe(show[cols_show] if cols_show else show, use_container_width=True)

                st.divider()
                st.markdown("##### 🗑️ Silme (Şifreli)")
                if confirm_delete_with_password("pacing"):
                    del_key = st.selectbox("Silinecek KayıtID", dfp["KayıtID"].unique(), key="pacing_del_key")
                    if st.button("🗑️ SİL", type="secondary", key="pacing_del_btn"):
                        if delete_row_by_value(SHEET_ID, PACED_WS_INDEX, "KayıtID", del_key):
                            st.success("Silindi!")
                            time.sleep(0.2)
                            st.rerun()
                        else:
                            st.error("Hata!")

    st.divider()

    # ---- form helpers ----
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

            try:
                d_date = datetime.strptime(gs("Tarih"), "%Y-%m-%d").date()
            except:
                d_date = datetime.now().date()
            basvuru = st.date_input("Başvuru Tarihi", value=d_date)

            hekim = st.text_input("Veriyi Giren Hekim (Zorunlu)", value=gs("Hekim"))
            iletisim = st.text_input("İletişim", value=gs("İletişim"))

            pacing_tipi_l = ["LBBAP", "HBP", "Diğer"]
            pt = gs("Pacing Tipi")
            pacing_tipi = st.selectbox("Pacing Tipi", pacing_tipi_l, index=(pacing_tipi_l.index(pt) if pt in pacing_tipi_l else 0))

            st.markdown("##### Pacing Endikasyonu")
            av_tam = st.checkbox("AV Tam Blok", value=gc("Pacing Endikasyonu: AV Tam Blok"))
            av_2 = st.checkbox("2. Derece AV Blok", value=gc("Pacing Endikasyonu: 2. Derece AV Blok"))

        with c2:
            cy, cc = st.columns(2)
            yas = cy.number_input("Yaş", step=1, value=gi("Yaş"))

            sex_l = ["Erkek", "Kadın"]
            s_ix = sex_l.index(gs("Cinsiyet")) if gs("Cinsiyet") in sex_l else 0
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
        l1, l2, l3 = st.columns(3)
        hgb = l1.number_input("Hgb (g/dL)", value=gf("Hgb"))
        wbc = l1.number_input("WBC (10³/µL)", value=gf("WBC"))
        plt = l1.number_input("PLT (10³/µL)", value=gf("PLT"))
        krea = l2.number_input("Kreatinin (mg/dL)", value=gf("Kreatinin"))
        na = l2.number_input("Na (mEq/L)", value=gf("Na"))
        k_val = l2.number_input("K (mEq/L)", value=gf("K"))
        ntprobnp = l3.number_input("NT-proBNP (pg/mL)", value=gf("NT-proBNP"))
        hs_trop = l3.number_input("hs-Troponin (ng/L)", value=gf("hs-Troponin"))

        st.markdown("### 🫀 Eko / STE — RV (Sadece)")
        r1, r2, r3, r4 = st.columns(4)

        rv_fwls = r1.number_input("RV FWLS (%)", value=gf("RV FWLS (%)"))
        endogls = r1.number_input("EndoGLS (%)", value=gf("EndoGLS (%)"))
        myogls = r1.number_input("MyoGLS (%)", value=gf("MyoGLS (%)"))

        eda = r2.number_input("EDA", value=gf("EDA"))
        esa = r2.number_input("ESA", value=gf("ESA"))
        rv_fac = r2.number_input("RV FAC (%)", value=gf("RV FAC (%)"))

        rv_grs = r3.number_input("RV GRS (%)", value=gf("RV GRS (%)"))
        tyvel = r3.number_input("TY vel. (m/sn)", value=gf("TY vel. (m/sn)"))

        rvsm = r4.number_input("RV Sm (cm/sn)", value=gf("RV Sm (cm/sn)"))
        tapse = r4.number_input("TAPSE (mm)", value=gf("TAPSE (mm)"))

        st.write("")
        submitted = st.form_submit_button("💾 KAYDET / GÜNCELLE", type="primary")
        if submitted:
            if not dosya_no or not hekim:
                st.error("Dosya No ve Hekim zorunlu!")
            else:
                final_data = {
                    "KayıtID": kayit_id,
                    "Dosya Numarası": dosya_no,
                    "Ziyaret": ziyaret,
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
                    "WBC": wbc,
                    "PLT": plt,
                    "Kreatinin": krea,
                    "Na": na,
                    "K": k_val,
                    "NT-proBNP": ntprobnp,
                    "hs-Troponin": hs_trop,

                    # RV only
                    "RV FWLS (%)": rv_fwls,
                    "EndoGLS (%)": endogls,
                    "MyoGLS (%)": myogls,
                    "EDA": eda,
                    "ESA": esa,
                    "RV FAC (%)": rv_fac,
                    "RV GRS (%)": rv_grs,
                    "TY vel. (m/sn)": tyvel,
                    "RV Sm (cm/sn)": rvsm,
                    "TAPSE (mm)": tapse,
                }

                save_data_row(SHEET_ID, final_data, unique_col="KayıtID", worksheet_index=PACED_WS_INDEX)
                st.success(f"✅ {kayit_id} kaydedildi / güncellendi!")
                time.sleep(0.25)
                st.rerun()


# =========================================================
# ===================== EKRAN 5: AFMR – TEE LV-GLS =====================
# =========================================================
elif menu == "🫀 AFMR – TEE LV-GLS":
    require_password_gate()

    st.header("🫀 AFMR – TEE ile LV-GLS (TTE ile karşılaştırma)")
    st.caption("AFMR: TEE-LVGLS ↔ TTE-LVGLS uyumu, MR şiddeti ayrımı, AF vs SR alt grupları.")

    dfa = load_data(SHEET_ID, AFMR_WS_INDEX, required_col="KayıtID")

    left, right = st.columns([2, 3])

    with left:
        st.markdown("##### ⚙️ İşlem Seçimi")
        mode = st.radio("Mod:", ["Yeni Kayıt", "Düzenleme"], horizontal=True, label_visibility="collapsed", key="afmr_mode")

        current = {}
        if mode == "Düzenleme" and not dfa.empty and "KayıtID" in dfa.columns:
            edit_key = st.selectbox("Düzenlenecek kayıt (KayıtID):", dfa["KayıtID"].unique(), key="afmr_edit_key")
            if edit_key:
                current = dfa[dfa["KayıtID"] == edit_key].iloc[0].to_dict()
                st.success(f"Seçildi: {current.get('Dosya No','')} | {current.get('Ziyaret','')} | {current.get('Ritim','')}")
        elif mode == "Düzenleme":
            st.warning("Düzenlenecek kayıt yok (veya sheet boş).")

    with right:
        with st.expander("📋 Kayıtlı Liste / Arama / Silme", expanded=True):
            if st.button("🔄 Listeyi Yenile", key="afmr_refresh"):
                st.rerun()

            if dfa.empty:
                st.info("Kayıt yok (veya AFMR sheet index yanlış / başlıklar oluşmadı). İlk kaydı girince başlıklar otomatik oluşur.")
            else:
                q = st.text_input("🔎 Arama (dosya no / hekim / ritim)", "", key="afmr_search")
                show = dfa.copy()
                if q.strip():
                    mask = show.apply(lambda r: r.astype(str).str.contains(q, case=False, na=False).any(), axis=1)
                    show = show[mask].copy()

                cols_show = [c for c in ["KayıtID", "Dosya No", "Tarih", "Ziyaret", "Ritim", "Hekim", "MR (TEE) Derece"] if c in show.columns]
                st.dataframe(show[cols_show] if cols_show else show, use_container_width=True)

                st.divider()
                st.markdown("##### 🗑️ Silme (Şifreli)")
                if confirm_delete_with_password("afmr"):
                    del_key = st.selectbox("Silinecek KayıtID", dfa["KayıtID"].unique(), key="afmr_del_key")
                    if st.button("🗑️ SİL", type="secondary", key="afmr_del_btn"):
                        if delete_row_by_value(SHEET_ID, AFMR_WS_INDEX, "KayıtID", del_key):
                            st.success("Silindi!")
                            time.sleep(0.2)
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
        st.markdown("### 👤 Demografi ve Klinik")
        c1, c2 = st.columns(2)

        with c1:
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

            hekim = st.text_input("Hekim (Zorunlu)", value=gs("Hekim"))
            yas = st.number_input("Yaş", step=1, value=gi("Yaş"))
            cinsiyet = st.radio("Cinsiyet", ["Kadın", "Erkek"], index=(0 if gs("Cinsiyet") != "Erkek" else 1), horizontal=True)

            ritim = st.radio("Ritim grubu", ["AF", "SR"], index=(0 if gs("Ritim") != "SR" else 1), horizontal=True)

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
        med_diger = st.text_input("Diğer (tedavi)", value=gs("Tedavi: Diğer"))

        st.markdown("### 🩸 Laboratuvar (opsiyonel)")
        l1, l2, l3 = st.columns(3)

        lab_hb = l1.number_input("Hb (g/dL)", value=gf("Hb"))
        lab_krea = l1.number_input("Kreatinin (mg/dL)", value=gf("Kreatinin"))
        lab_egfr = l1.number_input("eGFR (mL/dk/1.73m²)", value=gf("eGFR"))
        
        lab_ntprobnp = l2.number_input("NT-proBNP", value=gf("NT-proBNP"))

        st.markdown("### 🧠 Sedasyon / Hemodinami")
        h1, h2, h3 = st.columns(3)

        sed_ilac = h1.text_input("Sedasyon ilacı", value=(gs("Sedasyon ilacı") if gs("Sedasyon ilacı") else "Midazolam"))
        sed_doz = h1.number_input("Doz (mg)", value=gf("Sedasyon doz (mg)"))

        # Uygulama saati KALDIRILDI ✅
        # BP/HR alanları numeric + clamp (0 gelirse min'e çek)
        pre_sbp = int(_clamp_number(gi("TEE öncesi SBP"), min_v=50, max_v=260, default=120))
        pre_dbp = int(_clamp_number(gi("TEE öncesi DBP"), min_v=30, max_v=160, default=70))
        pre_hr  = int(_clamp_number(gi("TEE öncesi HR"),  min_v=20, max_v=220, default=80))

        tee_sbp = int(_clamp_number(gi("TEE sırasında SBP"), min_v=50, max_v=260, default=120))
        tee_dbp = int(_clamp_number(gi("TEE sırasında DBP"), min_v=30, max_v=160, default=70))
        tee_hr  = int(_clamp_number(gi("TEE sırasında HR"),  min_v=20, max_v=220, default=80))

        pre_sbp_in = h2.number_input("TEE öncesi SBP (mmHg)", min_value=50, max_value=260, step=1, value=pre_sbp)
        pre_dbp_in = h2.number_input("TEE öncesi DBP (mmHg)", min_value=30, max_value=160, step=1, value=pre_dbp)
        pre_hr_in  = h2.number_input("TEE öncesi HR (bpm)",   min_value=20, max_value=220, step=1, value=pre_hr)

        tee_sbp_in = h3.number_input("TEE sırasında SBP (mmHg)", min_value=50, max_value=260, step=1, value=tee_sbp)
        tee_dbp_in = h3.number_input("TEE sırasında DBP (mmHg)", min_value=30, max_value=160, step=1, value=tee_dbp)
        tee_hr_in  = h3.number_input("TEE sırasında HR (bpm)",   min_value=20, max_value=220, step=1, value=tee_hr)

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
                               index=(["S baskın","D baskın","Sistolik reversiyon"].index(gs("PV akım"))
                                      if gs("PV akım") in ["S baskın","D baskın","Sistolik reversiyon"] else 0))
        pv_sd = m3.number_input("PV S/D oranı", value=gf("PV S/D"))

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
        lvedv = s2.number_input("LVEDV (mL)", value=gf("TEE LVEDV"))
        lvesv = s2.number_input("LVESV (mL)", value=gf("TEE LVESV"))
        sv = s2.number_input("SV (mL)", value=gf("TEE SV"))
        tee_gls = s3.number_input("LV-GLS (TEE) (%)", value=gf("TEE LVGLS"))
        fr = s3.number_input("Frame rate (fps)", value=gf("Frame rate"))

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
        submitted = st.form_submit_button("💾 KAYDET / GÜNCELLE", type="primary")
        if submitted:
            if not dosya_no or not hekim:
                st.error("Dosya No ve Hekim zorunlu!")
            else:
                payload = {
                    "KayıtID": kayit_id,
                    "Dosya No": dosya_no,
                    "Tarih": str(tarih),
                    "Ziyaret": ziyaret,
                    "Hekim": hekim,

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
                    "Tedavi: Diğer": med_diger,

                    "Hb": lab_hb,
                    "Kreatinin": lab_krea,
                    "eGFR": lab_egfr,
                    "NT-proBNP": lab_ntprobnp,

                    "Sedasyon ilacı": sed_ilac,
                    "Sedasyon doz (mg)": sed_doz,

                    "TEE öncesi SBP": pre_sbp_in,
                    "TEE öncesi DBP": pre_dbp_in,
                    "TEE öncesi HR": pre_hr_in,

                    "TEE sırasında SBP": tee_sbp_in,
                    "TEE sırasında DBP": tee_dbp_in,
                    "TEE sırasında HR": tee_hr_in,

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
                    "TEE LVEDV": lvedv,
                    "TEE LVESV": lvesv,
                    "TEE SV": sv,
                    "TEE LVGLS": tee_gls,
                    "Frame rate": fr,

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

                save_data_row(SHEET_ID, payload, unique_col="KayıtID", worksheet_index=AFMR_WS_INDEX)
                st.success(f"✅ Kaydedildi/Güncellendi: {kayit_id}")
                time.sleep(0.25)
                st.rerun()

# =========================================================
# ====== EKRAN X: Kardiyoversiyon-Ablasyon / TEE-GLS =======
# =========================================================
elif menu == "⚡ Kardiyoversiyon-Ablasyon / TEE-GLS":
    require_password_gate()

    st.header("⚡ Kardiyoversiyon-Ablasyon / TEE-GLS")
    st.caption("AF hastalarında TEE ile LV-GLS, kardiyoversiyon veya ablasyon başarısını öngörür mü? (TTE karşılaştırma dahil)")

    dfc = load_data(SHEET_ID, CVABL_WS_INDEX, required_col="KayıtID")

    left, right = st.columns([2, 3])

    # ---- edit seçimi ----
    with left:
        st.markdown("##### ⚙️ İşlem Seçimi")
        mode = st.radio(
            "Mod:",
            ["Yeni Kayıt", "Düzenleme"],
            horizontal=True,
            label_visibility="collapsed",
            key="cvabl_mode",
        )

        current = {}
        if mode == "Düzenleme" and not dfc.empty and "KayıtID" in dfc.columns:
            edit_key = st.selectbox("Düzenlenecek kayıt (KayıtID):", dfc["KayıtID"].unique(), key="cvabl_edit_key")
            if edit_key:
                current = dfc[dfc["KayıtID"] == edit_key].iloc[0].to_dict()
                st.success(f"Seçildi: {current.get('Dosya No','')} | {current.get('Ziyaret','')} | {current.get('İşlem','')}")
        elif mode == "Düzenleme":
            st.warning("Düzenlenecek kayıt yok (veya sheet boş).")

    # ---- liste/arama/silme ----
    with right:
        with st.expander("📋 Kayıtlı Liste / Arama / Silme", expanded=True):
            if st.button("🔄 Listeyi Yenile", key="cvabl_refresh"):
                st.rerun()

            if dfc.empty:
                st.info("Kayıt yok (veya sheet index yanlış / başlıklar oluşmadı). İlk kaydı girince başlıklar otomatik oluşur.")
            else:
                q = st.text_input("🔎 Arama (dosya no / hekim / işlem)", "", key="cvabl_search")
                show = dfc.copy()
                if q.strip():
                    mask = show.apply(lambda r: r.astype(str).str.contains(q, case=False, na=False).any(), axis=1)
                    show = show[mask].copy()

                cols_show = [c for c in [
                    "KayıtID", "Dosya No", "Tarih", "Ziyaret", "İşlem", "Hekim",
                    "Primary endpoint", "Endpoint başarılı"
                ] if c in show.columns]
                st.dataframe(show[cols_show] if cols_show else show, use_container_width=True)

                st.divider()
                st.markdown("##### 🗑️ Silme (Şifreli)")
                if confirm_delete_with_password("cvabl"):
                    del_key = st.selectbox("Silinecek KayıtID", dfc["KayıtID"].unique(), key="cvabl_del_key")
                    if st.button("🗑️ SİL", type="secondary", key="cvabl_del_btn"):
                        if delete_row_by_value(SHEET_ID, CVABL_WS_INDEX, "KayıtID", del_key):
                            st.success("Silindi!")
                            time.sleep(0.2)
                            st.rerun()
                        else:
                            st.error("Hata!")

    st.divider()

    # ---- helpers ----
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

    with st.form("cvabl_form"):
        # ===================== DEMOGRAFİ / KLİNİK =====================
        st.markdown("### 👤 Demografi ve Klinik (AF hasta)")
        c1, c2 = st.columns(2)

        with c1:
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

            hekim = st.text_input("Hekim (Zorunlu)", value=gs("Hekim"))
            iletisim_no = st.text_input("İletişim No", value=gs("İletişim No"))
            yas = st.number_input("Yaş", step=1, value=gi("Yaş"))
            cinsiyet = st.radio("Cinsiyet", ["Kadın", "Erkek"], index=(0 if gs("Cinsiyet") != "Erkek" else 1), horizontal=True)

        with c2:
            boy = st.number_input("Boy (cm)", value=gf("Boy"))
            kilo = st.number_input("Kilo (kg)", value=gf("Kilo"))
            bmi = kilo / ((boy / 100) ** 2) if boy > 0 else 0
            bsa = (boy * kilo / 3600) ** 0.5 if (boy > 0 and kilo > 0) else 0
            st.metric("BMI", f"{bmi:.1f}")
            st.metric("BSA", f"{bsa:.2f}")

            nyha = st.selectbox(
                "NYHA",
                ["I", "II", "III", "IV"],
                index=(["I","II","III","IV"].index(gs("NYHA")) if gs("NYHA") in ["I","II","III","IV"] else 0)
            )

            st.markdown("##### Semptomlar")
            s1, s2, s3, s4 = st.columns(4)
            sym_dispne = s1.checkbox("Dispne", value=gc("Semptom: Dispne"))
            sym_carpinti = s2.checkbox("Çarpıntı", value=gc("Semptom: Çarpıntı"))
            sym_yorgunluk = s3.checkbox("Yorgunluk", value=gc("Semptom: Yorgunluk"))
            sym_diger = s4.text_input("Diğer", value=gs("Semptom: Diğer"))

        # ===================== İŞLEM =====================
        st.markdown("### ⚙️ İşlem Bilgisi")
        p1, p2, p3 = st.columns(3)

        islem_l = ["Elektrik Kardiyoversiyon", "Ablasyon"]
        islem_prev = gs("İşlem")
        islem_ix = islem_l.index(islem_prev) if islem_prev in islem_l else 0
        islem = p1.selectbox("İşlem", islem_l, index=islem_ix)

        try:
            d_proc = datetime.strptime(gs("İşlem Tarihi"), "%Y-%m-%d").date()
        except:
            d_proc = tarih
        islem_tarih = p2.date_input("İşlem Tarihi", value=d_proc)

        abl_tip = ""
        if islem == "Ablasyon":
            abl_l = ["PVI", "PVI + Ek lezyon", "Diğer"]
            abl_prev = gs("Ablasyon tipi")
            abl_ix = abl_l.index(abl_prev) if abl_prev in abl_l else 0
            abl_tip = p3.selectbox("Ablasyon tipi (ops.)", abl_l, index=abl_ix)
        else:
            abl_tip = ""

        # ===================== ENDPOINT (2 TANE) =====================
        st.markdown("### ✅ Endpoint (basit, literatüre uygun)")

        if islem == "Ablasyon":
            primary_endpoint = "Ablasyon başarısı: 3 ay blanking sonrası atriyal taşiaritmi rekürrensi yok (AF/AFL/AT)"
            cA1, cA2, cA3 = st.columns(3)

            rec_post_blanking = cA1.checkbox(
                "Blanking sonrası rekürrens var (AF/AFL/AT)",
                value=gc("Rekürrens (blanking sonrası)")
            )

            fu_months = cA2.number_input(
                "Takip süresi (ay)",
                min_value=0,
                max_value=60,
                step=1,
                value=gi("Takip süresi (ay)")
            )

            try:
                d_eval = datetime.strptime(gs("Endpoint değerlendirme tarihi"), "%Y-%m-%d").date()
            except:
                d_eval = datetime.now().date()
            eval_date = cA3.date_input("Endpoint değerlendirme tarihi (ops.)", value=d_eval)

            endpoint_success = (not bool(rec_post_blanking))

            # CV alanları
            early_sr = ""
            rec_30d = ""

        else:
            primary_endpoint = "Kardiyoversiyon başarısı: 30 gün içinde AF rekürrensi yok"
            cC1, cC2, cC3 = st.columns(3)

            early_sr = cC1.checkbox(
                "Erken başarı: SR sağlandı (işlem sonrası)",
                value=gc("Başarı (erken)")
            )

            rec_30d = cC2.checkbox(
                "AF rekürrensi 30 gün içinde",
                value=gc("Rekürrens (30 gün)")
            )

            try:
                d_eval = datetime.strptime(gs("Endpoint değerlendirme tarihi"), "%Y-%m-%d").date()
            except:
                d_eval = datetime.now().date()
            eval_date = cC3.date_input("Endpoint değerlendirme tarihi (ops.)", value=d_eval)

            endpoint_success = (not bool(rec_30d))

            # Ablasyon alanları
            fu_months = 0
            rec_post_blanking = False

        sonuc_not = st.text_input("Sonuç notu (ops.)", value=gs("Sonuç notu"))
        st.info(f"📌 Primary endpoint: {primary_endpoint}\n\n📌 Endpoint sonucu: {'BAŞARILI' if endpoint_success else 'BAŞARISIZ'}")

        # ===================== TIBBİ ÖYKÜ =====================
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

        # ===================== TEDAVİ =====================
        st.markdown("### 💊 Güncel Tedavi")
        t1, t2, t3 = st.columns(3)
        med_bb = t1.checkbox("Beta bloker", value=gc("Tedavi: BB"))
        med_ace = t1.checkbox("ACEi/ARB/ARNI", value=gc("Tedavi: ACEi/ARB/ARNI"))
        med_mra = t2.checkbox("MRA", value=gc("Tedavi: MRA"))
        med_sglt2 = t2.checkbox("SGLT2 inhibitörü", value=gc("Tedavi: SGLT2"))
        med_diur = t3.checkbox("Diüretik", value=gc("Tedavi: Diüretik"))
        med_antitrom = t3.checkbox("Antikoagülan/Antiplatelet", value=gc("Tedavi: Antitrombotik"))
        med_diger = st.text_input("Diğer (tedavi)", value=gs("Tedavi: Diğer"))

        # ===================== LAB =====================
        st.markdown("### 🩸 Laboratuvar (opsiyonel)")
        l1, l2, l3 = st.columns(3)
        lab_hb = l1.number_input("Hb (g/dL)", value=gf("Hb"))
        lab_krea = l1.number_input("Kreatinin (mg/dL)", value=gf("Kreatinin"))
        lab_egfr = l1.number_input("eGFR (mL/dk/1.73m²)", value=gf("eGFR"))
        lab_ntprobnp = l2.number_input("NT-proBNP", value=gf("NT-proBNP"))

        # ===================== TEE =====================
        # Sadece GLS (TEE'de bu çalışmada LV volüm/EF alınmıyor)
        st.markdown("### 🫀 TEE – LV-GLS (Ana değişken)")
        s1= st.columns(1)
        tee_gls = s1.number_input("LV-GLS (TEE) (%)", value=gf("TEE LVGLS"))

        # ===================== TTE (İSTEDİĞİN PARAMETRELER) =====================
        st.markdown("### 🫁 TTE – Karşılaştırma (yeterli set)")
        t1, t2, t3 = st.columns(3)
        tte_lvef = t1.number_input("LVEF (TTE) (%)", value=gf("TTE LVEF"))
        tte_sv = t1.number_input("SV (TTE) (mL)", value=gf("TTE SV"))

        tte_lvedv = t2.number_input("LVEDV (TTE) (mL)", value=gf("TTE LVEDV"))
        tte_lvesv = t2.number_input("LVESV (TTE) (mL)", value=gf("TTE LVESV"))

        tte_laesv = t3.number_input("LAESV (TTE) (mL)", value=gf("TTE LAESV"))
        tte_gls = t3.number_input("LV-GLS (TTE) (%)", value=gf("TTE LVGLS"))

        # ===================== SAVE =====================
        st.write("")
        submitted = st.form_submit_button("💾 KAYDET / GÜNCELLE", type="primary")

        if submitted:
            if not dosya_no or not hekim:
                st.error("Dosya No ve Hekim zorunlu!")
            else:
                payload = {
                    "KayıtID": kayit_id,
                    "Dosya No": dosya_no,
                    "Tarih": str(tarih),
                    "Ziyaret": ziyaret,
                    "Hekim": hekim,
                    "İletişim No": iletisim_no,

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

                    "İşlem": islem,
                    "İşlem Tarihi": str(islem_tarih),
                    "Ablasyon tipi": abl_tip,

                    "Primary endpoint": primary_endpoint,
                    "Endpoint başarılı": endpoint_success,
                    "Endpoint değerlendirme tarihi": str(eval_date),

                    # Ablasyon endpoint alanları
                    "Rekürrens (blanking sonrası)": rec_post_blanking,
                    "Takip süresi (ay)": fu_months,

                    # Kardiyoversiyon endpoint alanları
                    "Başarı (erken)": (early_sr if islem == "Elektrik Kardiyoversiyon" else ""),
                    "Rekürrens (30 gün)": (rec_30d if islem == "Elektrik Kardiyoversiyon" else ""),

                    "Sonuç notu": sonuc_not,

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
                    "Tedavi: Diğer": med_diger,

                    "Hb": lab_hb,
                    "Kreatinin": lab_krea,
                    "eGFR": lab_egfr,
                    "NT-proBNP": lab_ntprobnp,

                    # TEE (sadece GLS)
                    "TEE LVGLS": tee_gls,

                    # TTE (sadece istediğin set)
                    "TTE LVEF": tte_lvef,
                    "TTE LVEDV": tte_lvedv,
                    "TTE LVESV": tte_lvesv,
                    "TTE LAESV": tte_laesv,
                    "TTE LVGLS": tte_gls,
                    "TTE SV": tte_sv,
                }

                save_data_row(SHEET_ID, payload, unique_col="KayıtID", worksheet_index=CVABL_WS_INDEX)
                st.success(f"✅ Kaydedildi/Güncellendi: {kayit_id}")
                time.sleep(0.25)
                st.rerun()
                
# =========================================================
# ===================== EKRAN 1: H-TYPE HT =====================
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
        if mode == "Düzenleme" and not df.empty:
            edit_id = st.selectbox("Düzenlenecek Hasta (Dosya No):", df["Dosya Numarası"].unique(), key="htype_edit_id")
            if edit_id:
                current = df[df["Dosya Numarası"] == edit_id].iloc[0].to_dict()
                st.success(f"Seçildi: {current.get('Adı Soyadı', '')}")
        elif mode == "Düzenleme":
            st.warning("Düzenlenecek kayıt yok.")

    with col_right:
        with st.expander("📋 KAYITLI HASTA LİSTESİ / ARAMA / SİLME", expanded=True):
            if st.button("🔄 Listeyi Yenile", key="htype_refresh"):
                st.rerun()

            if df.empty:
                st.info("Kayıt yok.")
            else:
                q = st.text_input("🔎 Arama (dosya no / hekim)", "", key="htype_search")
                show = df.copy()
                if q.strip():
                    mask = show.apply(lambda r: r.astype(str).str.contains(q, case=False, na=False).any(), axis=1)
                    show = show[mask].copy()

                st.dataframe(show, use_container_width=True)

                st.divider()
                st.markdown("##### 🗑️ Silme")
                del_id = st.selectbox("Silinecek Dosya No", df["Dosya Numarası"].unique(), key="data_del_id")
                if st.button("🗑️ SİL", type="secondary", key="data_del_btn"):
                    if delete_row_by_value(SHEET_ID, DATA_WS_INDEX, "Dosya Numarası", del_id):
                        st.success("Silindi!")
                        time.sleep(0.2)
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
            s_ix = sex_l.index(gs("Cinsiyet")) if gs("Cinsiyet") in sex_l else 0
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
        ekg = st.selectbox("EKG", ekg_l, index=(ekg_l.index(gs("EKG")) if gs("EKG") in ekg_l else 0))

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

        with e4:
            st.caption("Sağ Kalp")
            tapse = st.number_input("TAPSE (mm)", value=gf("TAPSE"))
            rvsm = st.number_input("RV Sm (cm/sn)", value=gf("RV Sm"))
            spap = st.number_input("sPAP (mmHg)", value=gf("sPAP"))
            tyvel = st.number_input("TY vel. (m/sn)", value=gf("TY vel."))
            rvot = st.number_input("RVOT VTI (cm)", value=gf("RVOT VTI"))
            rvota = st.number_input("RVOT accT (ms)", value=gf("RVOT accT"))

        st.write("")
        submitted = st.form_submit_button("💾 KAYDET / GÜNCELLE", type="primary")
        if submitted:
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
                    "Ao Asc": ao,
                    "LVEF": lvef,
                    "SV": sv,
                    "LVOT VTI": lvot,
                    "GLS": gls,
                    "GCS": gcs,
                    "SD-LS": sdls,
                    "Mitral E": mite,
                    "Mitral A": mita,
                    "Septal e'": septe,
                    "Lateral e'": late,
                    "LAEDV": laedv,
                    "LAESV": laesv,
                    "LA Strain": lastr,
                    "TAPSE": tapse,
                    "RV Sm": rvsm,
                    "sPAP": spap,
                    "TY vel.": tyvel,
                    "RVOT VTI": rvot,
                    "RVOT accT": rvota,
                }
                save_data_row(SHEET_ID, final_data, unique_col="Dosya Numarası", worksheet_index=DATA_WS_INDEX)
                st.success(f"✅ {dosya_no} kaydedildi / güncellendi!")
                time.sleep(0.25)
                st.rerun()


# =========================================================
# ===================== FALLBACK ==========================
# =========================================================
else:
    st.warning("Menü seçimi tanınmadı.")
