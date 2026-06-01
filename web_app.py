# web_app.py
# NEÜ-KARDİYO | Streamlit + Google Sheets (CRUD)
# Not: Excel/CSV indirme YOK (isteğe göre kaldırıldı)

import time
import random
import textwrap
from datetime import datetime
from typing import Dict, Any, Optional

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import gspread
from oauth2client.service_account import ServiceAccountCredentials


# ===================== AYARLAR =====================
st.set_page_config(page_title="NEÜ-KARDİYO", page_icon="❤️", layout="wide")

# Tek bir Google Sheet içinde sekmeler:
SHEET_ID = "1_Jd27n2lvYRl-oKmMOVySd5rGvXLrflDCQJeD_Yz6Y4"
DATA_WS_INDEX = int(st.secrets.get("data_ws_index", 0))         # H-Type HT
CASE_WS_INDEX = int(st.secrets.get("case_ws_index", 1))         # Case Report
LETTER_WS_INDEX = int(st.secrets.get("letter_ws_index", 2))     # Editöre mektup
PACED_WS_INDEX = int(st.secrets.get("paced_ws_index", 3))       # Fizyolojik pacing
AFMR_WS_INDEX = int(st.secrets.get("afmr_ws_index", 4))         # AFMR
CVABL_WS_INDEX = int(st.secrets.get("cvabl_ws_index", 5))       # Kardiyoversiyon-Ablasyon / TEE-GLS
PBMV_WS_INDEX = int(st.secrets.get("pbmv_ws_index", 7))         # PBMV – RV-PA Coupling
FEATURED_WS_INDEX = int(st.secrets.get("featured_ws_index", 6)) # Özellikli Vakalar
QUESTION_WS_INDEX = int(st.secrets.get("question_ws_index", 8)) # Soru Bankası

APP_TITLE = "❤️ NEÜ-KARDİYO"


# ===================== HELPERS =====================
def _safe_str(x) -> str:
    if x is None:
        return ""
    return str(x)
def mask_name(name: str) -> str:
    name = _safe_str(name).strip()
    if not name:
        return ""

    parts = name.split()
    masked_parts = []

    for part in parts:
        if len(part) <= 1:
            masked_parts.append(part)
        else:
            masked_parts.append(part[0] + "*" * (len(part) - 1))

    return " ".join(masked_parts)


def mask_phone(phone: str) -> str:
    phone = _safe_str(phone).strip()
    if not phone:
        return ""

    digits = [c for c in phone if c.isdigit()]
    total_digits = len(digits)

    if total_digits == 0:
        return phone

    visible_prefix = 3
    visible_suffix = 2

    if total_digits <= visible_prefix + visible_suffix:
        return "*" * total_digits

    masked = []
    digit_index = 0

    for ch in phone:
        if ch.isdigit():
            digit_index += 1
            if digit_index <= visible_prefix or digit_index > total_digits - visible_suffix:
                masked.append(ch)
            else:
                masked.append("*")
        else:
            masked.append(ch)

    return "".join(masked)
    
def _clamp_number(value, min_v=None, max_v=None, default=None):
    """Streamlit number_input min/max hatasını engellemek için."""
    try:
        v = float(value)
    except Exception:
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
    if "gcp_service_account" in st.secrets:
        info = dict(st.secrets["gcp_service_account"])
        info = {k: (_safe_str(v) if v is not None else v) for k, v in info.items()}
        return info

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
        df = df.loc[:, [c for c in df.columns if str(c).strip() != ""]]

        if required_col and required_col not in df.columns:
            return pd.DataFrame()

        return df
    except Exception:
        return pd.DataFrame()


def save_data_row(sheet_id: str, data_dict: Dict[str, Any], unique_col: str, worksheet_index: int = 0):
    ws = get_ws(sheet_id, worksheet_index)
    clean = {str(k).strip(): ("" if v is None else str(v)) for k, v in data_dict.items()}
    all_values = ws.get_all_values()

    if not all_values:
        ws.append_row(list(clean.keys()))
        ws.append_row(list(clean.values()))
        st.toast("✅ İlk kayıt oluşturuldu.", icon="💾")
        return

    headers = [str(h).strip() for h in all_values[0]]

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

        col_idx = headers.index(col_name) + 1
        col_vals = ws.col_values(col_idx)
        target = str(value).strip()

        for i, v in enumerate(col_vals[1:], start=2):
            if str(v).strip() == target:
                ws.delete_rows(i)
                return True

        cell = ws.find(target)
        ws.delete_rows(cell.row)
        return True
    except Exception:
        return False




def flag_question_for_review(
    sheet_id: str,
    worksheet_index: int,
    soru_id: str,
    soru_text: str = "",
    flag_col: str = "Soru Düzelt",
) -> bool:
    """
    Soru Bankası'nda ilgili soru satırının sonuna uyarı koyar.
    Kolon yoksa en sona 'Soru Düzelt' kolonunu ekler.
    Aynı SoruID tekrar ederse, mümkünse Soru metniyle eşleşeni işaretler.
    """
    try:
        ws = get_ws(sheet_id, worksheet_index)
        values = ws.get_all_values()
        if not values:
            return False

        headers = [str(h).strip() for h in values[0]]

        if "SoruID" not in headers:
            return False

        # Uyarı kolonu yoksa en sona ekle
        if flag_col not in headers:
            headers.append(flag_col)
            ws.update("1:1", [headers])

        values = ws.get_all_values()
        headers = [str(h).strip() for h in values[0]]

        soru_id_col = headers.index("SoruID") + 1
        flag_col_idx = headers.index(flag_col) + 1
        soru_col_idx = headers.index("Soru") + 1 if "Soru" in headers else None

        target_id = str(soru_id).strip()
        target_soru = str(soru_text).strip()

        candidate_rows = []
        for row_idx, row in enumerate(values[1:], start=2):
            row_soru_id = str(row[soru_id_col - 1]).strip() if len(row) >= soru_id_col else ""
            if row_soru_id == target_id:
                candidate_rows.append((row_idx, row))

        if not candidate_rows:
            return False

        selected_row_idx = candidate_rows[0][0]

        # SoruID tekrar ederse soru metniyle disambiguate et
        if target_soru and soru_col_idx:
            for row_idx, row in candidate_rows:
                row_soru = str(row[soru_col_idx - 1]).strip() if len(row) >= soru_col_idx else ""
                if row_soru == target_soru:
                    selected_row_idx = row_idx
                    break

        cell_a1 = f"{colnum_to_letter(flag_col_idx)}{selected_row_idx}"
        ws.update(cell_a1, "Soru düzelt")
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
            "🧠 Soru Bankası",
            "🧮 Mitral Yetmezlik Hesaplayıcı",
            "🫀 Diyastolik Disfonksiyon Hesaplayıcı",
            "🏥 H-Type HT Çalışması",
            "🫀 AV tam blok-ileti sistemi pacing",
            "🫀 AFMR – TEE LV-GLS",
            "⚡ Kardiyoversiyon-Ablasyon / TEE-GLS",
            "🫁 PBMV – RV-PA Coupling",
            "⭐ Özellikli Vakalar",
            "📝 Case Report Takip",
            "✉️ Editöre Mektup",
        ],
        index=0,
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
# ===================== EKRAN 0: SORU BANKASI / QUIZ =======
# =========================================================
if menu == "🧠 Soru Bankası":
    st.header("🧠 Kardiyoloji Soru Bankası")

    # -----------------------------------------------------
    # Google Sheets başlık yapısı:
    # SoruID | Aktif | Kategori | Soru | A | B | C | D | E | Dogru | Aciklama | Kaynak
    # -----------------------------------------------------
    dfq = load_data(SHEET_ID, QUESTION_WS_INDEX, required_col="SoruID")

    if dfq.empty:
        st.warning("Henüz soru yok veya SoruBankasi sekmesi başlıkları uygun değil.")
        st.info(
            "Google Sheets içinde `SoruBankasi` isimli sekme açıp ilk satırı şu şekilde yap:\n\n"
            "`SoruID | Aktif | Kategori | Soru | A | B | C | D | E | Dogru | Aciklama | Kaynak`\n\n"
            "Not: Bu kodda varsayılan `question_ws_index = 8`. "
            "SoruBankasi farklı sıradaysa Streamlit secrets içine doğru index değerini ekle."
        )
        st.stop()

    required_cols = ["SoruID", "Aktif", "Kategori", "Soru", "A", "B", "C", "D", "E", "Dogru", "Aciklama", "Kaynak"]
    missing_cols = [c for c in required_cols if c not in dfq.columns]
    if missing_cols:
        st.error("SoruBankasi sekmesinde eksik kolon var: " + ", ".join(missing_cols))
        st.info("Başlık satırı birebir şöyle olmalı: `SoruID | Aktif | Kategori | Soru | A | B | C | D | E | Dogru | Aciklama | Kaynak`")
        st.stop()

    # Sadece aktif sorular. Aktif kolonu TRUE/1/evet/yes/aktif olmalı.
    dfq = dfq[
        dfq["Aktif"]
        .astype(str)
        .str.strip()
        .str.lower()
        .isin(["true", "1", "evet", "yes", "aktif"])
    ].copy()

    if dfq.empty:
        st.warning("Aktif soru bulunamadı. Sheet’te Aktif kolonunu TRUE yap.")
        st.stop()

    # Sorular aktif listenin tamamından rastgele gelir.
    # Sınıflandırma filtresi şimdilik kaldırıldı; Sheet'teki Kategori kolonu yalnızca bilgi amaçlı kullanılabilir.

    # SoruID’ye göre önce standart sıraya al; sonra bu standart liste üzerinden oturumluk karıştır.
    dfq["_SoruID_num"] = pd.to_numeric(dfq["SoruID"], errors="coerce")
    dfq = dfq.sort_values(["_SoruID_num", "SoruID"], na_position="last").drop(columns=["_SoruID_num"])
    dfq = dfq.reset_index(drop=True)

    # SoruID tekrar etse bile oturum sırası bozulmasın diye benzersiz iç UID oluştur.
    dfq["_quiz_uid"] = dfq["SoruID"].astype(str).str.strip() + "__" + dfq.index.astype(str)
    question_uids_current = dfq["_quiz_uid"].tolist()
    quiz_source_signature = tuple(question_uids_current)

    # Her yeni tarayıcı oturumunda veya soru listesi değişince random sıra üret.
    # Streamlit rerun oldukça sıra değişmesin diye session_state içinde saklanır.
    if (
        "quiz_order" not in st.session_state
        or "quiz_order_source" not in st.session_state
        or st.session_state.quiz_order_source != quiz_source_signature
    ):
        shuffled_df = dfq.sample(frac=1).reset_index(drop=True)
        st.session_state.quiz_order = shuffled_df["_quiz_uid"].tolist()
        st.session_state.quiz_order_source = quiz_source_signature
        st.session_state.quiz_index = 0
        st.session_state.quiz_answered = False
        st.session_state.quiz_selected = None
        st.session_state.quiz_score = 0
        st.session_state.quiz_done = False

    order_map = {uid: i for i, uid in enumerate(st.session_state.quiz_order)}
    dfq["_order"] = dfq["_quiz_uid"].map(order_map)
    dfq = dfq.sort_values("_order").drop(columns=["_order"]).reset_index(drop=True)

    # Session state başlangıç
    if "quiz_index" not in st.session_state:
        st.session_state.quiz_index = 0
    if "quiz_answered" not in st.session_state:
        st.session_state.quiz_answered = False
    if "quiz_selected" not in st.session_state:
        st.session_state.quiz_selected = None
    if "quiz_score" not in st.session_state:
        st.session_state.quiz_score = 0
    if "quiz_done" not in st.session_state:
        st.session_state.quiz_done = False

    total_q = len(dfq)

    if total_q == 0:
        st.warning("Gösterilecek soru yok.")
        st.stop()

    if st.session_state.quiz_index >= total_q:
        st.session_state.quiz_index = total_q - 1

    def _reset_quiz_with_new_order():
        shuffled_df = dfq.sample(frac=1).reset_index(drop=True)
        st.session_state.quiz_order = shuffled_df["_quiz_uid"].tolist()
        st.session_state.quiz_order_source = quiz_source_signature
        st.session_state.quiz_index = 0
        st.session_state.quiz_answered = False
        st.session_state.quiz_selected = None
        st.session_state.quiz_score = 0
        st.session_state.quiz_done = False

    def _clean_option_text(letter: str, value: str) -> str:
        """A hücresine yanlışlıkla 'A) metin' yazılırsa ekranda 'A) A) metin' görünmesini engeller."""
        txt = str(value).strip()
        prefixes = [f"{letter})", f"{letter}.", f"{letter}-", f"{letter}:"]
        for pref in prefixes:
            if txt.upper().startswith(pref.upper()):
                return txt[len(pref):].strip()
        return txt

    def _render_quiz_completion_bar(correct_count: int, answered_count: int, total_count: int):
        """
        Oyunlaştırılmış performans barı:
        - Ortada 0 çizgisi vardır.
        - Net doğru-yanlış skoru + yönde sağa yeşil, - yönde sola kırmızı dolar.
        - Bar ölçeği -10 ile +10 arasında sabittir; net skor bunun üzerine çıkarsa bar uçta sabit kalır.
        - Doğru/yanlış sayıları üstte artmaya devam eder.
        """
        total_count = max(int(total_count), 1)
        answered_count = max(0, min(int(answered_count), total_count))
        correct_count = max(0, min(int(correct_count), answered_count))
        wrong_count = max(0, answered_count - correct_count)
        remaining_count = max(0, total_count - answered_count)

        net_score = correct_count - wrong_count
        done_pct = (answered_count / total_count) * 100
        success_pct = round((correct_count / answered_count) * 100) if answered_count else 0

        # Oyun barı sabit -10 / +10 ölçeğinde çalışır.
        # Net +10 ve üzeri: sağ yarı tamamen yeşil.
        # Net -10 ve altı: sol yarı tamamen kırmızı.
        bar_target = 10
        capped_net = max(-bar_target, min(bar_target, net_score))

        if capped_net > 0:
            correct_half_width = (capped_net / bar_target) * 50
            wrong_half_width = 0
        elif capped_net < 0:
            correct_half_width = 0
            wrong_half_width = (abs(capped_net) / bar_target) * 50
        else:
            correct_half_width = 0
            wrong_half_width = 0

        if net_score > 0:
            net_label = f"Net: +{net_score}"
            net_emoji = "🟢"
        elif net_score < 0:
            net_label = f"Net: {net_score}"
            net_emoji = "🔴"
        else:
            net_label = "Net: 0"
            net_emoji = "⚪"

        html = f"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
  html, body {{
    margin: 0;
    padding: 0;
    background: transparent;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    color: #f8f9fa;
  }}
  .quiz-wrap {{
    width: 100%;
    box-sizing: border-box;
    padding: 0;
  }}
  .quiz-head {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    font-size: 15px;
    line-height: 1.35;
    margin-bottom: 8px;
    color: #f8f9fa;
    font-weight: 600;
    white-space: nowrap;
  }}
  .quiz-stats {{
    font-weight: 600;
  }}
  .quiz-bar {{
    position: relative;
    width: 100%;
    height: 32px;
    background: rgba(160,160,160,0.18);
    border: 1px solid rgba(180,180,180,0.38);
    border-radius: 18px;
    overflow: hidden;
    box-shadow: inset 0 1px 3px rgba(0,0,0,0.22);
    box-sizing: border-box;
  }}
  .wrong {{
    position: absolute;
    right: 50%;
    top: 0;
    width: {wrong_half_width:.4f}%;
    height: 100%;
    background: linear-gradient(270deg, #ff6b6b, #c92a2a);
    border-radius: 18px 0 0 18px;
  }}
  .correct {{
    position: absolute;
    left: 50%;
    top: 0;
    width: {correct_half_width:.4f}%;
    height: 100%;
    background: linear-gradient(90deg, #69db7c, #2f9e44);
    border-radius: 0 18px 18px 0;
  }}
  .zero-line {{
    position: absolute;
    left: 50%;
    top: 0;
    width: 4px;
    height: 100%;
    background: rgba(255,255,255,0.95);
    transform: translateX(-50%);
    box-shadow: 0 0 0 1px rgba(0,0,0,0.25), 0 0 8px rgba(255,255,255,0.35);
  }}
  .zero-label {{
    position: absolute;
    left: 50%;
    top: 50%;
    transform: translate(-50%, -50%);
    font-size: 11px;
    font-weight: 800;
    color: #212529;
    background: rgba(255,255,255,0.90);
    padding: 1px 7px;
    border-radius: 999px;
  }}
  .quiz-foot {{
    display: flex;
    justify-content: space-between;
    font-size: 12px;
    color: #adb5bd;
    margin-top: 5px;
    line-height: 1.25;
  }}
  @media (prefers-color-scheme: light) {{
    html, body {{ color: #212529; }}
    .quiz-head {{ color: #212529; }}
    .quiz-foot {{ color: #6c757d; }}
    .quiz-bar {{ background: rgba(0,0,0,0.08); border-color: rgba(0,0,0,0.18); }}
    .zero-line {{ background: rgba(33,37,41,0.9); }}
  }}
</style>
</head>
<body>
  <div class="quiz-wrap">
    <div class="quiz-head">
      <div>Performans barı</div>
      <div class="quiz-stats">✅ {correct_count} doğru &nbsp; | &nbsp; ❌ {wrong_count} yanlış &nbsp; | &nbsp; {net_emoji} {net_label} &nbsp; | &nbsp; Başarı: %{success_pct}</div>
    </div>
    <div class="quiz-bar">
      <div class="wrong" title="Yanlış cevaplar"></div>
      <div class="correct" title="Doğru cevaplar"></div>
      <div class="zero-line"></div>
      <div class="zero-label">0</div>
    </div>
    <div class="quiz-foot">
      <span>❌ negatif net</span>
      <span>0</span>
      <span>✅ pozitif net</span>
    </div>
  </div>
</body>
</html>
"""
        components.html(html, height=96, scrolling=False)

    # Test bitti ekranı
    if st.session_state.quiz_done:
        st.markdown("## 🏁 Test tamamlandı")

        correct_count = int(st.session_state.quiz_score)
        answered_count = total_q
        wrong_count = max(answered_count - correct_count, 0)
        success_pct = round((correct_count / answered_count) * 100) if answered_count else 0

        c1, c2 = st.columns(2)
        c1.metric("Doğru / Yanlış", f"{correct_count} / {wrong_count}")
        c2.metric("Başarı", f"%{success_pct}")

        _render_quiz_completion_bar(
            correct_count=correct_count,
            answered_count=answered_count,
            total_count=total_q,
        )

        st.success(f"Test tamamlandı: {correct_count} doğru, {wrong_count} yanlış, başarı %{success_pct}.")

        if st.button("🔁 Yeniden çöz", type="primary"):
            _reset_quiz_with_new_order()
            st.rerun()

        st.stop()

    q_index = st.session_state.quiz_index
    row = dfq.iloc[q_index].to_dict()

    soru_id = str(row.get("SoruID", q_index + 1)).strip()
    kategori = str(row.get("Kategori", "")).strip()
    soru = str(row.get("Soru", "")).strip()
    dogru = str(row.get("Dogru", "")).strip().upper()
    aciklama = str(row.get("Aciklama", "")).strip()
    kaynak = str(row.get("Kaynak", "")).strip()

    letters = ["A", "B", "C", "D", "E"]
    secenekler = []
    for letter in letters:
        val = str(row.get(letter, "")).strip()
        if val:
            secenekler.append((letter, _clean_option_text(letter, val)))

    valid_letters = [h for h, _ in secenekler]

    if not soru or not secenekler or dogru not in valid_letters:
        st.error(
            f"Bu soruda eksik/hatalı veri var. SoruID: {soru_id}\n\n"
            "Soru, şıklar veya Dogru alanını kontrol et. Dogru alanı A/B/C/D/E olmalı."
        )
        st.stop()

    # Yapılma oranı yalnızca performans barında izlenir; soru/cevaplanan sayaçları gösterilmez.
    answered_count = st.session_state.quiz_index + (1 if st.session_state.quiz_answered else 0)
    correct_count = int(st.session_state.quiz_score)

    _render_quiz_completion_bar(
        correct_count=correct_count,
        answered_count=answered_count,
        total_count=total_q,
    )

    st.markdown("---")

    # Soru metni
    st.markdown("### Soru")
    if kategori:
        st.caption(f"Kategori: {kategori}")
    st.markdown(f"#### {soru}")

    radio_options = list(range(len(secenekler)))

    quiz_uid = str(row.get("_quiz_uid", f"{soru_id}_{q_index}"))
    selected = st.radio(
        "Cevabınız:",
        options=radio_options,
        format_func=lambda i: f"{secenekler[i][0]}) {secenekler[i][1]}",
        index=st.session_state.quiz_selected if st.session_state.quiz_selected is not None else None,
        disabled=st.session_state.quiz_answered,
        key=f"quiz_radio_{quiz_uid}",
    )

    st.session_state.quiz_selected = selected

    # Butonlar
    col1, col2, col3, col4 = st.columns([1, 1, 1, 2])

    with col1:
        if st.button("✅ Cevapla", type="primary", disabled=st.session_state.quiz_answered):
            if st.session_state.quiz_selected is None:
                st.warning("Önce bir seçenek işaretle kral.")
            else:
                st.session_state.quiz_answered = True
                secilen_harf = secenekler[st.session_state.quiz_selected][0]
                if secilen_harf == dogru:
                    st.session_state.quiz_score += 1
                st.rerun()

    with col2:
        if st.button("➡️ Sonraki soru", disabled=not st.session_state.quiz_answered):
            if st.session_state.quiz_index < total_q - 1:
                st.session_state.quiz_index += 1
                st.session_state.quiz_answered = False
                st.session_state.quiz_selected = None
                st.rerun()
            else:
                st.session_state.quiz_done = True
                st.rerun()

    with col3:
        if st.button("☑️ Soru düzelt", help="Bu soruyu Google Sheets'te 'Soru Düzelt' kolonu altında işaretler."):
            ok = flag_question_for_review(
                SHEET_ID,
                QUESTION_WS_INDEX,
                soru_id=soru_id,
                soru_text=soru,
                flag_col="Soru Düzelt",
            )
            if ok:
                st.toast("☑️ Soru düzelt uyarısı Sheet'e işlendi.", icon="☑️")
                st.success("Bu soru Sheet'te `Soru Düzelt` olarak işaretlendi.")
            else:
                st.error("Uyarı Sheet'e yazılamadı. SoruID veya Sheet başlıklarını kontrol et.")

    with col4:
        if st.button("🔄 Baştan başla"):
            _reset_quiz_with_new_order()
            st.rerun()

    # Cevap sonrası geri bildirim
    if st.session_state.quiz_answered:
        st.markdown("---")

        secilen_harf = secenekler[st.session_state.quiz_selected][0]
        secilen_metin = secenekler[st.session_state.quiz_selected][1]
        dogru_metin = next((metin for h, metin in secenekler if h == dogru), "")

        if secilen_harf == dogru:
            st.success(f"✅ Doğru cevap: {dogru}) {dogru_metin}")
        else:
            st.error(
                f"❌ Yanlış cevap.\n\n"
                f"Senin cevabın: {secilen_harf}) {secilen_metin}\n\n"
                f"Doğru cevap: {dogru}) {dogru_metin}"
            )

        if aciklama:
            st.info(f"📌 Açıklama: {aciklama}")

        if kaynak:
            st.caption(f"📚 Kaynak: {kaynak}")


# =========================================================
# ===================== EKRAN MR: MİTRAL YETMEZLİK HESAPLAYICI =====
# =========================================================
elif menu == "🧮 Mitral Yetmezlik Hesaplayıcı":
    st.header("🧮 Mitral Kapak Yetmezliği Hesaplayıcı")
    st.caption(
        "Regürjitan volüm, regürjitan fraksiyon ve PISA temelli EROA hesabı. "
        "Amaç: MY şiddetini sayısal olarak desteklemek ve ölçüm mantığını öğretmek."
    )

    st.warning(
        "⚠️ Bu araç karar destek/öğretim amaçlıdır. Mitral yetmezlik şiddeti tek bir sayı ile değil; "
        "jet morfolojisi, VC/VCA, pulmoner ven akımı, CW Doppler yoğunluğu, LA/LV boyutları, ritim, yüklenme "
        "koşulları ve klinik ile birlikte integratif değerlendirilmelidir."
    )

    def _mr_safe_div(num, den):
        return (num / den) if den and den > 0 else 0.0

    def _mr_fmt(x, digits=2):
        try:
            return f"{float(x):.{digits}f}"
        except Exception:
            return "-"

    def _rf_grade(rf):
        if rf < 30:
            return "Hafif Yetmezlik", "low", "RF <%30: hafif aralık"
        if rf < 50:
            return "Orta Yetmezlik", "mid", "RF %30–49: orta aralık"
        return "Ciddi Yetmezlik", "high", "RF ≥%50: ciddi aralık"

    def _rvol_grade(rvol):
        if rvol < 30:
            return "Hafif", "RVol <30 mL"
        if rvol < 60:
            return "Orta", "RVol 30–59 mL"
        return "Ciddi", "RVol ≥60 mL"

    def _eroa_grade(eroa_cm2):
        if eroa_cm2 is None:
            return "Hesaplanmadı", ""
        if eroa_cm2 < 0.20:
            return "Hafif", "EROA <0.20 cm²"
        if eroa_cm2 < 0.40:
            return "Orta", "EROA 0.20–0.39 cm²"
        return "Ciddi", "EROA ≥0.40 cm²"

    def _badge_html(label, level):
        colors = {
            "low": ("#0f5132", "#d1e7dd", "#badbcc"),
            "mid": ("#664d03", "#fff3cd", "#ffecb5"),
            "high": ("#842029", "#f8d7da", "#f5c2c7"),
            "neutral": ("#084298", "#cfe2ff", "#b6d4fe"),
        }
        fg, bg, border = colors.get(level, colors["neutral"])
        return f"""
        <div style="
            border:1px solid {border};
            background:{bg};
            color:{fg};
            border-radius:18px;
            padding:18px 20px;
            text-align:center;
            margin:8px 0 14px 0;
        ">
            <div style="font-size:15px; opacity:0.85;">RF’ye göre sonuç</div>
            <div style="font-size:34px; font-weight:900; line-height:1.1;">{label}</div>
        </div>
        """

    tab_calc, tab_guide, tab_teach = st.tabs(
        ["🧮 Hesaplayıcı", "🧭 Yönlendirici", "📚 Öğretici notlar"]
    )

    with tab_calc:
        c0, c1, c2 = st.columns([1.2, 1, 1])
        with c0:
            hesap_modu = st.radio(
                "Hesaplama modu",
                [
                    "Doğrudan hacim girişi",
                    "PISA yöntemi",
                    "Volümetrik Doppler yöntemi",
                ],
                horizontal=False,
            )
        with c1:
            my_tipi = st.selectbox(
                "MY mekanizması",
                ["Primer / dejeneratif", "Sekonder / fonksiyonel", "Mekanizma belirsiz"],
                help="Sekonder MY’de sayısal değerler klinik bağlam ve LV boyutları ile birlikte yorumlanmalıdır.",
            )
        with c2:
            ritim_notu = st.selectbox(
                "Ölçüm ritmi",
                ["Sinüs ritmi", "Atriyal fibrilasyon / düzensiz ritim", "Belirsiz"],
                help="AF’de en az 3–5 atım ortalaması almak daha güvenlidir.",
            )

        st.divider()

        rf = 0.0
        rvol = 0.0
        total_sv = 0.0
        eroa = None
        flow_rate = None
        forward_sv = None
        calculation_note = ""

        if hesap_modu == "Doğrudan hacim girişi":
            st.subheader("1) Doğrudan Hacim Girişi")
            i1, i2 = st.columns(2)
            with i1:
                rvol = st.number_input(
                    "Regürjitan Volüm (RVol) (mL)",
                    min_value=0.0,
                    max_value=300.0,
                    value=40.0,
                    step=1.0,
                    help="Eko, CMR veya volumetrik yöntemle bulunan regürjitan volüm.",
                )
            with i2:
                total_sv = st.number_input(
                    "Toplam Atım Hacmi / Mitral SV (mL)",
                    min_value=1.0,
                    max_value=400.0,
                    value=100.0,
                    step=1.0,
                    help="Regürjitan akımı da içeren toplam LV/mitral stroke volüm.",
                )
            rf = _mr_safe_div(rvol, total_sv) * 100
            calculation_note = "RF = RVol / Toplam SV × 100"

        elif hesap_modu == "PISA yöntemi":
            st.subheader("2) PISA Yöntemi")
            st.caption("Varsayılan formül hemisferik PISA kabul eder. Birimler: r=cm, Va=cm/sn, Vmax=cm/sn, MR VTI=cm.")

            p1, p2, p3, p4, p5 = st.columns(5)
            with p1:
                pisa_r = st.number_input("PISA yarıçapı r (cm)", min_value=0.0, max_value=3.0, value=0.80, step=0.05)
            with p2:
                aliasing_va = st.number_input("Aliasing hızı Va (cm/sn)", min_value=1.0, max_value=150.0, value=40.0, step=1.0)
            with p3:
                mr_vmax = st.number_input("Maksimum MR hızı Vmax (cm/sn)", min_value=50.0, max_value=800.0, value=500.0, step=10.0)
            with p4:
                mr_vti = st.number_input("MR VTI (cm)", min_value=1.0, max_value=300.0, value=150.0, step=1.0)
            with p5:
                total_sv = st.number_input("Toplam SV / Mitral SV (mL)", min_value=1.0, max_value=400.0, value=100.0, step=1.0)

            ac1, ac2 = st.columns([1, 2])
            with ac1:
                use_angle = st.checkbox("Açı düzeltmesi kullan", value=False)
            with ac2:
                pisa_angle = st.slider(
                    "PISA açısı (derece)",
                    min_value=60,
                    max_value=360,
                    value=180,
                    step=10,
                    disabled=not use_angle,
                    help="Klasik hemisfer için 180°. Daha dar akım konverjansında açı düzeltmesi yapılabilir.",
                )

            angle_factor = (pisa_angle / 180.0) if use_angle else 1.0
            flow_rate = 2 * 3.141592653589793 * (pisa_r ** 2) * aliasing_va * angle_factor
            eroa = _mr_safe_div(flow_rate, mr_vmax)
            rvol = eroa * mr_vti
            rf = _mr_safe_div(rvol, total_sv) * 100
            calculation_note = "Flow = 2πr²Va; EROA = Flow/Vmax; RVol = EROA × MR VTI; RF = RVol/Toplam SV × 100"

        else:
            st.subheader("3) Volümetrik Doppler Yöntemi")
            st.caption(
                "Mantık: Toplam LV SV’den ileri LVOT SV çıkarılır. "
                "Aort yetersizliği veya belirgin intrakardiyak şant varsa güvenilirliği azalır."
            )

            v1, v2, v3, v4 = st.columns(4)
            with v1:
                lvedv_calc = st.number_input("LVEDV (mL)", min_value=0.0, max_value=500.0, value=140.0, step=1.0)
            with v2:
                lvesv_calc = st.number_input("LVESV (mL)", min_value=0.0, max_value=500.0, value=60.0, step=1.0)
            with v3:
                lvot_d = st.number_input("LVOT çapı (cm)", min_value=0.1, max_value=4.0, value=2.0, step=0.05)
            with v4:
                lvot_vti = st.number_input("LVOT VTI (cm)", min_value=1.0, max_value=60.0, value=20.0, step=0.5)

            total_sv = max(lvedv_calc - lvesv_calc, 0.0)
            lvot_area = 3.141592653589793 * (lvot_d / 2) ** 2
            forward_sv = lvot_area * lvot_vti
            rvol = max(total_sv - forward_sv, 0.0)
            rf = _mr_safe_div(rvol, total_sv) * 100
            calculation_note = "Toplam LV SV = LVEDV − LVESV; LVOT SV = π × (LVOT çap/2)² × LVOT VTI; RVol = Toplam SV − LVOT SV"

        st.divider()

        label, level, rf_explain = _rf_grade(rf)
        st.markdown(_badge_html(label, level), unsafe_allow_html=True)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Regürjitan Fraksiyon", f"%{_mr_fmt(rf)}")
        m2.metric("Regürjitan Volüm", f"{_mr_fmt(rvol)} mL")
        m3.metric("Toplam SV", f"{_mr_fmt(total_sv)} mL")
        if eroa is not None:
            m4.metric("EROA", f"{_mr_fmt(eroa)} cm²")
        elif forward_sv is not None:
            m4.metric("İleri LVOT SV", f"{_mr_fmt(forward_sv)} mL")
        else:
            m4.metric("EROA", "—")

        if flow_rate is not None:
            e1, e2 = st.columns(2)
            e1.metric("PISA Flow Rate", f"{_mr_fmt(flow_rate)} mL/sn")
            e2.metric("EROA", f"{_mr_fmt(eroa)} cm²  ({_mr_fmt(eroa * 100)} mm²)")

        rvol_g, rvol_txt = _rvol_grade(rvol)
        eroa_g, eroa_txt = _eroa_grade(eroa)

        st.markdown("### 🔎 Sayısal uyum kontrolü")
        check_cols = st.columns(3)
        check_cols[0].info(f"**RF:** {rf_explain}")
        check_cols[1].info(f"**RVol:** {rvol_g} aralık\n\n{rvol_txt}")
        check_cols[2].info(f"**EROA:** {eroa_g}\n\n{eroa_txt if eroa_txt else 'Bu modda EROA hesaplanmadı.'}")

        severe_votes = 0
        moderate_votes = 0
        if rf >= 50:
            severe_votes += 1
        elif rf >= 30:
            moderate_votes += 1

        if rvol >= 60:
            severe_votes += 1
        elif rvol >= 30:
            moderate_votes += 1

        if eroa is not None:
            if eroa >= 0.40:
                severe_votes += 1
            elif eroa >= 0.20:
                moderate_votes += 1

        if severe_votes >= 2 or (eroa is None and rf >= 50 and rvol >= 60):
            st.error("🔴 Sayısal parametreler ciddi MY lehine güçlü uyum gösteriyor. Klinik ve integratif eko bulguları ile doğrula.")
        elif severe_votes == 1 and moderate_votes >= 1:
            st.warning("🟠 Sınırda/karma sonuç var. Ölçüm kalitesi, jet tipi, kan basıncı ve ek parametreleri kontrol et.")
        elif moderate_votes >= 1:
            st.warning("🟡 Sayısal parametreler orta MY aralığında. Takip ve integratif değerlendirme önemli.")
        else:
            st.success("🟢 Sayısal parametreler hafif MY aralığı ile uyumlu.")

        with st.expander("🧪 Ölçüm güvenilirliği uyarıları", expanded=True):
            q1, q2, q3 = st.columns(3)
            eccentric = q1.checkbox("Eksantrik / Coanda jet")
            multijet = q1.checkbox("Multipl jet")
            late_systolic = q2.checkbox("Geç sistolik veya dinamik MY")
            poor_quality = q2.checkbox("Görüntü/Doppler kalitesi sınırlı")
            ar_shunt = q3.checkbox("Eşlik eden ciddi AY veya şant")
            bp_unstable = q3.checkbox("Belirgin yüklenme/BP değişkenliği")

            risk_count = sum([eccentric, multijet, late_systolic, poor_quality, ar_shunt, bp_unstable])
            if ritim_notu.startswith("Atriyal"):
                risk_count += 1

            if risk_count >= 3:
                st.error("Güvenilirlik düşük olabilir: tek ölçüme göre karar verme; 3D VCA/VC, PV akımı, CMR veya uzman eko kontrolü düşün.")
            elif risk_count >= 1:
                st.warning("Bazı sınırlılıklar var: ölçümü birkaç parametreyle doğrulamak iyi olur.")
            else:
                st.success("Belirgin güvenilirlik uyarısı seçilmedi.")

        with st.expander("📐 Kullanılan formül"):
            st.code(calculation_note, language="text")

    with tab_guide:
        st.subheader("🧭 Klinik yönlendirici karar destek")
        st.caption("Bu bölüm hesap sonucunu klinik bağlamla birleştirir; nihai karar Heart Team / kapak ekibi ile verilmelidir.")

        g1, g2, g3, g4 = st.columns(4)
        with g1:
            symptom = st.selectbox("Semptom", ["Yok", "Var / NYHA II-IV", "Belirsiz"])
        with g2:
            lvef_g = st.number_input("LVEF (%)", min_value=5.0, max_value=90.0, value=60.0, step=1.0, key="mr_guide_lvef")
        with g3:
            lvesd_g = st.number_input("LVESD (mm)", min_value=10.0, max_value=90.0, value=38.0, step=1.0, key="mr_guide_lvesd")
        with g4:
            spap_g = st.number_input("sPAP (mmHg)", min_value=0.0, max_value=120.0, value=35.0, step=1.0, key="mr_guide_spap")

        g5, g6, g7 = st.columns(3)
        new_af = g5.checkbox("Yeni AF var")
        pulmonary_venous_reversal = g6.checkbox("Pulmoner ven sistolik reversiyon var")
        flail_leaflet = g7.checkbox("Flail/prolapsus belirgin")

        severe_by_numbers = rf >= 50 or rvol >= 60 or (eroa is not None and eroa >= 0.40)
        severe_support = pulmonary_venous_reversal or flail_leaflet

        st.markdown("### Öneri özeti")

        if not severe_by_numbers and not severe_support:
            st.success(
                "Şu an ciddi MY lehine güçlü bir sinyal yok. Ölçümler kaliteli ise periyodik takip ve klinik bağlama göre kontrol uygun görünür."
            )
        else:
            if my_tipi == "Primer / dejeneratif":
                if symptom.startswith("Var") or lvef_g <= 60 or lvesd_g >= 40:
                    st.error(
                        "Primer MY + ciddi MY şüphesi + semptom veya LV disfonksiyon/dilatasyon kriteri var. "
                        "Mitral kapak tamiri/cerrahi açısından kapak ekibi değerlendirmesi önerilir."
                    )
                elif new_af or spap_g > 50:
                    st.warning(
                        "Asemptomatik primer ciddi MY olabilir; yeni AF veya pulmoner basınç yüksekliği varsa ileri değerlendirme ve kapak ekibi görüşü düşün."
                    )
                else:
                    st.info(
                        "Asemptomatik primer ciddi MY olasılığı var. Deneyimli merkezde tamir edilebilirlik, seri LV ölçümleri ve yakın takip planı yap."
                    )
            elif my_tipi == "Sekonder / fonksiyonel":
                st.warning(
                    "Sekonder MY’de önce optimal medikal tedavi, volüm kontrolü ve CRT endikasyonu değerlendirilir. "
                    "Buna rağmen ciddi semptomatik MY sürüyorsa anatomiye göre TEER/cerrahi için Heart Team değerlendirmesi düşün."
                )
            else:
                st.info(
                    "Mekanizma belirsiz: önce primer-sekonder ayrımını netleştir. TTE/TEE, 3D değerlendirme ve gerekirse CMR ile integratif analiz yap."
                )

        st.markdown("### Kontrol listesi")
        st.checkbox("Kan basıncı ve volüm durumu ölçüm sırasında uygun muydu?")
        st.checkbox("VC/3D VCA, PISA, RVol/RF ve pulmoner ven akımı birbiriyle uyumlu mu?")
        st.checkbox("LA/LV boyutları MY şiddeti ve kronisite ile uyumlu mu?")
        st.checkbox("Eksantrik veya multipl jet nedeniyle PISA/jet alanı yanıltıcı olabilir mi?")
        st.checkbox("AF varsa çoklu atım ortalaması alındı mı?")

    with tab_teach:
        st.subheader("📚 Kısa öğretici notlar")

        st.markdown(
            """
**1) Regürjitan fraksiyon (RF)**  
Toplam LV/mitral atım hacminin yüzde kaçının sol atriyuma geri kaçtığını gösterir.  
Pratik eşikler: **<%30 hafif**, **%30–49 orta**, **≥%50 ciddi**.

**2) Regürjitan volüm (RVol)**  
Her sistolde LA'ya geri dönen hacimdir. Genel pratikte **≥60 mL ciddi MY** lehinedir.

**3) EROA**  
Etkin regürjitan orifis alanıdır. PISA ile hesaplanabilir. Genel pratikte **≥0.40 cm² ciddi MY** lehinedir.

**4) PISA nerede zorlanır?**  
Eksantrik jet, multipl jet, eliptik orifis, geç sistolik MY, AF, kötü görüntü, yanlış aliasing hızı ve yanlış yarıçap ölçümü PISA'yı yanıltabilir.

**5) En doğru yaklaşım**  
MY şiddeti; **sayısal ölçümler + kapak morfolojisi + pulmoner ven akımı + LA/LV etkilenimi + klinik** ile birlikte değerlendirilir.
"""
        )

        st.info(
            "Pratik ipucu: Sonuç ciddi çıkıyor ama LA/LV hiç etkilenmemişse veya CW Doppler zayıfsa ölçümü tekrar kontrol et. "
            "Tersi durumda, eksantrik jetlerde renkli Doppler jet alanı küçük görünse bile MY ciddi olabilir."
        )




# =========================================================
# ===================== EKRAN DD: DİYASTOLİK DİSFONKSİYON HESAPLAYICI =====
# =========================================================
elif menu == "🫀 Diyastolik Disfonksiyon Hesaplayıcı":
    st.header("🫀 Diyastolik Disfonksiyon Hesaplayıcı")
    st.caption(
        "ASE 2025/2026 pratik algoritmasına göre diyastolik disfonksiyon, LV dolum basıncı ve grade değerlendirmesi. "
        "Amaç: hızlı klinik karar desteği; nihai yorum her zaman ölçüm kalitesi ve klinik bağlamla yapılmalıdır."
    )

    st.warning(
        "⚠️ Bu araç karar destek/öğretim amaçlıdır. Ciddi kapak hastalığı, protez/TEER, ileri MAC, konstriksiyon, "
        "belirgin non-kardiyak pulmoner hipertansiyon veya kötü Doppler kalitesinde standart algoritma yanıltıcı olabilir."
    )

    def _dd_safe_div(num, den):
        return (num / den) if den and den > 0 else 0.0

    def _dd_fmt(x, digits=2):
        try:
            return f"{float(x):.{digits}f}"
        except Exception:
            return "—"

    def _dd_bool_txt(flag):
        return "Pozitif" if flag else "Negatif"

    def _dd_badge_html(title, subtitle, level="neutral"):
        colors = {
            "normal": ("#0f5132", "#d1e7dd", "#badbcc"),
            "mild": ("#664d03", "#fff3cd", "#ffecb5"),
            "high": ("#842029", "#f8d7da", "#f5c2c7"),
            "uncertain": ("#084298", "#cfe2ff", "#b6d4fe"),
            "neutral": ("#212529", "#e9ecef", "#ced4da"),
        }
        fg, bg, border = colors.get(level, colors["neutral"])
        return f"""
        <div style="
            border:1px solid {border};
            background:{bg};
            color:{fg};
            border-radius:18px;
            padding:18px 20px;
            text-align:center;
            margin:8px 0 14px 0;
        ">
            <div style="font-size:15px; opacity:0.85;">{subtitle}</div>
            <div style="font-size:32px; font-weight:900; line-height:1.1;">{title}</div>
        </div>
        """

    def _dd_lap_label(lap_state):
        if lap_state == "Yüksek":
            return "Artmış LAP", "high"
        if lap_state == "Normal":
            return "Normal LAP", "normal"
        return "LAP belirsiz", "uncertain"

    def _dd_reliability(missing_count, special_count, support_count):
        if special_count >= 1 or missing_count >= 2:
            return "Düşük"
        if missing_count == 1 or support_count == 0:
            return "Orta"
        return "Yüksek"

    mode = st.radio(
        "Ritim / algoritma",
        ["Sinüs ritmi", "Atriyal fibrilasyon / flutter"],
        horizontal=True,
        key="dd_mode",
    )

    with st.expander("⚠️ Genel algoritmayı sınırlayan durumlar", expanded=False):
        s1, s2, s3, s4 = st.columns(4)
        severe_mr = s1.checkbox("Ciddi primer MY", key="dd_special_mr")
        ms_or_mac = s2.checkbox("MS / ileri MAC", key="dd_special_ms_mac")
        mitral_intervention = s3.checkbox("Mitral protez / TEER", key="dd_special_intervention")
        other_special = s4.checkbox("Konstriksiyon / non-kardiyak PHT", key="dd_special_other")
        special_count = sum([severe_mr, ms_or_mac, mitral_intervention, other_special])

        if special_count:
            st.warning(
                "Seçilen özel durumda standart diyastolik algoritma doğrudan uygulanmamalı. "
                "Sonuç kartını daha çok uyarı/ön değerlendirme olarak kullan."
            )

    st.divider()

    if mode == "Sinüs ritmi":
        st.subheader("🧮 Pratik sinüs ritmi algoritması")

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            lvef = st.number_input("LVEF (%)", min_value=5.0, max_value=90.0, value=60.0, step=1.0, key="dd_s_lvef")
            mitral_e = st.number_input("Mitral E (cm/sn)", min_value=0.0, max_value=250.0, value=80.0, step=1.0, key="dd_s_e")
            mitral_a = st.number_input("Mitral A (cm/sn)", min_value=0.0, max_value=250.0, value=70.0, step=1.0, key="dd_s_a")
        with c2:
            septal_e = st.number_input("Septal e' (cm/sn)", min_value=0.0, max_value=30.0, value=7.0, step=0.5, key="dd_s_septal_e")
            lateral_e = st.number_input("Lateral e' (cm/sn)", min_value=0.0, max_value=35.0, value=9.0, step=0.5, key="dd_s_lateral_e")
            tr_vmax = st.number_input("TR Vmax (m/sn)", min_value=0.0, max_value=6.0, value=2.5, step=0.1, key="dd_s_trv")
        with c3:
            lavi = st.number_input("LAVI (mL/m²)", min_value=0.0, max_value=120.0, value=30.0, step=1.0, key="dd_s_lavi")
            lars = st.number_input("LARS (%) - opsiyonel", min_value=0.0, max_value=80.0, value=0.0, step=1.0, key="dd_s_lars", help="Ölçülmediyse 0 bırak.")
            pv_sd = st.number_input("PV S/D - opsiyonel", min_value=0.0, max_value=5.0, value=0.0, step=0.1, key="dd_s_pvsd", help="Ölçülmediyse 0 bırak.")
        with c4:
            ivrt = st.number_input("IVRT (ms) - opsiyonel", min_value=0.0, max_value=200.0, value=0.0, step=5.0, key="dd_s_ivrt", help="Ölçülmediyse 0 bırak.")
            symptomatic = st.checkbox("Dispne / HFpEF şüphesi", key="dd_s_symptom")
            use_lars_support = st.checkbox("LARS ölçümü güvenilir", value=(lars > 0), key="dd_s_lars_reliable")

        e_a = _dd_safe_div(mitral_e, mitral_a)
        avg_e_prime = (septal_e + lateral_e) / 2 if (septal_e > 0 and lateral_e > 0) else 0.0
        septal_ee = _dd_safe_div(mitral_e, septal_e)
        lateral_ee = _dd_safe_div(mitral_e, lateral_e)
        avg_ee = _dd_safe_div(mitral_e, avg_e_prime)

        reduced_e_prime = bool((septal_e > 0 and septal_e <= 6) or (lateral_e > 0 and lateral_e <= 7) or (avg_e_prime > 0 and avg_e_prime <= 6.5))
        high_ee = bool((avg_ee >= 14) or (septal_ee >= 15) or (lateral_ee >= 13))
        high_tr = bool(tr_vmax >= 2.8)
        high_lavi = bool(lavi > 34)
        low_lars = bool(use_lars_support and lars > 0 and lars <= 18)
        abnormal_ea_for_dd = bool((mitral_a > 0 and e_a <= 0.8) or (mitral_a > 0 and e_a >= 2.0))
        pv_support = bool(pv_sd > 0 and pv_sd <= 0.67)
        ivrt_support = bool(ivrt > 0 and ivrt <= 70)

        dd_support_flags = [high_ee, low_lars, abnormal_ea_for_dd, high_lavi]
        dd_support_count = sum(dd_support_flags)
        if reduced_e_prime and dd_support_count >= 1:
            dd_present = True
        elif (not reduced_e_prime) and dd_support_count >= 2:
            dd_present = True
        else:
            dd_present = False

        main_positive_count = sum([reduced_e_prime, high_ee, high_tr])
        support_positive_count = sum([high_lavi, low_lars, pv_support, ivrt_support])
        missing_count = sum([
            1 if mitral_e <= 0 else 0,
            1 if mitral_a <= 0 else 0,
            1 if septal_e <= 0 or lateral_e <= 0 else 0,
            1 if tr_vmax <= 0 else 0,
            1 if lavi <= 0 else 0,
        ])

        if missing_count >= 3:
            grade = "Kararsız"
            lap_state = "Belirsiz"
            result_note = "Temel ölçümlerin çoğu eksik. En az E/A, e', E/e', TR Vmax ve LAVI ile tekrar değerlendir."
        elif not dd_present and main_positive_count == 0 and support_positive_count == 0:
            grade = "Normal"
            lap_state = "Normal"
            result_note = "Diyastolik disfonksiyon lehine güçlü bulgu yok."
        elif main_positive_count == 3:
            lap_state = "Yüksek"
            grade = "Grade 3" if e_a >= 2.0 else "Grade 2"
            result_note = "Ana değişkenlerin tamamı pozitif; LV dolum basıncı artmış kabul edilir."
        elif reduced_e_prime and not high_ee and not high_tr:
            if mitral_a > 0 and e_a <= 0.8:
                grade = "Grade 1"
                lap_state = "Normal"
                result_note = "Relaksasyon bozukluğu paterni; LAP genellikle normaldir."
            elif support_positive_count >= 1:
                grade = "Grade 2 olası"
                lap_state = "Yüksek"
                result_note = "Reduced e' yanında destek parametresi pozitif; artmış LAP olasıdır."
            else:
                grade = "Grade 1 / Kararsız"
                lap_state = "Normal veya belirsiz"
                result_note = "Reduced e' var ama LAP artışı için yeterli destek yok."
        elif (main_positive_count >= 2) or high_ee or high_tr:
            if support_positive_count >= 1:
                lap_state = "Yüksek"
                grade = "Grade 3" if e_a >= 2.0 else "Grade 2"
                result_note = "Ana ve destek parametreler artmış LAP lehine."
            else:
                lap_state = "Belirsiz"
                grade = "Kararsız"
                result_note = "Ana parametrelerde sinyal var; fakat destek parametresi yok veya negatif."
        elif dd_present:
            grade = "Grade 1 olası"
            lap_state = "Normal veya belirsiz"
            result_note = "Diyastolik disfonksiyon sinyali var, ancak artmış LAP için güçlü kanıt yok."
        else:
            grade = "Normal / Kararsız"
            lap_state = "Normal veya belirsiz"
            result_note = "Sonuç sınıra yakın; ölçüm kalitesini ve klinik bağlamı kontrol et."

        if lvef < 50:
            result_note += " LVEF <%50 olduğundan yorum klinik bağlamla birlikte yapılmalı."

        reliability = _dd_reliability(missing_count, special_count, support_positive_count)
        lap_label, lap_level = _dd_lap_label(lap_state if lap_state in ["Normal", "Yüksek"] else "Belirsiz")
        badge_level = "normal" if grade == "Normal" else ("high" if "Grade 2" in grade or "Grade 3" in grade else ("mild" if "Grade 1" in grade else "uncertain"))

        st.markdown(_dd_badge_html(grade, f"Sonuç: {lap_label} | Güvenilirlik: {reliability}", badge_level), unsafe_allow_html=True)

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("E/A", _dd_fmt(e_a, 2) if mitral_a > 0 else "—")
        m2.metric("Ortalama e'", f"{_dd_fmt(avg_e_prime, 1)} cm/sn" if avg_e_prime > 0 else "—")
        m3.metric("Ortalama E/e'", _dd_fmt(avg_ee, 1) if avg_ee > 0 else "—")
        m4.metric("LAVI", f"{_dd_fmt(lavi, 1)} mL/m²" if lavi > 0 else "—")
        m5.metric("TR Vmax", f"{_dd_fmt(tr_vmax, 1)} m/sn" if tr_vmax > 0 else "—")

        st.info(f"📌 **Yorum:** {result_note}")

        if symptomatic and lap_state != "Yüksek":
            st.warning(
                "Semptom/HFpEF şüphesi var ama istirahat bulguları net yüksek LAP göstermiyor. "
                "Uygunsa diyastolik stres eko veya ek klinik skorlarla değerlendirme düşünülebilir."
            )

        with st.expander("🔎 Kanıt tablosu", expanded=True):
            evidence = pd.DataFrame([
                {"Parametre": "Reduced e'", "Değer": f"Septal {septal_e:.1f}, lateral {lateral_e:.1f}, ort {avg_e_prime:.1f}", "Eşik": "Septal ≤6 veya lateral ≤7 veya ort ≤6.5", "Sonuç": _dd_bool_txt(reduced_e_prime)},
                {"Parametre": "Increased E/e'", "Değer": f"Ort {avg_ee:.1f} / septal {septal_ee:.1f} / lateral {lateral_ee:.1f}", "Eşik": "Ort ≥14 veya septal ≥15 veya lateral ≥13", "Sonuç": _dd_bool_txt(high_ee)},
                {"Parametre": "TR Vmax", "Değer": f"{tr_vmax:.1f} m/sn", "Eşik": "≥2.8 m/sn", "Sonuç": _dd_bool_txt(high_tr)},
                {"Parametre": "LAVI", "Değer": f"{lavi:.1f} mL/m²", "Eşik": ">34 mL/m²", "Sonuç": _dd_bool_txt(high_lavi)},
                {"Parametre": "LARS", "Değer": f"{lars:.1f}%" if lars > 0 else "Ölçülmedi", "Eşik": "≤18%", "Sonuç": _dd_bool_txt(low_lars) if lars > 0 else "—"},
                {"Parametre": "PV S/D", "Değer": f"{pv_sd:.2f}" if pv_sd > 0 else "Ölçülmedi", "Eşik": "≤0.67", "Sonuç": _dd_bool_txt(pv_support) if pv_sd > 0 else "—"},
                {"Parametre": "IVRT", "Değer": f"{ivrt:.0f} ms" if ivrt > 0 else "Ölçülmedi", "Eşik": "≤70 ms", "Sonuç": _dd_bool_txt(ivrt_support) if ivrt > 0 else "—"},
            ])
            st.dataframe(evidence, use_container_width=True, hide_index=True)

        with st.expander("📝 Rapor cümlesi"):
            if grade == "Normal":
                report = "Diyastolik fonksiyon normal sınırlarda izlenmiştir. Sol atriyal basınç artışı lehine belirgin bulgu saptanmamıştır."
            elif "Grade 1" in grade:
                report = "Bulgular Grade 1 diyastolik disfonksiyon/relaksasyon bozukluğu ile uyumludur. Sol atriyal basınç normal veya belirgin artmamış görünmektedir."
            elif "Grade 2" in grade:
                report = "Bulgular Grade 2 diyastolik disfonksiyon ve artmış sol atriyal basınç ile uyumludur."
            elif "Grade 3" in grade:
                report = "Bulgular Grade 3 diyastolik disfonksiyon ve belirgin artmış sol atriyal basınç ile uyumludur."
            else:
                report = "Diyastolik fonksiyon ve sol atriyal basınç mevcut ölçümlerle net sınıflandırılamadı; ek parametreler ve klinik bağlam ile değerlendirme önerilir."
            st.code(report, language="text")

    else:
        st.subheader("🧮 Pratik AF/flutter algoritması")
        st.caption("AF’de A dalgası olmadığı için E/A kullanılmaz; sonuç LAP tahmini odaklıdır.")

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            lvef = st.number_input("LVEF (%)", min_value=5.0, max_value=90.0, value=55.0, step=1.0, key="dd_af_lvef")
            mitral_e = st.number_input("Mitral E (cm/sn)", min_value=0.0, max_value=250.0, value=90.0, step=1.0, key="dd_af_e")
        with c2:
            septal_e = st.number_input("Septal e' (cm/sn)", min_value=0.0, max_value=30.0, value=7.0, step=0.5, key="dd_af_septal_e")
            septal_ee = _dd_safe_div(mitral_e, septal_e)
            st.metric("Septal E/e'", _dd_fmt(septal_ee, 1) if septal_e > 0 else "—")
        with c3:
            tr_vmax = st.number_input("TR Vmax (m/sn)", min_value=0.0, max_value=6.0, value=2.6, step=0.1, key="dd_af_trv")
            dt = st.number_input("E deselerasyon zamanı (ms)", min_value=0.0, max_value=400.0, value=180.0, step=5.0, key="dd_af_dt")
        with c4:
            lavi = st.number_input("LAVI (mL/m²)", min_value=0.0, max_value=120.0, value=32.0, step=1.0, key="dd_af_lavi")
            lars = st.number_input("LARS (%) - opsiyonel", min_value=0.0, max_value=80.0, value=0.0, step=1.0, key="dd_af_lars", help="Ölçülmediyse 0 bırak.")

        af_e_high = bool(mitral_e >= 100)
        af_ee_high = bool(septal_ee > 11)
        af_tr_high = bool(tr_vmax > 2.8)
        af_dt_short = bool(dt > 0 and dt <= 160)
        af_lavi_high = bool(lavi > 34)
        af_lars_low = bool(lars > 0 and lars < 18)

        af_main_count = sum([af_e_high, af_ee_high, af_tr_high, af_dt_short])
        af_support_count = sum([af_lavi_high, af_lars_low])
        af_missing_count = sum([
            1 if mitral_e <= 0 else 0,
            1 if septal_e <= 0 else 0,
            1 if tr_vmax <= 0 else 0,
            1 if dt <= 0 else 0,
        ])

        if af_missing_count >= 3:
            lap_state = "Belirsiz"
            result = "Kararsız"
            note = "Temel AF parametrelerinin çoğu eksik."
        elif af_main_count >= 3:
            lap_state = "Yüksek"
            result = "Artmış LAP olası"
            note = "AF ana kriterlerinin ≥3 tanesi pozitif."
        elif af_main_count <= 1:
            lap_state = "Normal"
            result = "Normal LAP olası"
            note = "AF ana kriterlerinden 0–1 tanesi pozitif."
        else:
            if af_support_count >= 1:
                lap_state = "Yüksek"
                result = "Artmış LAP olası"
                note = "AF ana kriterleri ara bölgede; destek parametresi pozitif."
            else:
                lap_state = "Belirsiz"
                result = "Kararsız"
                note = "AF ana kriterleri ara bölgede; destek parametresi yok veya negatif."

        reliability = _dd_reliability(af_missing_count, special_count, af_support_count)
        lap_label, lap_level = _dd_lap_label(lap_state)
        badge_level = "high" if lap_state == "Yüksek" else ("normal" if lap_state == "Normal" else "uncertain")
        st.markdown(_dd_badge_html(result, f"Sonuç: {lap_label} | Güvenilirlik: {reliability}", badge_level), unsafe_allow_html=True)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Mitral E", f"{mitral_e:.0f} cm/sn")
        m2.metric("Septal E/e'", _dd_fmt(septal_ee, 1) if septal_e > 0 else "—")
        m3.metric("TR Vmax", f"{tr_vmax:.1f} m/sn")
        m4.metric("DT", f"{dt:.0f} ms" if dt > 0 else "—")

        st.info(f"📌 **Yorum:** {note}")

        with st.expander("🔎 Kanıt tablosu", expanded=True):
            evidence = pd.DataFrame([
                {"Parametre": "Mitral E", "Değer": f"{mitral_e:.0f} cm/sn", "Eşik": "≥100 cm/sn", "Sonuç": _dd_bool_txt(af_e_high)},
                {"Parametre": "Septal E/e'", "Değer": f"{septal_ee:.1f}", "Eşik": ">11", "Sonuç": _dd_bool_txt(af_ee_high)},
                {"Parametre": "TR Vmax", "Değer": f"{tr_vmax:.1f} m/sn", "Eşik": ">2.8 m/sn", "Sonuç": _dd_bool_txt(af_tr_high)},
                {"Parametre": "DT", "Değer": f"{dt:.0f} ms", "Eşik": "≤160 ms", "Sonuç": _dd_bool_txt(af_dt_short)},
                {"Parametre": "LAVI", "Değer": f"{lavi:.1f} mL/m²", "Eşik": ">34 mL/m²", "Sonuç": _dd_bool_txt(af_lavi_high)},
                {"Parametre": "LARS", "Değer": f"{lars:.1f}%" if lars > 0 else "Ölçülmedi", "Eşik": "<18%", "Sonuç": _dd_bool_txt(af_lars_low) if lars > 0 else "—"},
            ])
            st.dataframe(evidence, use_container_width=True, hide_index=True)

        with st.expander("📝 Rapor cümlesi"):
            if lap_state == "Yüksek":
                report = "AF ritminde mevcut Doppler ve destek parametreleri artmış sol atriyal basınç lehinedir."
            elif lap_state == "Normal":
                report = "AF ritminde mevcut Doppler parametreleri artmış sol atriyal basınç lehine güçlü bulgu göstermemektedir."
            else:
                report = "AF ritminde sol atriyal basınç mevcut ölçümlerle net değerlendirilemedi; ek parametreler ve klinik bağlam ile yorum önerilir."
            st.code(report, language="text")

    st.divider()
    with st.expander("📚 Kısa öğretici notlar", expanded=False):
        st.markdown(
            """
**Pratik mantık:** Diyastolik değerlendirmede tek parametreye güvenilmez; mitral inflow, annüler e', E/e', TR Vmax, LAVI ve mümkünse LARS birlikte yorumlanır.

**E/e' yorumu:** Ortalama E/e' yüksekliği dolum basıncı artışını destekler; ancak ciddi MY, MS, ileri MAC, protez/TEER ve kötü Doppler kalitesinde yanıltıcı olabilir.

**LARS:** Ölçüm güvenilirse ≤18% değeri kronik LAP artışı lehine güçlü destek sağlar.

**AF:** A dalgası olmadığı için E/A ve klasik gradeleme yerine LAP tahmini yapılır.
"""
        )


# =========================================================
# ===================== EKRAN 4: AV TAM BLOK - İLETİ SİSTEMİ PACING ==
# =========================================================
elif menu == "🫀 AV tam blok-ileti sistemi pacing":
    require_password_gate()

    st.header("🫀 AV tam blok-ileti sistemi pacing (LBBAP / HBP)")
    st.caption("AV tam blok nedeniyle ileti sistemi pacing yapılan hastalarda klinik + RV + LV/LA parametreleri.")

    dfp = load_data(SHEET_ID, PACED_WS_INDEX, required_col="KayıtID")

    col_left, col_right = st.columns([2, 3])

    with col_left:
        st.markdown("##### ⚙️ İşlem Seçimi")
        mode = st.radio(
            "Mod:",
            ["Yeni Kayıt", "Düzenleme", "Kontrol Hasta"],
            horizontal=True,
            label_visibility="collapsed",
            key="pacing_mode",
        )

        current = {}
        if mode == "Düzenleme" and not dfp.empty and "KayıtID" in dfp.columns:
            edit_key = st.selectbox("Düzenlenecek KayıtID", dfp["KayıtID"].unique(), key="pacing_edit_key")
            if edit_key:
                current = dfp[dfp["KayıtID"] == edit_key].iloc[0].to_dict()
                st.success(f"Seçildi: {current.get('Dosya Numarası','')} | {current.get('Ziyaret','')}")
        elif mode == "Düzenleme":
            st.warning("Düzenlenecek kayıt yok.")
        elif mode == "Kontrol Hasta":
            st.info("Kayıtlı hasta listesinden hasta seçip sadece kontrol eko parametrelerini girebilirsin.")

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

                cols_show = [
                    c for c in ["KayıtID", "Dosya Numarası", "Ziyaret", "Tarih", "Hekim", "Pacing Tipi"]
                    if c in show.columns
                ]
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

    def gs(k): return str(current.get(k, ""))
    def gf(k):
        try:
            return float(current.get(k, 0))
        except Exception:
            return 0.0
    def gi(k):
        try:
            return int(float(current.get(k, 0)))
        except Exception:
            return 0
    def gc(k): return str(current.get(k, "")).lower() == "true"

    VISIT_LABELS = ["1. Başlangıç", "2. Kontrol"]
    VISIT_CODE = {"1. Başlangıç": "BASLANGIC", "2. Kontrol": "KONTROL"}

    if mode == "Kontrol Hasta":
        if dfp.empty or "Dosya Numarası" not in dfp.columns:
            st.warning("Kontrol girilecek kayıtlı hasta bulunamadı. Önce başlangıç kaydı oluştur.")
            st.stop()

        patient_source = dfp.copy()
        patient_source["Dosya Numarası"] = patient_source["Dosya Numarası"].astype(str).str.strip()
        patient_source = patient_source[patient_source["Dosya Numarası"] != ""].copy()

        if patient_source.empty:
            st.warning("Kontrol girilecek geçerli dosya numarası bulunamadı.")
            st.stop()

        patient_options = sorted(patient_source["Dosya Numarası"].unique().tolist())
        selected_patient_no = st.selectbox(
            "Kontrol verisi girilecek hasta",
            patient_options,
            key="pacing_control_patient",
        )

        patient_rows = patient_source[patient_source["Dosya Numarası"] == selected_patient_no].copy()
        if "Ziyaret" in patient_rows.columns:
            patient_rows["_visit_priority"] = patient_rows["Ziyaret"].astype(str).apply(
                lambda x: 0 if ("Başlangıç" in x or "BASLANGIC" in x.upper()) else 1
            )
            patient_rows = patient_rows.sort_values("_visit_priority")

        base_patient = patient_rows.iloc[0].to_dict()

        def bgs(k): return str(base_patient.get(k, ""))
        def bgf(k):
            try:
                return float(base_patient.get(k, 0))
            except Exception:
                return 0.0

        st.info(
            f"Seçilen hasta: **{selected_patient_no}**"
            + (f" | Pacing tipi: **{bgs('Pacing Tipi')}**" if bgs("Pacing Tipi") else "")
        )

        with st.form("pacing_control_form"):
            st.markdown("### 🫀 Kontrol Eko Parametreleri")

            cdate, chekim = st.columns(2)
            kontrol_tarihi = cdate.date_input("Kontrol Tarihi", value=datetime.now().date())
            kontrol_hekim = chekim.text_input("Kontrolü Giren Hekim (Zorunlu)", value="")

            kayit_id = f"{selected_patient_no}_KONTROL_{kontrol_tarihi.strftime('%Y%m%d')}"
            st.caption(f"🆔 KayıtID: {kayit_id}")

            def _rv_control_inputs(prefix: str, title: str) -> Dict[str, float]:
                st.markdown(f"#### RV — {title}")
                r1, r2, r3, r4 = st.columns(4)
                values = {
                    "RV FWLS (%)": r1.number_input(f"{title} RV FWLS (%)", value=0.0, key=f"pacing_ctrl_{prefix}_rv_fwls"),
                    "EndoGLS (%)": r1.number_input(f"{title} EndoGLS (%)", value=0.0, key=f"pacing_ctrl_{prefix}_endogls"),
                    "MyoGLS (%)": r1.number_input(f"{title} MyoGLS (%)", value=0.0, key=f"pacing_ctrl_{prefix}_myogls"),
                    "EDA": r2.number_input(f"{title} EDA", value=0.0, key=f"pacing_ctrl_{prefix}_eda"),
                    "ESA": r2.number_input(f"{title} ESA", value=0.0, key=f"pacing_ctrl_{prefix}_esa"),
                    "RV FAC (%)": r2.number_input(f"{title} RV FAC (%)", value=0.0, key=f"pacing_ctrl_{prefix}_rv_fac"),
                    "RV GRS (%)": r3.number_input(f"{title} RV GRS (%)", value=0.0, key=f"pacing_ctrl_{prefix}_rv_grs"),
                    "TY vel. (m/sn)": r3.number_input(f"{title} TY vel. (m/sn)", value=0.0, key=f"pacing_ctrl_{prefix}_tyvel"),
                    "RV Sm (cm/sn)": r4.number_input(f"{title} RV Sm (cm/sn)", value=0.0, key=f"pacing_ctrl_{prefix}_rvsm"),
                    "TAPSE (mm)": r4.number_input(f"{title} TAPSE (mm)", value=0.0, key=f"pacing_ctrl_{prefix}_tapse"),
                }
                st.write("")
                return values

            rv_unipolar = _rv_control_inputs("unipolar", "Unipolar mod")
            rv_bipolar = _rv_control_inputs("bipolar", "Bipolar mod")

            st.markdown("#### LV / LA")
            lv1, lv2, lv3 = st.columns(3)
            lv_gls = lv1.number_input("LV-GLS (%)", value=0.0, key="pacing_ctrl_lv_gls")
            lvedv = lv2.number_input("LVEDV (mL)", value=0.0, key="pacing_ctrl_lvedv")
            lvesv = lv2.number_input("LVESV (mL)", value=0.0, key="pacing_ctrl_lvesv")
            sv_lv = lv3.number_input("SV (mL)", value=0.0, key="pacing_ctrl_sv_lv")

            la_gls = lv1.number_input("LA-GLS (%)", value=0.0, key="pacing_ctrl_la_gls")
            laedv = lv2.number_input("LAEDV (mL)", value=0.0, key="pacing_ctrl_laedv")
            laesv = lv3.number_input("LAESV (mL)", value=0.0, key="pacing_ctrl_laesv")

            bsa_safe = bgf("BSA")
            if bsa_safe <= 0:
                boy_base = bgf("Boy")
                kilo_base = bgf("Kilo")
                bsa_safe = (boy_base * kilo_base / 3600) ** 0.5 if (boy_base > 0 and kilo_base > 0) else 0.0

            laedvi = (laedv / bsa_safe) if bsa_safe > 0 else 0.0
            laesvi = (laesv / bsa_safe) if bsa_safe > 0 else 0.0
            lavi = laesvi
            laci = (laedvi / laesvi) if laesvi > 0 else 0.0

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("LAVI (mL/m²)", f"{lavi:.1f}")
            m2.metric("LAEDVi (mL/m²)", f"{laedvi:.1f}")
            m3.metric("LAESVi (mL/m²)", f"{laesvi:.1f}")
            m4.metric("LACi (LAEDVi/LAESVi)", f"{laci:.2f}")

            submitted_control = st.form_submit_button("💾 KONTROL EKOSUNU KAYDET", type="primary")

            if submitted_control:
                if not kontrol_hekim:
                    st.error("Kontrolü giren hekim zorunlu!")
                else:
                    control_payload = {
                        "KayıtID": kayit_id,
                        "Dosya Numarası": selected_patient_no,
                        "Ziyaret": "2. Kontrol",
                        "Tarih": str(kontrol_tarihi),
                        "Hekim": kontrol_hekim,
                        "Pacing Tipi": bgs("Pacing Tipi"),
                        "Unipolar RV FWLS (%)": rv_unipolar["RV FWLS (%)"],
                        "Unipolar EndoGLS (%)": rv_unipolar["EndoGLS (%)"],
                        "Unipolar MyoGLS (%)": rv_unipolar["MyoGLS (%)"],
                        "Unipolar EDA": rv_unipolar["EDA"],
                        "Unipolar ESA": rv_unipolar["ESA"],
                        "Unipolar RV FAC (%)": rv_unipolar["RV FAC (%)"],
                        "Unipolar RV GRS (%)": rv_unipolar["RV GRS (%)"],
                        "Unipolar TY vel. (m/sn)": rv_unipolar["TY vel. (m/sn)"],
                        "Unipolar RV Sm (cm/sn)": rv_unipolar["RV Sm (cm/sn)"],
                        "Unipolar TAPSE (mm)": rv_unipolar["TAPSE (mm)"],
                        "Bipolar RV FWLS (%)": rv_bipolar["RV FWLS (%)"],
                        "Bipolar EndoGLS (%)": rv_bipolar["EndoGLS (%)"],
                        "Bipolar MyoGLS (%)": rv_bipolar["MyoGLS (%)"],
                        "Bipolar EDA": rv_bipolar["EDA"],
                        "Bipolar ESA": rv_bipolar["ESA"],
                        "Bipolar RV FAC (%)": rv_bipolar["RV FAC (%)"],
                        "Bipolar RV GRS (%)": rv_bipolar["RV GRS (%)"],
                        "Bipolar TY vel. (m/sn)": rv_bipolar["TY vel. (m/sn)"],
                        "Bipolar RV Sm (cm/sn)": rv_bipolar["RV Sm (cm/sn)"],
                        "Bipolar TAPSE (mm)": rv_bipolar["TAPSE (mm)"],
                        "LV-GLS (%)": lv_gls,
                        "LVEDV (mL)": lvedv,
                        "LVESV (mL)": lvesv,
                        "SV (mL)": sv_lv,
                        "LA-GLS (%)": la_gls,
                        "LAEDV (mL)": laedv,
                        "LAESV (mL)": laesv,
                        "LAVI (mL/m2)": lavi,
                        "LAEDVi (mL/m2)": laedvi,
                        "LAESVi (mL/m2)": laesvi,
                        "LACi": laci,
                    }
                    save_data_row(SHEET_ID, control_payload, unique_col="KayıtID", worksheet_index=PACED_WS_INDEX)
                    st.success(f"✅ Kontrol eko kaydı oluşturuldu: {kayit_id}")
                    time.sleep(0.25)
                    st.rerun()

        st.stop()

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
            except Exception:
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

            cb1, cb2, cb3, cb4 = st.columns(4)
            boy = cb1.number_input("Boy (cm)", value=gf("Boy"))
            kilo = cb2.number_input("Kilo (kg)", value=gf("Kilo"))
            bmi = kilo / ((boy / 100) ** 2) if boy > 0 else 0
            bsa = (boy * kilo / 3600) ** 0.5 if (boy > 0 and kilo > 0) else 0
            cb3.metric("BMI", f"{bmi:.1f}")
            cb4.metric("BSA", f"{bsa:.2f}")

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

        st.markdown("### 🫀 Eko / STE — RV")
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

        st.markdown("### 🫀 LV / LA")
        lv1, lv2, lv3 = st.columns(3)

        lv_gls = lv1.number_input("LV-GLS (%)", value=gf("LV-GLS (%)"))
        lvedv = lv2.number_input("LVEDV (mL)", value=gf("LVEDV (mL)"))
        lvesv = lv2.number_input("LVESV (mL)", value=gf("LVESV (mL)"))
        sv_lv = lv3.number_input("SV (mL)", value=gf("SV (mL)"))

        la_gls = lv1.number_input("LA-GLS (%)", value=gf("LA-GLS (%)"))
        laedv = lv2.number_input("LAEDV (mL)", value=gf("LAEDV (mL)"))
        laesv = lv3.number_input("LAESV (mL)", value=gf("LAESV (mL)"))

        bsa_safe = bsa if (bsa and bsa > 0) else 0.0
        laedvi = (laedv / bsa_safe) if bsa_safe > 0 else 0.0
        laesvi = (laesv / bsa_safe) if bsa_safe > 0 else 0.0
        lavi = laesvi
        laci = (laedvi / laesvi) if laesvi > 0 else 0.0

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("LAVI (mL/m²)", f"{lavi:.1f}")
        m2.metric("LAEDVi (mL/m²)", f"{laedvi:.1f}")
        m3.metric("LAESVi (mL/m²)", f"{laesvi:.1f}")
        m4.metric("LACi (LAEDVi/LAESVi)", f"{laci:.2f}")

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
                    "LV-GLS (%)": lv_gls,
                    "LVEDV (mL)": lvedv,
                    "LVESV (mL)": lvesv,
                    "SV (mL)": sv_lv,
                    "LA-GLS (%)": la_gls,
                    "LAEDV (mL)": laedv,
                    "LAESV (mL)": laesv,
                    "LAVI (mL/m2)": lavi,
                    "LAEDVi (mL/m2)": laedvi,
                    "LAESVi (mL/m2)": laesvi,
                    "LACi": laci,
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
        except Exception: return 0.0
    def gi(k):
        try: return int(float(current.get(k, 0)))
        except Exception: return 0
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
            except Exception:
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
            sx1, sx2, sx3, sx4 = st.columns(4)
            sym_dispne = sx1.checkbox("Dispne", value=gc("Semptom: Dispne"))
            sym_carpinti = sx2.checkbox("Çarpıntı", value=gc("Semptom: Çarpıntı"))
            sym_yorgunluk = sx3.checkbox("Yorgunluk", value=gc("Semptom: Yorgunluk"))
            sym_diger = sx4.text_input("Diğer", value=gs("Semptom: Diğer"))

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

        pre_sbp = int(_clamp_number(gi("TEE öncesi SBP"), min_v=50, max_v=260, default=120))
        pre_dbp = int(_clamp_number(gi("TEE öncesi DBP"), min_v=30, max_v=160, default=70))
        pre_hr  = int(_clamp_number(gi("TEE öncesi HR"),  min_v=20, max_v=220, default=80))
        tee_sbp = int(_clamp_number(gi("TEE sırasında SBP"), min_v=50, max_v=260, default=120))
        tee_dbp = int(_clamp_number(gi("TEE sırasında DBP"), min_v=30, max_v=160, default=70))
        tee_hr  = int(_clamp_number(gi("TEE sırasında HR"),  min_v=20, max_v=220, default=80))

        pre_sbp_in = h2.number_input("TEE öncesi SBP (mmHg)", min_value=50, max_value=260, step=1, value=pre_sbp)
        pre_dbp_in = h2.number_input("TEE öncesi DBP (mmHg)", min_value=30, max_value=160, step=1, value=pre_dbp)
        pre_hr_in  = h2.number_input("TEE öncesi HR (bpm)", min_value=20, max_value=220, step=1, value=pre_hr)
        tee_sbp_in = h3.number_input("TEE sırasında SBP (mmHg)", min_value=50, max_value=260, step=1, value=tee_sbp)
        tee_dbp_in = h3.number_input("TEE sırasında DBP (mmHg)", min_value=30, max_value=160, step=1, value=tee_dbp)
        tee_hr_in  = h3.number_input("TEE sırasında HR (bpm)", min_value=20, max_value=220, step=1, value=tee_hr)

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
        tte1, tte2, tte3 = st.columns(3)
        mr_deg_tte = tte1.selectbox("MR (TTE) Derece (integratif)", ["Hafif", "Orta", "İleri"],
                                  index=(["Hafif","Orta","İleri"].index(gs("MR (TTE) Derece")) if gs("MR (TTE) Derece") in ["Hafif","Orta","İleri"] else 1))
        tte_lvef = tte1.number_input("LVEF (TTE) (%)", value=gf("TTE LVEF"))
        tte_lvedv = tte2.number_input("LVEDV (TTE) (mL)", value=gf("TTE LVEDV"))
        tte_lvesv = tte2.number_input("LVESV (TTE) (mL)", value=gf("TTE LVESV"))
        tte_sv = tte2.number_input("SV (TTE) (mL)", value=gf("TTE SV"))
        tte_gls = tte3.number_input("LV-GLS (TTE) (%)", value=gf("TTE LVGLS"))
        laesv = tte3.number_input("LAESV (mL)", value=gf("LAESV"))

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

    def gs(k): return str(current.get(k, ""))
    def gf(k):
        try: return float(current.get(k, 0))
        except Exception: return 0.0
    def gi(k):
        try: return int(float(current.get(k, 0)))
        except Exception: return 0
    def gc(k): return str(current.get(k, "")).lower() == "true"

    VISIT_LABELS = ["1. Başlangıç", "2. Kontrol"]
    VISIT_CODE = {"1. Başlangıç": "BASLANGIC", "2. Kontrol": "KONTROL"}

    with st.form("cvabl_form"):
        st.markdown("### 👤 Demografi ve Klinik (AF hasta)")
        c1, c2 = st.columns(2)

        with c1:
            dosya_no = st.text_input("Dosya No (Zorunlu)", value=gs("Dosya No"))
            prev_visit = gs("Ziyaret")
            visit_ix = VISIT_LABELS.index(prev_visit) if prev_visit in VISIT_LABELS else 0
            ziyaret = st.selectbox("Ziyaret", VISIT_LABELS, index=visit_ix)

            try:
                d_date = datetime.strptime(gs("Tarih"), "%Y-%m-%d").date()
            except Exception:
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
            sx1, sx2, sx3, sx4 = st.columns(4)
            sym_dispne = sx1.checkbox("Dispne", value=gc("Semptom: Dispne"))
            sym_carpinti = sx2.checkbox("Çarpıntı", value=gc("Semptom: Çarpıntı"))
            sym_yorgunluk = sx3.checkbox("Yorgunluk", value=gc("Semptom: Yorgunluk"))
            sym_diger = sx4.text_input("Diğer", value=gs("Semptom: Diğer"))

        st.markdown("### ⚙️ İşlem Bilgisi")
        p1, p2, p3 = st.columns(3)
        islem_l = ["Elektrik Kardiyoversiyon", "Ablasyon"]
        islem_prev = gs("İşlem")
        islem_ix = islem_l.index(islem_prev) if islem_prev in islem_l else 0
        islem = p1.selectbox("İşlem", islem_l, index=islem_ix)

        try:
            d_proc = datetime.strptime(gs("İşlem Tarihi"), "%Y-%m-%d").date()
        except Exception:
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

        st.markdown("### ✅ Endpoint (basit, literatüre uygun)")

        if islem == "Ablasyon":
            primary_endpoint = "Ablasyon başarısı: 3 ay blanking sonrası atriyal taşiaritmi rekürrensi yok (AF/AFL/AT)"
            cA1, cA2, cA3 = st.columns(3)
            rec_post_blanking = cA1.checkbox(
                "Blanking sonrası rekürrens var (AF/AFL/AT)",
                value=gc("Rekürrens (blanking sonrası)")
            )
            fu_months = cA2.number_input("Takip süresi (ay)", min_value=0, max_value=60, step=1, value=gi("Takip süresi (ay)"))
            try:
                d_eval = datetime.strptime(gs("Endpoint değerlendirme tarihi"), "%Y-%m-%d").date()
            except Exception:
                d_eval = datetime.now().date()
            eval_date = cA3.date_input("Endpoint değerlendirme tarihi (ops.)", value=d_eval)
            endpoint_success = (not bool(rec_post_blanking))
            early_sr = ""
            rec_30d = ""
        else:
            primary_endpoint = "Kardiyoversiyon başarısı: 30 gün içinde AF rekürrensi yok"
            cC1, cC2, cC3 = st.columns(3)
            early_sr = cC1.checkbox("Erken başarı: SR sağlandı (işlem sonrası)", value=gc("Başarı (erken)"))
            rec_30d = cC2.checkbox("AF rekürrensi 30 gün içinde", value=gc("Rekürrens (30 gün)"))
            try:
                d_eval = datetime.strptime(gs("Endpoint değerlendirme tarihi"), "%Y-%m-%d").date()
            except Exception:
                d_eval = datetime.now().date()
            eval_date = cC3.date_input("Endpoint değerlendirme tarihi (ops.)", value=d_eval)
            endpoint_success = (not bool(rec_30d))
            fu_months = 0
            rec_post_blanking = False

        sonuc_not = st.text_input("Sonuç notu (ops.)", value=gs("Sonuç notu"))
        st.info(f"📌 Primary endpoint: {primary_endpoint}\n\n📌 Endpoint sonucu: {'BAŞARILI' if endpoint_success else 'BAŞARISIZ'}")

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

        st.markdown("### 🫀 TEE – LV-GLS (Ana değişken)")
        tee_gls = st.number_input("LV-GLS (TEE) (%)", value=gf("TEE LVGLS"))

        st.markdown("### 🫁 TTE – Karşılaştırma (yeterli set)")
        tt1, tt2, tt3 = st.columns(3)
        tte_lvef = tt1.number_input("LVEF (TTE) (%)", value=gf("TTE LVEF"))
        tte_sv = tt1.number_input("SV (TTE) (mL)", value=gf("TTE SV"))
        tte_lvedv = tt2.number_input("LVEDV (TTE) (mL)", value=gf("TTE LVEDV"))
        tte_lvesv = tt2.number_input("LVESV (TTE) (mL)", value=gf("TTE LVESV"))
        tte_laesv = tt3.number_input("LAESV (TTE) (mL)", value=gf("TTE LAESV"))
        tte_gls = tt3.number_input("LV-GLS (TTE) (%)", value=gf("TTE LVGLS"))

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
                    "Rekürrens (blanking sonrası)": rec_post_blanking,
                    "Takip süresi (ay)": fu_months,
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
                    "TEE LVGLS": tee_gls,
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
# ===================== EKRAN PBMV: RV-PA COUPLING =========
# =========================================================
elif menu == "🫁 PBMV – RV-PA Coupling":
    require_password_gate()

    st.header("🫁 PBMV – RV-PA Coupling")
    st.caption("Romatizmal mitral darlığında PBMV öncesi ve erken dönem sonrası (24–72 saat) RV–PA coupling, sağ kalp yanıtı ve işlem başarısı takibi.")

    dfm = load_data(SHEET_ID, PBMV_WS_INDEX, required_col="KayıtID")

    left, right = st.columns([2, 3])

    with left:
        st.markdown("##### ⚙️ İşlem Seçimi")
        mode = st.radio(
            "Mod:",
            ["Yeni Kayıt", "Düzenleme"],
            horizontal=True,
            label_visibility="collapsed",
            key="pbmv_mode",
        )

        current = {}
        if mode == "Düzenleme" and not dfm.empty and "KayıtID" in dfm.columns:
            edit_key = st.selectbox("Düzenlenecek KayıtID", dfm["KayıtID"].unique(), key="pbmv_edit_key")
            if edit_key:
                current = dfm[dfm["KayıtID"] == edit_key].iloc[0].to_dict()
                st.success(f"Seçildi: {current.get('Dosya No','')} | {current.get('Ziyaret','')} | {current.get('Hekim','')}")
        elif mode == "Düzenleme":
            st.warning("Düzenlenecek kayıt yok veya sheet başlığı henüz oluşmadı.")

    with right:
        with st.expander("📋 KAYITLI LİSTE / ARAMA / SİLME", expanded=True):
            if st.button("🔄 Listeyi Yenile", key="pbmv_refresh"):
                st.rerun()

            if dfm.empty:
                st.info("Kayıt yok. İlk kaydı girince başlıklar otomatik oluşur. Google Sheet içinde PBMV için yeni worksheet açıp pbmv_ws_index değerini kontrol et.")
            else:
                q = st.text_input("🔎 Arama (dosya no / hekim / ziyaret / ritim)", "", key="pbmv_search")
                show = dfm.copy()
                if q.strip():
                    mask = show.apply(lambda r: r.astype(str).str.contains(q, case=False, na=False).any(), axis=1)
                    show = show[mask].copy()

                display_df = show.copy()
                if "Adı Soyadı" in display_df.columns:
                    display_df["Adı Soyadı"] = display_df["Adı Soyadı"].apply(mask_name)
                if "İletişim" in display_df.columns:
                    display_df["İletişim"] = display_df["İletişim"].apply(mask_phone)

                cols_show = [c for c in [
                    "KayıtID", "Dosya No", "Adı Soyadı", "Tarih", "Ziyaret", "Hekim", "Ritim",
                    "NYHA", "6DYT (m)", "MVA final (cm2)", "Mean MG (mmHg)", "PASP final (mmHg)",
                    "TAPSE/PASP", "RVFWLS/PASP", "İşlem başarısı"
                ] if c in display_df.columns]
                st.dataframe(display_df[cols_show] if cols_show else display_df, use_container_width=True)

                st.divider()
                st.markdown("##### 🗑️ Silme (Şifreli)")
                if confirm_delete_with_password("pbmv"):
                    del_key = st.selectbox("Silinecek KayıtID", dfm["KayıtID"].unique(), key="pbmv_del_key")
                    if st.button("🗑️ SİL", type="secondary", key="pbmv_del_btn"):
                        if delete_row_by_value(SHEET_ID, PBMV_WS_INDEX, "KayıtID", del_key):
                            st.success("Silindi!")
                            time.sleep(0.2)
                            st.rerun()
                        else:
                            st.error("Hata!")

    st.divider()

    def gs(k): return str(current.get(k, ""))
    def gf(k):
        try: return float(current.get(k, 0))
        except Exception: return 0.0
    def gi(k):
        try: return int(float(current.get(k, 0)))
        except Exception: return 0
    def gc(k): return str(current.get(k, "")).lower() == "true"

    VISIT_LABELS = ["1. PBMV Öncesi", "2. PBMV Sonrası Erken (24-72 saat)", "3. Kontrol"]
    VISIT_CODE = {
        "1. PBMV Öncesi": "PRE",
        "2. PBMV Sonrası Erken (24-72 saat)": "POST_24_72H",
        "3. Kontrol": "KONTROL",
    }

    with st.form("pbmv_main_form"):
        st.markdown("### 👤 Demografi ve Klinik")
        c1, c2 = st.columns(2)

        with c1:
            dosya_no = st.text_input("Dosya No (Zorunlu)", value=gs("Dosya No"))
            ad_soyad = st.text_input("Adı Soyadı", value=gs("Adı Soyadı"))

            prev_visit = gs("Ziyaret")
            visit_ix = VISIT_LABELS.index(prev_visit) if prev_visit in VISIT_LABELS else 0
            ziyaret = st.selectbox("Ziyaret", VISIT_LABELS, index=visit_ix)

            try:
                d_date = datetime.strptime(gs("Tarih"), "%Y-%m-%d").date()
            except Exception:
                d_date = datetime.now().date()
            tarih = st.date_input("Değerlendirme Tarihi", value=d_date)

            kayit_id = f"{dosya_no.strip()}_{VISIT_CODE.get(ziyaret,'PRE')}_{tarih.strftime('%Y%m%d')}".strip("_")
            st.caption(f"🆔 KayıtID: {kayit_id}")

            hekim = st.text_input("Veriyi Giren Hekim (Zorunlu)", value=gs("Hekim"))
            iletisim = st.text_input("İletişim", value=gs("İletişim"))

            ritim_l = ["Sinüs", "AF", "Atriyal flutter", "Pacemaker", "Diğer"]
            ritim_prev = gs("Ritim")
            ritim = st.selectbox("Ritim", ritim_l, index=(ritim_l.index(ritim_prev) if ritim_prev in ritim_l else 0))

        with c2:
            cy, cc = st.columns(2)
            yas = cy.number_input("Yaş", step=1, value=gi("Yaş"))
            sex_l = ["Kadın", "Erkek"]
            cinsiyet = cc.radio("Cinsiyet", sex_l, index=(sex_l.index(gs("Cinsiyet")) if gs("Cinsiyet") in sex_l else 0), horizontal=True)

            cb1, cb2, cb3, cb4 = st.columns(4)
            boy = cb1.number_input("Boy (cm)", value=gf("Boy"))
            kilo = cb2.number_input("Kilo (kg)", value=gf("Kilo"))
            bmi = kilo / ((boy / 100) ** 2) if boy > 0 else 0
            bsa = (boy * kilo / 3600) ** 0.5 if (boy > 0 and kilo > 0) else 0
            cb3.metric("BMI", f"{bmi:.1f}")
            cb4.metric("BSA", f"{bsa:.2f}")

            v1, v2, v3 = st.columns(3)
            ta_sis = v1.number_input("TA Sistol (mmHg)", value=gi("TA Sistol"))
            ta_dia = v2.number_input("TA Diyastol (mmHg)", value=gi("TA Diyastol"))
            nabiz = v3.number_input("Nabız (/dk)", value=gi("Nabız"))

            nyha_l = ["I", "II", "III", "IV"]
            nyha_prev = gs("NYHA")
            nyha = st.selectbox("NYHA", nyha_l, index=(nyha_l.index(nyha_prev) if nyha_prev in nyha_l else 1))
            six_mwt = st.number_input("6DYT (m)", value=gf("6DYT (m)"))

        st.markdown("### 🧾 Öykü ve Tedavi")
        h1, h2, h3, h4 = st.columns(4)
        hx_ht = h1.checkbox("HT", value=gc("Öykü: HT"))
        hx_dm = h1.checkbox("DM", value=gc("Öykü: DM"))
        hx_kah = h2.checkbox("KAH / MI", value=gc("Öykü: KAH/MI"))
        hx_kby = h2.checkbox("KBY", value=gc("Öykü: KBY"))
        hx_koah = h3.checkbox("KOAH/Astım", value=gc("Öykü: KOAH/Astım"))
        hx_pht = h3.checkbox("Pulmoner HT öyküsü", value=gc("Öykü: Pulmoner HT"))
        hx_stroke = h4.checkbox("İnme/TIA", value=gc("Öykü: İnme/TIA"))
        hx_smoke = h4.checkbox("Sigara", value=gc("Sigara"))
        hx_other = st.text_input("Diğer öykü", value=gs("Öykü: Diğer"))

        t1, t2, t3 = st.columns(3)
        med_bb = t1.checkbox("Beta bloker", value=gc("Tedavi: BB"))
        med_diur = t1.checkbox("Diüretik", value=gc("Tedavi: Diüretik"))
        med_oac = t2.checkbox("OAK / VKA / DOAC", value=gc("Tedavi: OAK"))
        med_antiarr = t2.checkbox("Anti-aritmik", value=gc("Tedavi: Anti-aritmik"))
        med_diger = t3.text_area("Diğer ilaçlar", value=gs("Tedavi: Diğer"))

        st.markdown("### 🩸 Laboratuvar")
        l1, l2, l3, l4 = st.columns(4)
        hb = l1.number_input("Hb (g/dL)", value=gf("Hb"))
        hct = l1.number_input("Hct (%)", value=gf("Hct"))
        wbc = l1.number_input("WBC (10³/µL)", value=gf("WBC"))
        plt = l1.number_input("PLT (10³/µL)", value=gf("PLT"))

        glucose = l2.number_input("Glukoz (mg/dL)", value=gf("Glukoz"))
        urea = l2.number_input("Üre (mg/dL)", value=gf("Üre"))
        creat = l2.number_input("Kreatinin (mg/dL)", value=gf("Kreatinin"))
        egfr = l2.number_input("eGFR", value=gf("eGFR"))

        na = l3.number_input("Na (mEq/L)", value=gf("Na"))
        k_val = l3.number_input("K (mEq/L)", value=gf("K"))
        crp = l3.number_input("CRP", value=gf("CRP"))
        albumin = l3.number_input("Albümin (g/dL)", value=gf("Albümin"))

        ntprobnp = l4.number_input("NT-proBNP (pg/mL)", value=gf("NT-proBNP"))
        inr = l4.number_input("INR", value=gf("INR"))
        tsh = l4.number_input("TSH", value=gf("TSH"))

        st.markdown("### 🫀 Mitral Kapak / PBMV Başarı Parametreleri")
        m1, m2, m3, m4 = st.columns(4)
        mva_plan = m1.number_input("MVA planimetri (cm²)", value=gf("MVA planimetri (cm2)"))
        mva_pht = m1.number_input("MVA PHT (cm²)", value=gf("MVA PHT (cm2)"))
        mva_final = mva_plan if mva_plan > 0 else mva_pht
        m1.metric("MVA final", f"{mva_final:.2f} cm²")

        mean_mg = m2.number_input("Transmitral mean MG (mmHg)", value=gf("Mean MG (mmHg)"))
        max_mg = m2.number_input("Transmitral max MG (mmHg)", value=gf("Max MG (mmHg)"))
        pht_ms = m2.number_input("PHT (ms)", value=gf("PHT (ms)"))

        wilkins = m3.number_input("Wilkins skoru", value=gf("Wilkins skoru"))
        commissural_calc = m3.selectbox(
            "Komissür kalsifikasyonu",
            ["Yok", "Hafif", "Orta", "İleri"],
            index=(["Yok", "Hafif", "Orta", "İleri"].index(gs("Komissür kalsifikasyonu")) if gs("Komissür kalsifikasyonu") in ["Yok", "Hafif", "Orta", "İleri"] else 0),
        )
        mr_deg = m4.selectbox(
            "MY derecesi",
            ["Yok/Eser", "Hafif", "Orta", "Orta-ileri", "İleri"],
            index=(["Yok/Eser", "Hafif", "Orta", "Orta-ileri", "İleri"].index(gs("MY derecesi")) if gs("MY derecesi") in ["Yok/Eser", "Hafif", "Orta", "Orta-ileri", "İleri"] else 1),
        )
        sec_grade = m4.selectbox(
            "LAA/LA SEC",
            ["Yok", "Hafif", "Orta", "Yoğun", "Trombüs"],
            index=(["Yok", "Hafif", "Orta", "Yoğun", "Trombüs"].index(gs("LAA/LA SEC")) if gs("LAA/LA SEC") in ["Yok", "Hafif", "Orta", "Yoğun", "Trombüs"] else 0),
        )

        st.markdown("### 🫁 Sağ Kalp / RV–PA Coupling")
        r1, r2, r3, r4 = st.columns(4)
        tr_vmax = r1.number_input("TR Vmax (m/sn)", value=gf("TR Vmax"))
        rap = r1.number_input("RAP / IVC tahmini (mmHg)", value=gf("RAP"))
        pasp_calc = (4 * (tr_vmax ** 2) + rap) if tr_vmax > 0 else 0.0
        pasp_manual = r1.number_input("PASP/sPAP manuel (mmHg)", value=gf("PASP manuel (mmHg)"))
        pasp_final = pasp_manual if pasp_manual > 0 else pasp_calc
        r1.metric("PASP final", f"{pasp_final:.1f} mmHg")

        tapse = r2.number_input("TAPSE (mm)", value=gf("TAPSE"))
        rv_s = r2.number_input("RV S' (cm/sn)", value=gf("RV S'"))
        rv_fac = r2.number_input("RV FAC (%)", value=gf("RV FAC (%)"))
        tr_deg = r2.selectbox(
            "TY/TR derecesi",
            ["Yok/Eser", "Hafif", "Orta", "İleri"],
            index=(["Yok/Eser", "Hafif", "Orta", "İleri"].index(gs("TY/TR derecesi")) if gs("TY/TR derecesi") in ["Yok/Eser", "Hafif", "Orta", "İleri"] else 1),
        )

        rv_fwls = r3.number_input("RV FWLS (%)", value=gf("RV FWLS (%)"))
        rv_gls = r3.number_input("RV GLS (%)", value=gf("RV GLS (%)"))
        rv_eda = r3.number_input("RV EDA (cm²)", value=gf("RV EDA (cm2)"))
        rv_esa = r3.number_input("RV ESA (cm²)", value=gf("RV ESA (cm2)"))

        rv_basal = r4.number_input("RV basal çap (mm)", value=gf("RV basal çap (mm)"))
        ra_area = r4.number_input("RA alanı (cm²)", value=gf("RA alanı (cm2)"))
        rvot_acct = r4.number_input("RVOT AccT (ms)", value=gf("RVOT AccT (ms)"))
        rvot_vti = r4.number_input("RVOT VTI (cm)", value=gf("RVOT VTI (cm)"))

        tapse_pasp = (tapse / pasp_final) if pasp_final > 0 else 0.0
        rvfwls_pasp = (abs(rv_fwls) / pasp_final) if pasp_final > 0 else 0.0
        rvgls_pasp = (abs(rv_gls) / pasp_final) if pasp_final > 0 else 0.0
        rv_fac_calc = ((rv_eda - rv_esa) / rv_eda * 100) if rv_eda > 0 and rv_esa >= 0 else rv_fac

        cm1, cm2, cm3, cm4 = st.columns(4)
        cm1.metric("TAPSE/PASP", f"{tapse_pasp:.3f}")
        cm2.metric("RVFWLS/PASP", f"{rvfwls_pasp:.3f}")
        cm3.metric("RVGLS/PASP", f"{rvgls_pasp:.3f}")
        cm4.metric("FAC hesap", f"{rv_fac_calc:.1f}%")

        st.markdown("### 🫀 LV / LA / Diğer Eko")
        e1, e2, e3, e4 = st.columns(4)
        lvef = e1.number_input("LVEF (%)", value=gf("LVEF"))
        lv_gls = e1.number_input("LV GLS (%)", value=gf("LV GLS (%)"))
        lvedv = e1.number_input("LVEDV (mL)", value=gf("LVEDV (mL)"))
        lvesv = e1.number_input("LVESV (mL)", value=gf("LVESV (mL)"))

        la_ap = e2.number_input("LA AP çap (mm)", value=gf("LA AP çap (mm)"))
        laesv = e2.number_input("LAESV (mL)", value=gf("LAESV (mL)"))
        la_gls = e2.number_input("LA strain (%)", value=gf("LA strain (%)"))
        bsa_safe = bsa if bsa and bsa > 0 else 0.0
        lavi = (laesv / bsa_safe) if bsa_safe > 0 else 0.0
        e2.metric("LAVI", f"{lavi:.1f} mL/m²")

        lvot_vti = e3.number_input("LVOT VTI (cm)", value=gf("LVOT VTI (cm)"))
        sv = e3.number_input("SV (mL)", value=gf("SV (mL)"))
        av_vmax = e3.number_input("AV Vmax (m/sn)", value=gf("AV Vmax"))
        ar_deg = e3.selectbox(
            "AY derecesi",
            ["Yok/Eser", "Hafif", "Orta", "İleri"],
            index=(["Yok/Eser", "Hafif", "Orta", "İleri"].index(gs("AY derecesi")) if gs("AY derecesi") in ["Yok/Eser", "Hafif", "Orta", "İleri"] else 0),
        )

        frame_rate = e4.number_input("Strain frame rate (fps)", value=gf("Frame rate"))
        echo_quality = e4.selectbox(
            "Eko görüntü kalitesi",
            ["İyi", "Orta", "Kötü"],
            index=(["İyi", "Orta", "Kötü"].index(gs("Eko görüntü kalitesi")) if gs("Eko görüntü kalitesi") in ["İyi", "Orta", "Kötü"] else 0),
        )
        echo_note = e4.text_area("Eko notu", value=gs("Eko notu"))

        st.markdown("### ⚙️ İşlem Bilgisi ve Klinik Sonlanım")
        p1, p2, p3 = st.columns(3)
        try:
            proc_date_prev = datetime.strptime(gs("PBMV tarihi"), "%Y-%m-%d").date()
        except Exception:
            proc_date_prev = tarih
        pbmv_date = p1.date_input("PBMV tarihi", value=proc_date_prev)
        balloon_size = p1.number_input("Balon boyutu (mm)", value=gf("Balon boyutu (mm)"))


        success_auto = bool(mva_final >= 1.5 and mr_deg not in ["Orta-ileri", "İleri"])
        success_manual = p3.checkbox("İşlem başarısı (manuel)", value=(gc("İşlem başarısı") if gs("İşlem başarısı") else success_auto))
        complication = p3.selectbox(
            "Komplikasyon",
            ["Yok", "Yeni ciddi MY", "Tamponad", "Emboli", "Acil cerrahi", "Diğer"],
            index=(["Yok", "Yeni ciddi MY", "Tamponad", "Emboli", "Acil cerrahi", "Diğer"].index(gs("Komplikasyon")) if gs("Komplikasyon") in ["Yok", "Yeni ciddi MY", "Tamponad", "Emboli", "Acil cerrahi", "Diğer"] else 0),
        )
        hospital = p3.checkbox("Takipte hastaneye yatış", value=gc("Hastaneye yatış"))
        mortality = p3.checkbox("Mortalite", value=gc("Mortalite"))
        outcome_note = st.text_area("Sonuç / takip notu", value=gs("Sonuç notu"))

        st.write("")
        submitted = st.form_submit_button("💾 KAYDET / GÜNCELLE", type="primary")

        if submitted:
            if not dosya_no or not hekim:
                st.error("Dosya No ve Hekim zorunlu!")
            else:
                payload = {
                    "KayıtID": kayit_id,
                    "Dosya No": dosya_no,
                    "Adı Soyadı": ad_soyad,
                    "Tarih": str(tarih),
                    "Ziyaret": ziyaret,
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
                    "Nabız": nabiz,
                    "Ritim": ritim,
                    "NYHA": nyha,
                    "6DYT (m)": six_mwt,
                    "Öykü: HT": hx_ht,
                    "Öykü: DM": hx_dm,
                    "Öykü: KAH/MI": hx_kah,
                    "Öykü: KBY": hx_kby,
                    "Öykü: KOAH/Astım": hx_koah,
                    "Öykü: Pulmoner HT": hx_pht,
                    "Öykü: İnme/TIA": hx_stroke,
                    "Sigara": hx_smoke,
                    "Öykü: Diğer": hx_other,
                    "Tedavi: BB": med_bb,
                    "Tedavi: Diüretik": med_diur,
                    "Tedavi: OAK": med_oac,
                    "Tedavi: Anti-aritmik": med_antiarr,
                    "Tedavi: Diğer": med_diger,
                    "Hb": hb,
                    "Hct": hct,
                    "WBC": wbc,
                    "PLT": plt,
                    "Glukoz": glucose,
                    "Üre": urea,
                    "Kreatinin": creat,
                    "eGFR": egfr,
                    "Na": na,
                    "K": k_val,
                    "CRP": crp,
                    "Albümin": albumin,
                    "NT-proBNP": ntprobnp,
                    "INR": inr,
                    "TSH": tsh,
                    "MVA planimetri (cm2)": mva_plan,
                    "MVA PHT (cm2)": mva_pht,
                    "MVA final (cm2)": mva_final,
                    "Mean MG (mmHg)": mean_mg,
                    "Max MG (mmHg)": max_mg,
                    "PHT (ms)": pht_ms,
                    "Wilkins skoru": wilkins,
                    "Komissür kalsifikasyonu": commissural_calc,
                    "MY derecesi": mr_deg,
                    "LAA/LA SEC": sec_grade,
                    "TR Vmax": tr_vmax,
                    "RAP": rap,
                    "PASP hesap (mmHg)": pasp_calc,
                    "PASP manuel (mmHg)": pasp_manual,
                    "PASP final (mmHg)": pasp_final,
                    "TAPSE": tapse,
                    "RV S'": rv_s,
                    "RV FAC (%)": rv_fac,
                    "RV FAC hesap (%)": rv_fac_calc,
                    "TY/TR derecesi": tr_deg,
                    "RV FWLS (%)": rv_fwls,
                    "RV GLS (%)": rv_gls,
                    "RV EDA (cm2)": rv_eda,
                    "RV ESA (cm2)": rv_esa,
                    "RV basal çap (mm)": rv_basal,
                    "RA alanı (cm2)": ra_area,
                    "RVOT AccT (ms)": rvot_acct,
                    "RVOT VTI (cm)": rvot_vti,
                    "TAPSE/PASP": tapse_pasp,
                    "RVFWLS/PASP": rvfwls_pasp,
                    "RVGLS/PASP": rvgls_pasp,
                    "LVEF": lvef,
                    "LV GLS (%)": lv_gls,
                    "LVEDV (mL)": lvedv,
                    "LVESV (mL)": lvesv,
                    "LA AP çap (mm)": la_ap,
                    "LAESV (mL)": laesv,
                    "LAVI (mL/m2)": lavi,
                    "LA strain (%)": la_gls,
                    "LVOT VTI (cm)": lvot_vti,
                    "SV (mL)": sv,
                    "AV Vmax": av_vmax,
                    "AY derecesi": ar_deg,
                    "Frame rate": frame_rate,
                    "Eko görüntü kalitesi": echo_quality,
                    "Eko notu": echo_note,
                    "PBMV tarihi": str(pbmv_date),
                    "Balon boyutu (mm)": balloon_size,
                    "İşlem başarısı": success_manual,
                    "Komplikasyon": complication,
                    "Hastaneye yatış": hospital,
                    "Mortalite": mortality,
                    "Sonuç notu": outcome_note,
                }

                save_data_row(SHEET_ID, payload, unique_col="KayıtID", worksheet_index=PBMV_WS_INDEX)
                st.success(f"✅ Kaydedildi / güncellendi: {kayit_id}")
                time.sleep(0.25)
                st.rerun()


# =========================================================
# ===================== EKRAN Y: ÖZELLİKLİ VAKALAR =====================
# =========================================================
elif menu == "⭐ Özellikli Vakalar":
    st.header("⭐ Özellikli Vakalar")

    left, right = st.columns([1, 2])

    with left:
        with st.form("featured_form"):
            n_dosya = st.text_input("Dosya No")
            n_not = st.text_area("Not")

            submitted = st.form_submit_button("Kaydet", type="primary")
            if submitted:
                try:
                    now = datetime.now()
                    payload = {
                        "Tarih": str(now.date()),
                        "TarihSaat": now.isoformat(timespec="seconds"),
                        "Dosya No": n_dosya,
                        "Not": n_not,
                    }
                    save_data_row(SHEET_ID, payload, unique_col="TarihSaat", worksheet_index=FEATURED_WS_INDEX)
                    st.success("✅ Kaydedildi")
                    time.sleep(0.3)
                    st.rerun()
                except Exception as e:
                    st.error(f"Hata: {e}")

    with right:
        df = load_data(SHEET_ID, FEATURED_WS_INDEX, required_col="TarihSaat")
        if df.empty:
            st.info("Henüz özellikli vaka kaydı yok (veya sheet yok/başlık uyumsuz).")
        else:
            q = st.text_input("🔎 Arama (dosya no / not)", "")
            show = df.copy()
            if q.strip():
                mask = show.apply(lambda r: r.astype(str).str.contains(q, case=False, na=False).any(), axis=1)
                show = show[mask].copy()

            st.dataframe(show, use_container_width=True)

            st.divider()
            st.markdown("### 🗑️ Silme (Şifreli)")
            if confirm_delete_with_password("featured"):
                del_ts = st.selectbox("Silinecek kayıt (TarihSaat)", df["TarihSaat"].unique(), key="featured_del_ts")
                if st.button("🗑️ Sil", key="featured_del_btn", type="secondary"):
                    if delete_row_by_value(SHEET_ID, FEATURED_WS_INDEX, "TarihSaat", del_ts):
                        st.success("Silindi")
                        time.sleep(0.2)
                        st.rerun()
                    else:
                        st.error("Hata!")


# =========================================================
# ===================== EKRAN 2: CASE REPORT =====================
# =========================================================
elif menu == "📝 Case Report Takip":
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
                st.success(f"Seçildi: {mask_name(current.get('Adı Soyadı', ''))}")
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

                search_cols = [c for c in ["Dosya Numarası", "Hekim", "Tarih"] if c in show.columns]
                if q.strip() and search_cols:
                    mask = show[search_cols].apply(
                        lambda r: r.astype(str).str.contains(q, case=False, na=False).any(),
                        axis=1
                    )
                    show = show[mask].copy()

                display_df = show.copy()

                if "Adı Soyadı" in display_df.columns:
                    display_df["Adı Soyadı"] = display_df["Adı Soyadı"].apply(mask_name)

                if "İletişim" in display_df.columns:
                    display_df["İletişim"] = display_df["İletişim"].apply(mask_phone)

                cols_show = [
                    c for c in [
                        "Dosya Numarası", "Adı Soyadı", "Tarih", "Hekim", "İletişim",
                        "Yaş", "Cinsiyet", "TA Sistol", "TA Diyastol", "Homosistein"
                    ]
                    if c in display_df.columns
                ]

                st.dataframe(
                    display_df[cols_show] if cols_show else display_df,
                    use_container_width=True
                )

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
        except Exception: return 0.0
    def gi(k):
        try: return int(float(current.get(k, 0)))
        except Exception: return 0
    def gc(k): return str(current.get(k, "")).lower() == "true"

    with st.form("main_form"):
        st.markdown("### 👤 Klinik")
        c1, c2 = st.columns(2)

        with c1:
            dosya_no = st.text_input("Dosya Numarası (Zorunlu)", value=gs("Dosya Numarası"))
            ad_soyad = st.text_input("Adı Soyadı", value=gs("Adı Soyadı"))

            try:
                d_date = datetime.strptime(gs("Tarih"), "%Y-%m-%d").date()
            except Exception:
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
