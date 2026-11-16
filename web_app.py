# web_app.py
# NEÜ-KARDİYO | Streamlit + Google Sheets (CRUD)
# Not: Excel/CSV indirme YOK (isteğe göre kaldırıldı)

import hashlib
import json
import re
import tempfile
import unicodedata
from pathlib import Path
from urllib.parse import urlparse, parse_qs

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

# Ana Google Sheets (mevcut klinik modüller ve soru bankası) — DEĞİŞTİRMEYİN.
SHEET_ID = "1_Jd27n2lvYRl-oKmMOVySd5rGvXLrflDCQJeD_Yz6Y4"

# İkinci Google Sheets — yalnızca fotoğraf ve video soruları.
# Yeni dosyanızın URL'sinde /d/ ile /edit arasındaki değeri buraya girin.
# Bu ID gizli anahtar değildir; servis hesabının JSON bilgileri Secrets'ta kalır.
MEDIA_SHEET_ID = "1nrAcMsjEpYmhWThlA5XfKfmCykJ_2w8zCaE00iTaXGI"
MEDIA_PHOTO_TAB = "Fotograflar"
MEDIA_VIDEO_TAB = "Videolar"
def _sheet_index(key, default):
    try:
        return int(st.secrets.get(key, default))
    except FileNotFoundError:
        return default


DATA_WS_INDEX = _sheet_index("data_ws_index", 0)         # H-Type HT
CASE_WS_INDEX = _sheet_index("case_ws_index", 1)         # Case Report
LETTER_WS_INDEX = _sheet_index("letter_ws_index", 2)     # Editöre mektup
PACED_WS_INDEX = _sheet_index("paced_ws_index", 3)       # Fizyolojik pacing
AFMR_WS_INDEX = _sheet_index("afmr_ws_index", 4)         # AFMR
CVABL_WS_INDEX = _sheet_index("cvabl_ws_index", 5)       # Kardiyoversiyon-Ablasyon / TEE-GLS
PBMV_WS_INDEX = _sheet_index("pbmv_ws_index", 7)         # PBMV – RV-PA Coupling
FEATURED_WS_INDEX = _sheet_index("featured_ws_index", 6) # Özellikli Vakalar
QUESTION_WS_INDEX = _sheet_index("question_ws_index", 8) # Soru Bankası

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


def get_ws(sheet_id: str, worksheet_index):
    """Mevcut sayısal sekme indeksleri ve yeni isimli medya sekmeleri."""
    client = connect_to_gsheets()
    sh = client.open_by_key(sheet_id)
    if isinstance(worksheet_index, str):
        return sh.worksheet(worksheet_index)
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



def _media_sheet_is_configured():
    return bool(MEDIA_SHEET_ID.strip() and MEDIA_SHEET_ID != "YENI_SHEETS_ID_BURAYA")


def _media_link(value):
    """Do not render arbitrary file paths / unsafe URL schemes from Sheets."""
    url = str(value or "").strip()
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"https", "http"} or not parsed.netloc:
        return ""
    return url


def _drive_file_id(url):
    """Extract Drive file id only from standard share URLs."""
    parsed = urlparse(url)
    if parsed.hostname not in {"drive.google.com", "www.drive.google.com"}:
        return None
    match = re.search(r"/file/d/([A-Za-z0-9_-]{10,})", parsed.path)
    if match:
        return match.group(1)
    file_id = parse_qs(parsed.query).get("id", [None])[0]
    if file_id and re.fullmatch(r"[A-Za-z0-9_-]{10,}", file_id):
        return file_id
    return None


def _show_question_media(row, kind):
    """Show the image/video from the second Google Sheets before answer options."""
    keys = ("GorselURL", "GörselURL", "FotoURL", "ResimURL", "MedyaURL") if kind == "photo" else ("VideoURL", "MedyaURL")
    raw = next((str(row.get(key, "")).strip() for key in keys if str(row.get(key, "")).strip()), "")
    if not raw:
        st.info("Bu soruya henüz medya bağlantısı eklenmemiş.")
        return
    url = _media_link(raw)
    if not url:
        st.warning("Medya bağlantısı geçersiz. Google Sheets'te https:// ile başlayan bir URL kullanın.")
        return
    drive_id = _drive_file_id(url)
    try:
        if kind == "photo":
            view_url = f"https://drive.google.com/thumbnail?id={drive_id}&sz=w1600" if drive_id else url
            st.image(view_url, caption="Soruyla ilgili görüntü", use_container_width=True)
        elif drive_id:
            # Standard Drive /view URL cannot be passed directly into st.video.
            components.iframe(f"https://drive.google.com/file/d/{drive_id}/preview", height=475, scrolling=False)
            st.caption("Drive videosunun oynatılması dosyanın paylaşım iznine bağlıdır. Döngüsel oynatma Drive oynatıcısında garanti edilemez.")
        else:
            # Direct MP4/WebM URLs can repeat with Streamlit's native player.
            # YouTube / other providers may have their own playback behavior.
            st.video(url, loop=True)
    except Exception:
        st.warning("Medya gösterilemedi. Bağlantıyı ve dosyanın görüntülenme iznini kontrol edin.")
        st.markdown(f"[Medya bağlantısını aç]({url})")


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
            ws.update_cell(1, len(headers), flag_col)

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

            else:
                return False

        ws.update_cell(selected_row_idx, flag_col_idx, "Soru düzelt")
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


# ===================== ANATOMİK SORU ATLASI =====================
# Yalnızca Anatomi/Kategori/Soru üzerinden eşleştir. Şıkları ve yanıtı konu etiketi sayma.
_ATLAS_TERMS = {
    "mitral": r"\b(?:mitral\w*|miytral\w*)\b",
    "laa": r"\b(?:laa|sol (?:atrial|atriyal|atrium|atriyum|aurikul\w*) (?:apend\w*|append\w*|kulakc\w*)|left atrial append\w*|sol atriyal aurikul\w*)\b",
    "hepatic": r"\b(?:hepat(?:ik|ic) (?:vein\w*|ven\w*|toplardamar\w*)|karaciger ven\w*)\b",
    "aortic_valve": r"\b(?:aort(?:ik|ic)? (?:kapa\w*|val[vf]\w*|darl\w*|steno\w*|yet\w*|reg[uü]\w*)|(?:bikuspi[dt]|trikuspi[dt]|bicuspi[dt]|tricuspi[dt]) aort(?:ik|ic)?(?: (?:val[vf]\w*|kapa\w*))?|tavi|tavr)\b",
    "tricuspid": r"\b(?:trikuspi[dt]\w*|tricuspi[dt]\w*)\b",
    "pulmonary_valve": r"\b(?:pulmon(?:er|ary|ic|ik) (?:kapa\w*|valv\w*|darl\w*|steno\w*|yet\w*|regu\w*))\b",
    "aorta": r"\b(?:aort\w*|arkus aorta|ascending aorta|sinotubuler\w*|valsalva sinus\w*)\b",
    "lv": r"\b(?:sol ventrik\w*|left ventric\w*|lvef|lvot)\b",
    "rv": r"\b(?:sag ventrik\w*|right ventric\w*|tapse|rvot|rvfwls)\b",
    "la": r"\b(?:sol atri(?:y?um|al|yal)\w*|left atri(?:um|al)\w*)\b",
    "ra": r"\b(?:sag atri(?:y?um|al|yal)\w*|right atri(?:um|al)\w*)\b",
    "pa": r"\b(?:pulmon(?:er|ary) (?:arter\w*|trun[kc]\w*)|ana pulmoner arter\w*|truncus pulmonalis)\b",
    "pv": r"\b(?:pulmon(?:er|ary) (?:ven\w*|vein\w*)|pulmonal ven\w*)\b",
    "svc": r"\b(?:v(?:ena)? [kc]a[vw]a sup\w*|superior vena cava|svc|vks|vcs)\b",
    "ivc": r"\b(?:v(?:ena)? [kc]a[vw]a inf\w*|inferior vena cava|ivc|vki|vci)\b",
    "coronary": r"\b(?:koroner(?! sinus| kusp| yaprak)\w*|coronary(?! sinus| cusp)|lad|sirkumfleks\w*|circumflex\w*|on inen arter\w*)\b",
}
_ATLAS_PATTERNS = {key: re.compile(pattern) for key, pattern in _ATLAS_TERMS.items()}
_ATLAS_SHORT_TAGS = {"mr": "mitral", "my": "mitral", "tr": "tricuspid", "ty": "tricuspid",
                     "as": "aortic_valve", "ay": "aortic_valve", "ad": "aortic_valve",
                     "lv": "lv", "rv": "rv", "ra": "ra", "la": "la"}

def _atlas_text(value):
    if pd.isna(value):
        return ""
    return str(value).strip()

def _atlas_fold(value):
    text = unicodedata.normalize("NFKD", _atlas_text(value).casefold().replace("ı", "i"))
    return re.sub(r"[^a-z0-9]+", " ", "".join(c for c in text if not unicodedata.combining(c))).strip()

def _atlas_topics(value, *, as_tags=False):
    normalized = _atlas_fold(value)
    if not normalized:
        return set()
    topics = set()
    if as_tags:
        for part in re.split(r"[,;|/\n]+", _atlas_text(value)):
            code = part.strip().casefold()
            if code in _ATLAS_TERMS:
                topics.add(code)
            elif code in _ATLAS_SHORT_TAGS:
                topics.add(_ATLAS_SHORT_TAGS[code])
    # Consume the more specific phrase before matching its containing structure.
    for key in ("aortic_valve", "laa"):
        pattern = _ATLAS_PATTERNS[key]
        if pattern.search(normalized):
            topics.add(key)
            normalized = pattern.sub(" ", normalized)
    topics.update(key for key, pattern in _ATLAS_PATTERNS.items() if pattern.search(normalized))
    return topics

def _atlas_bank(df):
    """Only valid active questions are sent to the student component."""
    banks, lookup = {}, {}
    if not {"SoruID", "Aktif", "Soru", "Dogru"}.issubset(df.columns):
        return banks, lookup, "schema" if len(df.columns) else "unavailable"
    tag_cols = [c for c in df.columns if _atlas_fold(c) in {"anatomi", "anatomik yapi", "anatomikyapi", "anatomik bolge", "yapi"}]
    for row in df.to_dict("records"):
        if _atlas_fold(row.get("Aktif")) not in {"1", "true", "evet", "yes", "aktif"}:
            continue
        stem, sheet_id = (_atlas_text(row.get(col)) for col in ("Soru", "SoruID"))
        tags = ";".join(_atlas_text(row[c]) for c in tag_cols if _atlas_text(row[c]))
        if tags:
            topics = _atlas_topics(tags, as_tags=True)
        else:
            topics = _atlas_topics(row.get("Kategori"), as_tags=True) or _atlas_topics(stem)
        if not stem or not sheet_id or not topics:
            continue
        options = []
        for letter in "ABCDE":
            value = re.sub(r"^" + letter + r"\s*[.):\-]\s*", "", _atlas_text(row.get(letter)), flags=re.I).strip()
            if value:
                options.append([letter, value])
        correct = _atlas_text(row.get("Dogru")).upper()
        if len(options) < 2 or correct not in {letter for letter, _ in options}:
            continue
        identity = json.dumps([sheet_id, stem, options, correct], ensure_ascii=False)
        uid = "s-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        if uid in lookup:
            # Two indistinguishable duplicate rows may legitimately carry different labels.
            known = {k for k in topics if any(q["id"] == uid for q in banks.get(k, []))}
            topics -= known
        source = _atlas_text(row.get("Kaynak"))
        entry = {"id": uid, "stem": stem, "options": options, "key": correct, "why": _atlas_text(row.get("Aciklama")),
                 "source": [source, source if re.fullmatch(r"https?://\S+", source, re.I) else ""]}
        lookup[uid] = (sheet_id, stem)
        for topic in topics:
            banks.setdefault(topic, []).append(entry)
    return banks, lookup, "ready"

_ATLAS_HTML = r'''<!doctype html>
<html lang="tr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Kalp atlası · NEÜ Kardiyoloji</title>
  <style>
    :root{color-scheme:light;--ink:#173a38;--mute:#526762;--paper:#f5f3eb;--line:#d9dfd4;--green:#176c54;--pink:#b1695a;--serif:"Source Serif 4","STIX Two Text",Georgia,serif;--sans:Inter,"Segoe UI",Arial,sans-serif}
    *{box-sizing:border-box}
    html,body{padding:0;margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);-webkit-font-smoothing:antialiased}
    .atlas{max-width:1290px;margin:auto;padding:clamp(14px,3.2vw,46px)}
    header{display:flex;align-items:center;justify-content:space-between;gap:12px;border-bottom:1px solid #c9d1c6;padding-bottom:15px}
    .brand{font-size:12px;font-weight:700;letter-spacing:.13em;display:flex;align-items:center;gap:9px;color:#274e44}
    .brand svg{width:29px;height:25px}.header-section{font-size:12px;color:var(--mute);font-weight:550}
    .intro{display:flex;justify-content:space-between;align-items:end;gap:20px;padding:23px 0 20px}
    h1,h2,h3,p{margin:0}h1,h2,h3{font-weight:500}
    h1{font-family:var(--serif);font-size:clamp(37px,4.3vw,60px);letter-spacing:-.058em;line-height:1.04}
    .intro p{font-size:14px;color:var(--mute);line-height:1.5;margin-top:8px}
    .course{flex:none;width:155px;text-align:right}
    #course-label{font-size:12px;color:var(--mute);font-weight:570}
    .track{height:4px;background:#dce2d7;border-radius:9px;overflow:hidden;margin-top:8px}
    #course-fill,#q-fill{height:100%;display:block;border-radius:inherit;background:#528875;transition:width .2s}
    main{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(300px,.88fr);gap:16px;align-items:start}
    .model{border-radius:15px;background:#19343b;border:1px solid #1b3b40;color:#edf3e9;overflow:hidden}
    .panel-head{padding:19px 21px 0;display:flex;align-items:center;justify-content:space-between;gap:8px}
    .panel-head h2,.right-kicker,.mini-head{font-size:11px;font-weight:700;letter-spacing:.105em;text-transform:uppercase}
    .panel-head h2{color:#d0ded6}
    .phase{display:flex;align-items:center;gap:6px;color:#c3d3cf;font-size:11px}
    #beat-indicator{width:7px;height:7px;border-radius:50%;background:#99d5b3}
    .views{display:flex;gap:5px;margin:14px 19px 3px;flex-wrap:wrap;position:relative;z-index:1}
    button,select{font:inherit}button{cursor:pointer}button:focus-visible,select:focus-visible,[tabindex]:focus-visible,a:focus-visible{outline:3px solid #e69a46;outline-offset:3px}
    .views button,.tools button{border:1px solid #496169;background:transparent;color:#d4dfdc;border-radius:6px;font-size:12px;font-weight:530;padding:7px 10px}
    .views button:hover,.tools button:hover{background:#315054}.views button[aria-pressed=true]{background:#d3e8d8;border-color:#d3e8d8;color:#183c32}
    .viewport{position:relative;isolation:isolate;height:clamp(345px,34vw,430px);overflow:hidden;touch-action:none;cursor:grab;background:radial-gradient(ellipse at 49% 46%,#354a4c 0,#213d42 47%,#19343b 75%)}
    .viewport::before{content:"";position:absolute;inset:0;pointer-events:none;opacity:.35;background-image:radial-gradient(#8ba6a1 .7px,transparent .85px);background-size:17px 17px;mask-image:radial-gradient(ellipse at 50% 48%,#000 12%,transparent 82%)}
    .grabbing{cursor:grabbing}.viewport canvas{display:block;position:absolute;inset:0;width:100%;height:100%;pointer-events:none}
    .tools{border-top:1px solid #385258;display:flex;align-items:center;justify-content:space-between;gap:9px;padding:11px 15px;flex-wrap:wrap}
    .toolgroup{display:flex;align-items:center;gap:5px}
    .tools button{min-width:32px;min-height:30px;padding:5px 9px}
    .tools button[aria-pressed=true]{color:#d6f0de;background:#2f5053;border-color:#5d7e78}
    .sign{font-size:16px!important;line-height:1}
    .right{background:#fffef9;border:1px solid var(--line);border-radius:15px;padding:clamp(17px,2.1vw,30px);min-width:0}
    .right-top{display:flex;align-items:center;justify-content:space-between;gap:9px;margin-bottom:12px}
    .right-kicker{color:#566e63}.source-badge{color:#6c5b44;font-size:11px;background:#f5eee0;border:1px solid #e8decb;border-radius:5px;padding:4px 7px}
    .source-badge.bank{color:#2e6b57;background:#edf6ed;border-color:#cbded0}
    .select-wrap{position:relative;display:block;margin:0 0 16px;max-width:100%}
    .select-wrap:after{content:"⌄";position:absolute;right:9px;top:50%;transform:translateY(-58%);color:#467467;font-size:21px;pointer-events:none}
    select{appearance:none;width:100%;cursor:pointer;background:transparent;border:0;border-bottom:1px solid #cbd6ca;border-radius:0;color:#214a3c;font-family:var(--serif);font-size:clamp(24px,2.4vw,35px);letter-spacing:-.04em;padding:0 33px 8px 0;line-height:1.2}
    select option,select optgroup{font:15px var(--sans);color:#173a38}
    .meter-label{display:flex;justify-content:space-between;gap:10px;font-size:11px;color:var(--mute);font-weight:550;font-variant-numeric:tabular-nums}
    #qmeter{height:3px;margin:7px 0 17px}
    .question{font-family:var(--serif);font-size:clamp(19px,1.75vw,24px);letter-spacing:-.02em;line-height:1.32;color:#182e2b;margin:0 0 15px;overflow-wrap:anywhere}
    .options{display:grid;gap:7px}
    .opt{display:flex;align-items:center;gap:10px;text-align:left;border:1px solid #d6dfd4;background:#fcfcf6;border-radius:7px;color:#30463e;min-height:39px;padding:7px 10px;font-size:13px;line-height:1.4;overflow-wrap:anywhere}
    .opt:hover:not(:disabled){border-color:#70937f;background:#f3f7ef}
    .opt[aria-pressed=true]{border-color:#4e8773;background:#eaf3e9}
    .opt:disabled{cursor:default;opacity:1}.opt.correct{background:#e2f2e4;border-color:#73a985}.opt.wrong{background:#fcf0e9;border-color:#c89177}
    .letter{border:1px solid #c8d3c8;border-radius:4px;display:grid;place-items:center;flex:none;width:23px;height:23px;font-size:11px;font-weight:700;background:#fffdfa;color:#506457}
    .correct .letter{background:#267253;color:white;border-color:#267253}.wrong .letter{background:#995b48;color:white;border-color:#995b48}
    .primary{background:#1e654e;color:#fff;border:1px solid #1e654e;border-radius:7px;font-weight:600;font-size:13px;min-height:40px;width:100%;margin-top:13px;padding:8px 12px}
    .primary:hover:not(:disabled){background:#15533e}.primary:disabled{background:#dce6dc;color:#50675b;border-color:#d7e1d5;cursor:default}
    .feedback{border-left:3px solid #669d83;padding:0 0 0 12px;margin-top:15px;font-size:13px;color:#475c51;line-height:1.48;overflow-wrap:anywhere}
    .feedback.negative{border-left-color:#bc8167}.feedback strong{display:block;color:#254f3c;margin-bottom:4px}.negative strong{color:#8c503d}
    .feedback a,.reference{display:inline-block;color:#346456;font-size:11px;margin-top:6px}
    .actions{display:flex;align-items:center;justify-content:space-between;gap:9px;margin-top:10px}
    .text-button{background:none;border:none;font-size:11px;color:#4c6c60;text-decoration:underline;text-underline-offset:3px;padding:4px 0}
    .flag-status,.bank-notice{color:#5d6b63;font-size:12px;line-height:1.45}.flag-status{margin-top:5px}
    .bank-notice{margin:12px 0 0}.model-foot{display:flex;justify-content:space-between;gap:8px;align-items:start;margin:9px 2px 0;line-height:1.45;font-size:11px;color:var(--mute)}
    .model-foot strong{font-weight:600;color:#465f51}.mobile-back{display:none}
    .end{min-height:145px;display:flex;flex-direction:column;justify-content:center;gap:9px}.end h3{font:32px var(--serif);color:#28533f}.end p{color:#50665b}
    .sr{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
    [hidden]{display:none!important}
    @media(max-width:740px){
      .atlas{padding:13px}.intro{padding:17px 0 15px;gap:11px}.course{width:111px}main{grid-template-columns:minmax(0,1fr);gap:13px}
      .viewport{height:335px}.right{padding:17px}.right-top{margin-bottom:9px}.mobile-back{display:inline-block}.model-foot{font-size:10px}
      .intro p{font-size:12px;max-width:280px}.brand,.header-section{font-size:10px}.panel-head{padding:14px 15px 0}.views{margin:11px 14px 0}
      .tools{padding:8px 10px}.right{scroll-margin-top:8px}
    }
    @media(max-width:370px){.atlas{padding:8px}.course{width:82px}.views button{padding:6px 8px}.tools{gap:5px}.tools button{font-size:11px;min-width:28px;padding:5px 7px}.viewport{height:305px}}
    @media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;transition:none!important}}
  </style>
</head>
<body>
<div class="atlas">
  <header><span class="brand"><svg viewBox="0 0 32 27" fill="none" aria-hidden="true"><path d="M2 15h6l4-10 5 18 4-12 3 4h6" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>NEÜ KARDİYOLOJİ</span><span class="header-section">Soru bankası</span></header>
  <div class="intro"><div><h1>Kalp atlası</h1><p>Kalbi sürükleyerek döndürün. Bir yapıya dokunup sorusunu çözün.</p></div><div class="course"><span id="course-label"></span><div class="track"><i id="course-fill"></i></div></div></div>
  <main>
    <section aria-label="Etkileşimli anatomik model">
      <div class="model">
        <div class="panel-head"><h2>Anatomik görünüm</h2><span class="phase"><i id="beat-indicator"></i><span id="phase">Diyastol</span></span></div>
        <div class="views" role="group" aria-label="Model görünümü">
          <button data-view="front" aria-pressed="true">Ön</button><button data-view="back" aria-pressed="false">Arka</button><button data-view="valves" aria-pressed="false">Kapak düzlemi</button><button data-view="inferior" aria-pressed="false">Alt</button>
        </div>
        <div id="viewport" class="viewport" tabindex="0" role="group" aria-label="Döndürülebilen kalp modeli. Ok tuşlarıyla döndürün veya sorular için yapı listesini kullanın."><canvas id="heart"></canvas><canvas id="overlay" aria-hidden="true"></canvas></div>
        <div class="tools"><div class="toolgroup"><button id="motion" type="button">Durdur</button><button id="guides" type="button" aria-pressed="true">Etiketler</button></div><div class="toolgroup"><button class="sign" id="zoom-out" aria-label="Uzaklaştır">−</button><button class="sign" id="zoom-in" aria-label="Yakınlaştır">+</button><button id="home" title="Geçerli görünümün başlangıç açısına dön">Açıyı sıfırla</button></div></div>
      </div>
      <div class="model-foot"><span><strong>3B + zaman</strong> · Şematik kalp döngüsü</span><span>16 seçilebilir yapı</span></div>
    </section>
    <section class="right" id="quiz" aria-label="Seçilen yapının soruları">
      <div class="right-top"><span class="right-kicker">Seçilen yapı</span><span class="source-badge" id="source"></span></div>
      <label class="select-wrap"><span class="sr">Anatomik yapı seç</span><select id="region"></select></label>
      <div class="meter-label"><span id="q-index"></span><span id="score"></span></div><div class="track" id="qmeter"><i id="q-fill"></i></div>
      <div id="exercise"><h2 class="question" id="stem"></h2><div class="options" id="choices" role="group" aria-labelledby="stem"></div><div id="feedback" class="feedback" role="status" hidden></div></div>
      <div class="end" id="complete" hidden><h3>Bu yapı tamamlandı.</h3><p id="result"></p></div>
      <button class="primary" id="submit" type="button">Yanıtı kontrol et</button>
      <div class="actions"><button class="text-button mobile-back" id="to-model">↑ Modele dön</button><button class="text-button" id="flag" hidden>Soruyu düzeltme için bildir</button></div><p class="flag-status" role="status" id="flag-status"></p>
    </section>
  </main>
  <p class="bank-notice" id="bank-note"></p>
</div>
<script>
'use strict';
const CATALOG={"regions":[{"id":"aorta","name":"Aorta","short":"Aorta","group":"Büyük damarlar","view":"front"},{"id":"mitral","name":"Mitral kapak","short":"Mitral kapak","group":"Kapaklar","view":"valves"},{"id":"laa","name":"Sol atriyal apendiks","short":"Sol atriyal apendiks","group":"Kalp boşlukları","view":"front"},{"id":"hepatic","name":"Hepatik venler","short":"Hepatik venler","group":"Büyük damarlar","view":"inferior"},{"id":"aortic_valve","name":"Aort kapağı","short":"Aort kapağı","group":"Kapaklar","view":"valves"},{"id":"tricuspid","name":"Triküspit kapak","short":"Triküspit","group":"Kapaklar","view":"valves"},{"id":"pulmonary_valve","name":"Pulmoner kapak","short":"Pulmoner kapak","group":"Kapaklar","view":"valves"},{"id":"lv","name":"Sol ventrikül","short":"Sol ventrikül","group":"Kalp boşlukları","view":"front"},{"id":"rv","name":"Sağ ventrikül","short":"Sağ ventrikül","group":"Kalp boşlukları","view":"front"},{"id":"la","name":"Sol atriyum","short":"Sol atriyum","group":"Kalp boşlukları","view":"back"},{"id":"ra","name":"Sağ atriyum","short":"Sağ atriyum","group":"Kalp boşlukları","view":"front"},{"id":"pa","name":"Pulmoner arter","short":"Pulmoner arter","group":"Büyük damarlar","view":"front"},{"id":"pv","name":"Pulmoner venler","short":"Pulmoner venler","group":"Büyük damarlar","view":"back"},{"id":"svc","name":"Vena kava superior","short":"V. kava superior","group":"Büyük damarlar","view":"front"},{"id":"ivc","name":"Vena kava inferior","short":"V. kava inferior","group":"Büyük damarlar","view":"inferior"},{"id":"coronary","name":"Koroner arterler","short":"Koroner arterler","group":"Koroner dolaşım","view":"front"}],"samples":{"aorta":[{"id":"demo-aorta-1","stem":"Çıkan aortadan arkusa ilerlerken tipik sol aort arkının ilk dalı hangisidir?","options":[["A","Sol ana karotis arter"],["B","Brakiyosefalik trunkus"],["C","Sol subklavyen arter"],["D","Sağ koroner arter"]],"key":"B","why":"Arkusun tipik dal sırası brakiyosefalik trunkus, sol ana karotis ve sol subklavyen arterdir. Koroner arterler daha proksimalde, aort kökünden çıkar.","source":["OpenStax · Sistemik dolaşım","https://openstax.org/books/anatomy-and-physiology/pages/20-5-circulatory-pathways"]},{"id":"demo-aorta-2","stem":"Normal bir aort kökünde koroner ostiyumlar hangi düzeyde yer alır?","options":[["A","Sinotübüler bileşkenin belirgin distalinde"],["B","Anulusun ventriküler yüzünde"],["C","Sağ ve sol Valsalva sinüslerinde"],["D","Arkusun küçük kurvaturunda"]],"key":"C","why":"Sağ ve sol koroner arterler karşılık gelen aort sinüslerinden köken alır. Üçüncü sinüs nonkoroner sinüstür.","source":["OpenStax · Sistemik dolaşım","https://openstax.org/books/anatomy-and-physiology/pages/20-5-circulatory-pathways"]}],"mitral":[{"id":"demo-mitral-1","stem":"3B TEE’nin cerrahi görünümünde posterior mitral yaprakçığın ortasındaki prolabe segment nasıl adlandırılır?","options":[["A","A2"],["B","P1"],["C","P2"],["D","P3"]],"key":"C","why":"Posterior yaprakçığın orta tarağı P2’dir. Karşısında anterior yaprakçığın A2 bölgesi bulunur.","source":["BSE · Mitral kapak değerlendirmesi","https://doi.org/10.1530/ERP-20-0034"]},{"id":"demo-mitral-2","stem":"Marjinal kordası kopan bir mitral segmentte sistolde hangi hareket beklenir?","options":[["A","Serbest kenarın sol atriyuma dönmesi"],["B","Anulusun aortaya doğru ayrılması"],["C","Diyastolde komissürlerin birleşmesi"],["D","Papiller kasın atriyuma göç etmesi"]],"key":"A","why":"Marjinal kordalar yaprakçığın serbest kenarını destekler. Destek kaybolduğunda kenar sol atriyuma dönebilir ve flail segment görülebilir.","source":["BSE · Mitral kapak değerlendirmesi","https://doi.org/10.1530/ERP-20-0034"]}],"laa":[{"id":"demo-laa-1","stem":"TEE’de sol atriyal apendiks içinde, duvarla birlikte hareket eden paralel kas bantları görülüyor. Normal anatomide bunlar nedir?","options":[["A","Moderatör bant"],["B","Korda tendinealar"],["C","Östaki kapakçığı"],["D","Pektinat kaslar"]],"key":"D","why":"Pektinat kaslar apendiksin trabeküllü iç yüzeyini oluşturur. Farklı TEE düzlemlerinde duvarla sürekliliklerini izlemek trombüs ayrımına yardımcı olur.","source":["LAA morfolojisi ve ekokardiyografik değerlendirme","https://pmc.ncbi.nlm.nih.gov/articles/PMC11285475/"]},{"id":"demo-laa-2","stem":"TEE’de görülen Coumadin sırtı, sol atriyal apendiksi hangi yapıdan ayırır?","options":[["A","Sol üst pulmoner ven"],["B","Vena kava superior"],["C","Sağ alt pulmoner ven"],["D","Koroner sinüs ostiyumu"]],"key":"A","why":"Sol lateral atriyal sırt, apendiks ağzı ile sol üst pulmoner ven arasında uzanır. Belirgin olduğunda kitleyi taklit edebilir.","source":["LAA morfolojisi ve ekokardiyografik değerlendirme","https://pmc.ncbi.nlm.nih.gov/articles/PMC11285475/"]}],"hepatic":[{"id":"demo-hepatic-1","stem":"Hepatik venlerde pulsed-wave Doppler ile sistol boyunca ters akım izleniyor. Bu bulgu en çok hangi kapak lezyonunu destekler?","options":[["A","Mitral darlığı"],["B","Ciddi triküspit yetersizliği"],["C","Pulmoner darlık"],["D","Aort yetersizliği"]],"key":"B","why":"Ciddi triküspit yetersizliğinde sistolik geri akım sağ atriyumdan hepatik venlere iletilebilir. Yorumda ritim, sağ atriyum basıncı ve diğer yetersizlik ölçütleri birlikte değerlendirilir.","source":["EACVI · Doğal kapak yetersizliklerinin değerlendirilmesi","https://doi.org/10.1093/ehjci/jeab253"]},{"id":"demo-hepatic-2","stem":"Karaciğerden çıkan kan, ana hepatik venlerden sonra önce hangi damara ulaşır?","options":[["A","Portal ven"],["B","Vena kava superior"],["C","Vena kava inferior"],["D","Pulmoner ven"]],"key":"C","why":"Hepatik venler diyaframın hemen altında vena kava inferiora açılır. Kan oradan sağ atriyuma döner.","source":["AJR · Hepatik ven anatomisi","https://doi.org/10.2214/ajr.180.6.1801583"]}],"aortic_valve":[{"id":"demo-aortic_valve-1","stem":"Normal kardiyak siklusta aort kapağını hangi basınç değişikliği açar?","options":[["A","Aort basıncının sol ventrikül basıncını aşması"],["B","Sol atriyum basıncının sol ventrikülü aşması"],["C","Sağ ventrikül basıncının pulmoner arteri aşması"],["D","Sol ventrikül basıncının aort basıncını aşması"]],"key":"D","why":"İzovolümetrik kontraksiyonun sonunda sol ventrikül basıncı aort basıncını aşınca kapak açılır ve ejeksiyon başlar.","source":["OpenStax · Kardiyak siklus","https://openstax.org/books/anatomy-and-physiology/pages/19-3-cardiac-cycle"]},{"id":"demo-aortic_valve-2","stem":"Kısa eksende normal bir triküspit aort kapağının yaprakçıkları nasıl adlandırılır?","options":[["A","Sağ koroner, sol koroner ve nonkoroner"],["B","Anterior, septal ve inferior"],["C","A1, A2 ve A3"],["D","Sağ, sol ve komissüral"]],"key":"A","why":"Aort yaprakçıklarının isimleri komşu sinüslerin koroner ostiyumlarla ilişkisine dayanır.","source":["OpenStax · Sistemik dolaşım","https://openstax.org/books/anatomy-and-physiology/pages/20-5-circulatory-pathways"]}],"tricuspid":[{"id":"demo-tricuspid-1","stem":"Triküspit kapaktan diyastolde geçen kan hangi yolu izler?","options":[["A","Sol atriyumdan sol ventriküle"],["B","Sağ ventrikülden pulmoner artere"],["C","Sağ atriyumdan sağ ventriküle"],["D","Sağ atriyumdan sol atriyuma"]],"key":"C","why":"Triküspit kapak sağ atriyum ile sağ ventrikül arasındaki atriyoventriküler kapaktır.","source":["OpenStax · Kalp anatomisi","https://openstax.org/books/anatomy-and-physiology-2e/pages/19-1-heart-anatomy"]},{"id":"demo-tricuspid-2","stem":"Triküspit kapağın hangi yaprakçığı interventriküler septuma komşudur?","options":[["A","Posterior mitral yaprakçık"],["B","Septal yaprakçık"],["C","Nonkoroner yaprakçık"],["D","Sol koroner yaprakçık"]],"key":"B","why":"Septal yaprakçık sağ ventrikülün septal tarafına tutunur. Apikal dört boşluk kesitinde bu ilişki izlenebilir.","source":["BSE · Sağ kalbin ekokardiyografik değerlendirmesi","https://doi.org/10.1530/ERP-19-0051"]}],"pulmonary_valve":[{"id":"demo-pulmonary_valve-1","stem":"Pulmoner kapak hangi iki yapı arasında bulunur?","options":[["A","Sağ ventrikül çıkış yolu ve pulmoner trunkus"],["B","Sol ventrikül çıkış yolu ve aorta"],["C","Sağ atriyum ve sağ ventrikül"],["D","Sol atriyum ve pulmoner ven"]],"key":"A","why":"Sağ ventrikülden çıkan kan pulmoner kapağı geçerek pulmoner trunkusa girer.","source":["OpenStax · Kalp anatomisi","https://openstax.org/books/anatomy-and-physiology-2e/pages/19-1-heart-anatomy"]},{"id":"demo-pulmonary_valve-2","stem":"Pulmoner kapağı triküspit kapaktan ayıran yapısal özellik hangisidir?","options":[["A","İki boşluğu birleştirmesi"],["B","Sadece diyastolde açılması"],["C","Bir septal yaprakçığının olması"],["D","Yaprakçıklarının korda ve papiller kas bağlantısı taşımaması"]],"key":"D","why":"Pulmoner kapak bir semilunar kapaktır. Yaprakçıkları korda tendinealarla papiller kaslara bağlanmaz.","source":["OpenStax · Kalp anatomisi","https://openstax.org/books/anatomy-and-physiology-2e/pages/19-1-heart-anatomy"]}],"lv":[{"id":"demo-lv-1","stem":"Normal kalpte apeksi ağırlıklı olarak hangi boşluk oluşturur?","options":[["A","Sol ventrikül"],["B","Sağ atriyum"],["C","Sağ ventrikül çıkış yolu"],["D","Sol atriyum"]],"key":"A","why":"Sol ventrikül apeksi oluşturur. Dış yüzeyde ön interventriküler oluk, iki ventrikül arasındaki sınırı izlemeye yardım eder.","source":["OpenStax · Kalp anatomisi","https://openstax.org/books/anatomy-and-physiology-2e/pages/19-1-heart-anatomy"]},{"id":"demo-lv-2","stem":"Sol ventrikül duvarının sağ ventriküle göre daha kalın olmasının temel nedeni nedir?","options":[["A","Kalp hızının daha yüksek olması"],["B","Daha fazla atım hacmi pompalaması"],["C","Sistemik dolaşımın daha yüksek basıncına karşı çalışması"],["D","Kanı daha uzun süre depolaması"]],"key":"C","why":"İki ventrikül kararlı durumda benzer atım hacmi pompalar. Sol ventrikül sistemik dolaşımın daha yüksek basıncını oluşturur.","source":["OpenStax · Kalp anatomisi","https://openstax.org/books/anatomy-and-physiology-2e/pages/19-1-heart-anatomy"]}],"rv":[{"id":"demo-rv-1","stem":"Apikal dört boşluk kesitinde moderatör bant hangi boşluğu tanımaya yardım eder?","options":[["A","Sol atriyum"],["B","Sağ ventrikül"],["C","Sol ventrikül"],["D","Sağ atriyum"]],"key":"B","why":"Moderatör bant morfolojik sağ ventrikülde septum ile anterior papiller kas bölgesini birleştirir.","source":["OpenStax · Kalp anatomisi","https://openstax.org/books/anatomy-and-physiology-2e/pages/19-1-heart-anatomy"]},{"id":"demo-rv-2","stem":"TAPSE ölçümü, sağ ventrikülün hangi hareketini örnekler?","options":[["A","Septumun çevresel deformasyonunu"],["B","Çıkış yolunun radyal genişlemesini"],["C","Sağ atriyum rezervuar fonksiyonunu"],["D","Lateral triküspit anulusun sistolik uzunlamasına yer değiştirmesini"]],"key":"D","why":"TAPSE, lateral triküspit anulusun sistolde apekse doğru hareketini ölçer. Sağ ventrikülün uzunlamasına işlevi hakkında bilgi verir.","source":["BSE · Sağ kalbin ekokardiyografik değerlendirmesi","https://doi.org/10.1530/ERP-19-0051"]}],"la":[{"id":"demo-la-1","stem":"Arka görünümde sol atriyuma giren damarlar hangi dolaşımdan kan getirir?","options":[["A","Sistemik venöz dolaşımdan"],["B","Koroner venöz dolaşımdan"],["C","Pulmoner venöz dolaşımdan"],["D","Portal dolaşımdan"]],"key":"C","why":"Pulmoner venler akciğerlerde oksijenlenen kanı sol atriyuma taşır.","source":["OpenStax · Kalp anatomisi","https://openstax.org/books/anatomy-and-physiology-2e/pages/19-1-heart-anatomy"]},{"id":"demo-la-2","stem":"Ventrikül diyastolünde sol atriyumdan çıkan kan sırasıyla hangi yapılara ulaşır?","options":[["A","Triküspit kapak ve sağ ventrikül"],["B","Mitral kapak ve sol ventrikül"],["C","Aort kapağı ve aorta"],["D","Pulmoner kapak ve pulmoner arter"]],"key":"B","why":"Sol atriyumun çıkışında mitral kapak yer alır. Kapak açıldığında kan sol ventriküle geçer.","source":["OpenStax · Kalp anatomisi","https://openstax.org/books/anatomy-and-physiology-2e/pages/19-1-heart-anatomy"]}],"ra":[{"id":"demo-ra-1","stem":"Miyokardın venöz kanının büyük bölümünü sağ atriyuma hangi yapı getirir?","options":[["A","Pulmoner trunkus"],["B","Sol üst pulmoner ven"],["C","Brakiyosefalik arter"],["D","Koroner sinüs"]],"key":"D","why":"Koroner sinüs, kalp venlerinin topladığı kanın büyük kısmını sağ atriyuma boşaltır.","source":["OpenStax · Kalp anatomisi","https://openstax.org/books/anatomy-and-physiology-2e/pages/19-1-heart-anatomy"]},{"id":"demo-ra-2","stem":"Tipik anatomide sinüs düğümü sağ atriyumun hangi damar bileşkesine yakındır?","options":[["A","Vena kava superior"],["B","Sol üst pulmoner ven"],["C","Vena kava inferior"],["D","Koroner sinüs"]],"key":"A","why":"Sinüs düğümü sağ atriyumun üst kısmında, vena kava superiorun girişine yakın yerleşir.","source":["OpenStax · Kardiyak ileti sistemi","https://openstax.org/books/anatomy-and-physiology-2e/pages/19-2-cardiac-muscle-and-electrical-activity"]}],"pa":[{"id":"demo-pa-1","stem":"Ana pulmoner arterin bifurkasyonu hangi iki dala ayrılır?","options":[["A","Sağ ve sol pulmoner venlere"],["B","Sağ ve sol pulmoner arterlere"],["C","Sağ ve sol koroner arterlere"],["D","İnen aorta ve aort arkına"]],"key":"B","why":"Pulmoner trunkus sağ ve sol pulmoner arterlere ayrılır. Bu dallar kanı ilgili akciğere taşır.","source":["OpenStax · Kalp anatomisi","https://openstax.org/books/anatomy-and-physiology-2e/pages/19-1-heart-anatomy"]},{"id":"demo-pa-2","stem":"Normal dolaşımda ana pulmoner arterdeki kanın özelliği nedir?","options":[["A","Akciğerlerden sol atriyuma dönmektedir"],["B","Aort kökünü yeni geçmiştir"],["C","Oksijen içeriği pulmoner ven kanından daha düşüktür"],["D","Karaciğerden doğrudan gelmektedir"]],"key":"C","why":"Pulmoner arter sağ ventrikülden akciğere henüz oksijenlenmemiş kan taşır.","source":["OpenStax · Kalp anatomisi","https://openstax.org/books/anatomy-and-physiology-2e/pages/19-1-heart-anatomy"]}],"pv":[{"id":"demo-pv-1","stem":"Klasik anatomide sol atriyuma ayrı ostiyumlarla açılan kaç pulmoner ven vardır?","options":[["A","İki"],["B","Üç"],["C","Altı"],["D","Dört"]],"key":"D","why":"Tipik olarak sağ ve sol akciğerden birer üst ve alt pulmoner ven gelir. Ostiyum sayısı anatomik varyantlarda değişebilir.","source":["OpenStax · Kalp anatomisi","https://openstax.org/books/anatomy-and-physiology-2e/pages/19-1-heart-anatomy"]},{"id":"demo-pv-2","stem":"Pulmoner ven Dopplerinde sistolik akımın tersine dönmesi hangi lezyonun şiddetini destekler?","options":[["A","Ciddi mitral yetersizliği"],["B","Ciddi pulmoner darlık"],["C","Triküspit darlığı"],["D","İzole aort darlığı"]],"key":"A","why":"Ciddi mitral yetersizliğinde sistolik jet ve sol atriyum basınç artışı pulmoner ven akımını tersine çevirebilir. Jet yönü ve örneklenen ven bulguyu etkiler.","source":["EACVI · Doğal kapak yetersizliklerinin değerlendirilmesi","https://doi.org/10.1093/ehjci/jeab253"]}],"svc":[{"id":"demo-svc-1","stem":"Vena kava superior hangi iki venin birleşmesiyle oluşur?","options":[["A","Sağ ve sol brakiyosefalik venler"],["B","Sağ ve sol hepatik venler"],["C","Sağ ve sol pulmoner venler"],["D","Sağ ve sol ana iliak venler"]],"key":"A","why":"Sağ ve sol brakiyosefalik venler birleşerek vena kava superioru oluşturur. Vena kava superior sağ atriyuma açılır.","source":["OpenStax · Sistemik dolaşım","https://openstax.org/books/anatomy-and-physiology/pages/20-5-circulatory-pathways"]},{"id":"demo-svc-2","stem":"Normal anatomide baş ve üst ekstremitelerin venöz kanı sağ atriyuma hangi yolla döner?","options":[["A","Koroner sinüs"],["B","Pulmoner venler"],["C","Vena kava superior"],["D","Portal ven"]],"key":"C","why":"Baş-boyun ve üst ekstremite kanı brakiyosefalik venlerden vena kava superiora ulaşır.","source":["OpenStax · Sistemik dolaşım","https://openstax.org/books/anatomy-and-physiology/pages/20-5-circulatory-pathways"]}],"ivc":[{"id":"demo-ivc-1","stem":"Subkostal uzun eksende vena kava inferioru kraniyale doğru takip ediyorsunuz. Hangi boşluğa ulaşırsınız?","options":[["A","Sol atriyum"],["B","Sağ atriyum"],["C","Sağ ventrikül"],["D","Sol ventrikül"]],"key":"B","why":"Vena kava inferior diyaframı geçerek sağ atriyumun alt bölümüne açılır.","source":["OpenStax · Sistemik dolaşım","https://openstax.org/books/anatomy-and-physiology/pages/20-5-circulatory-pathways"]},{"id":"demo-ivc-2","stem":"Spontan soluyan erişkinde vena kava inferior çapı ve inspiratuvar kollapsı birlikte hangi basıncın tahmininde kullanılır?","options":[["A","Aort diyastolik basıncı"],["B","Sol atriyum basıncı"],["C","Pulmoner kapiller kama basıncı"],["D","Sağ atriyum basıncı"]],"key":"D","why":"Kaval çap ve inspirasyonla değişimi tahmini sağ atriyum basıncına katkı sağlar. Yorumda solunum biçimi ve klinik koşullar dikkate alınır.","source":["BSE · Sağ kalbin ekokardiyografik değerlendirmesi","https://doi.org/10.1530/ERP-19-0051"]}],"coronary":[{"id":"demo-coronary-1","stem":"Ön interventriküler olukta apekse doğru seyreden koroner arter hangisidir?","options":[["A","Sirkumfleks arter"],["B","Sağ marjinal arter"],["C","Sol ön inen arter (LAD)"],["D","Posterior inen arter"]],"key":"C","why":"LAD, anterior interventriküler olukta izlenir ve seyri boyunca septal ve diyagonal dallar verir.","source":["OpenStax · Kalp anatomisi","https://openstax.org/books/anatomy-and-physiology-2e/pages/19-1-heart-anatomy"]},{"id":"demo-coronary-2","stem":"Sol ana koroner arterin tipik iki terminal dalı hangileridir?","options":[["A","LAD ve sirkumfleks arter"],["B","LAD ve sağ koroner arter"],["C","Sağ koroner ve posterior inen arter"],["D","Sirkumfleks ve sağ marjinal arter"]],"key":"A","why":"Sol ana koroner arter tipik olarak sol ön inen ve sirkumfleks arterlere ayrılır.","source":["OpenStax · Kalp anatomisi","https://openstax.org/books/anatomy-and-physiology-2e/pages/19-1-heart-anatomy"]}]}};
// Patient coordinates: +x left, +y superior, +z anterior. Dimensions are schematic.
const TAU = 2 * Math.PI;
const add = (a,b) => a.map((x,i) => x+b[i]);
const sub = (a,b) => a.map((x,i) => x-b[i]);
const scale = (a,k) => a.map(x => x*k);
const mix = (a,b,t) => a.map((x,i) => x+(b[i]-x)*t);
const unit = a => scale(a, 1/(Math.hypot(...a)||1));
const cross = (a,b) => [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]];
const clamp = (x,lo,hi) => Math.max(lo,Math.min(hi,x));
const pi = Math.PI;

// Catmull–Rom interpolation for a continuous vessel lumen and ventricular outline.
function spline(nodes,t){
  const f=clamp(t,0,1)*(nodes.length-1), i=Math.min(nodes.length-2,Math.floor(f)), s=f-i;
  const a=nodes[Math.max(i-1,0)], b=nodes[i], c=nodes[i+1], d=nodes[Math.min(i+2,nodes.length-1)];
  return b.map((v,k)=>0.5*(2*v+(-a[k]+c[k])*s+(2*a[k]-5*v+4*c[k]-d[k])*s*s+(-a[k]+3*v-3*c[k]+d[k])*s*s*s));
}
const regionIndex = Object.fromEntries(CATALOG.regions.map((r,i)=>[r.id,i+1]));
function beatPoint(p,id,phase){
  const [x,y,z]=p;
  if (['lv','rv','coronary'].includes(id)){
    const h=clamp((y+1.68)/2.35,0,1), cx=0.50*(1-h), cz=0.28*(1-h);
    const twist=phase*(0.085-0.13*h), shrink=1-phase*(0.025+0.074*Math.sin(pi*h));
    const dx=(x-cx)*shrink, dz=(z-cz)*shrink;
    return [cx+dx*Math.cos(twist)-dz*Math.sin(twist), y-phase*.13*h, cz+dz*Math.cos(twist)+dx*Math.sin(twist)];
  }
  if (['ra','la','laa'].includes(id)){
    const amount=phase*.023;
    return [x*(1+amount),y+amount*(y-.55)-.055*phase,z*(1+amount)];
  }
  if (['aorta','pa'].includes(id)){
    const near=Math.exp(-Math.pow((y-1.05)/.66,2));
    return [x*(1+.018*near*phase),y-.065*near*phase,z*(1+.027*near*phase)];
  }
  return p;
}
const palette={
  lv:'#bf6258',rv:'#b67167',ra:'#976879',la:'#ad6a72',laa:'#d98578',aorta:'#da735b',
  pa:'#5a92aa',pv:'#ce807b',ivc:'#7299ab',svc:'#7199b2',hepatic:'#79a8b6',
  coronary:'#e1ac72',mitral:'#e1b892',tricuspid:'#bdcdbc',aortic_valve:'#e1a078',pulmonary_valve:'#a8cbd4'
};
const rgb = h => [1,3,5].map(i=>parseInt(h.slice(i,i+2),16)/255);

function buildHeart(){
  const vertices=[], indices=[];
  function surface(id,layer,nu,nv,point,base=palette[id],wrap=true,customBeat=false,skipCell=null){
    const start=vertices.length/16, color=typeof base==='string'?rgb(base):base;
    for(let j=0;j<=nv;j++){
      const v=j/nv, row=[];
      for(let i=0;i<=nu;i++){
        const u=i/nu;
        row.push(point(u,v,0));
      }
      for(let i=0;i<=nu;i++){
        const u=i/nu, actualId=typeof id==='function'?id(u,v):id;
        const p=row[i], p1=customBeat?point(u,v,1):beatPoint(p,actualId,1);
        const u1=wrap?u-.001:Math.max(0,u-.001), u2=wrap?u+.001:Math.min(1,u+.001);
        const v1=Math.max(0,v-.001),v2=Math.min(1,v+.001);
        const normal=unit(cross(sub(point(u,v2,0),point(u,v1,0)),sub(point(u2,v,0),point(u1,v,0))));
        const n1=customBeat?unit(cross(sub(point(u,v2,1),point(u,v1,1)),sub(point(u2,v,1),point(u1,v,1)))):normal;
        vertices.push(...p,...p1,...normal,...n1,...color,regionIndex[actualId]+layer*32);
      }
    }
    for(let j=0;j<nv;j++) for(let i=0;i<nu;i++){
      if(skipCell&&skipCell((i+.5)/nu,(j+.5)/nv))continue;
      const k=start+j*(nu+1)+i;
      indices.push(k,k+nu+1,k+1, k+1,k+nu+1,k+nu+2);
    }
  }
  function chamber(id,center,radii,skew,color=palette[id]){
    surface(id,1,40,23,(u,v)=>{
      const a=u*TAU, b=(v-.5)*pi*.9998, h=Math.sin(b), ring=Math.cos(b);
      const relief=1+.032*Math.cos(3*a+.7)*ring+.023*Math.sin(2*b-a);
      return [center[0]+radii[0]*ring*Math.cos(a)*relief+skew*h,
        center[1]+radii[1]*h+.07*ring*Math.cos(a),
        center[2]+radii[2]*ring*Math.sin(a)*relief+.06*h];
    },color);
  }
  // A moving orthogonal frame gives each curved vessel a round section.
  function tube(id,layer,nodes,opts={}){
    const seg=opts.seg||Math.max(14,(nodes.length-1)*6), around=opts.around||18;
    const ringCache=new Map();
    function frame(t){
      if(ringCache.has(t)) return ringCache.get(t);
      const p=spline(nodes,t), tangent=unit(sub(spline(nodes,Math.min(1,t+.001)).slice(0,3),spline(nodes,Math.max(0,t-.001)).slice(0,3)));
      const ref=opts.ref||[0,0,1];
      const n=unit(cross(tangent,Math.abs(tangent[0]*ref[0]+tangent[1]*ref[1]+tangent[2]*ref[2])>.97?[0,1,0]:ref)), b=cross(n,tangent);
      const out={p,n,b}; ringCache.set(t,out); return out;
    }
    function ring(u,t,ratio=1){
      const {p,n,b}=frame(t), angle=u*TAU, radius=Math.max(.003,p[3])*ratio;
      return add(p.slice(0,3),add(scale(n,radius*Math.cos(angle)),scale(b,radius*Math.sin(angle))));
    }
    surface(id,layer,around,seg,(u,v)=>ring(u,v),opts.color||palette[id]);
    for(const end of opts.open||[]){
      const tint=rgb(opts.color||palette[id]), inward=end===1?-1:1;
      surface(id,layer,around,2,(u,v)=>ring(u,end,1-v*.25),mix(tint,[1,.84,.76],.35));
      surface(id,layer,around,3,(u,v)=>ring(u,end+inward*.075*v,.75-.12*v),scale(tint,.48));
      surface(id,layer,around,2,(u,v)=>ring(u,end+inward*.075,.63*(1-v)+.001),scale(tint,.25));
    }
  }
  const rings=[
    [.61,-1.64,.34,.026,.027], [.50,-1.48,.34,.27,.22], [.34,-1.20,.29,.53,.40],
    [.15,-.82,.21,.81,.59], [-.01,-.39,.12,1.03,.75], [-.05,.03,.075,1.15,.84],
    [-.045,.37,.035,1.15,.82], [-.025,.59,.005,1.04,.71], [-.01,.68,-.025,.91,.62]
  ];
  const vent=(t,a,offset=0)=>{
    const [x,y,z,rx,rz]=spline(rings,t), aFront=1.24+.08*Math.sin(pi*t), aBack=4.27+.13*t;
    const groove=(aa)=>Math.exp(-Math.pow(Math.atan2(Math.sin(a-aa),Math.cos(a-aa))/.12,2));
    const s=1-(.040*groove(aFront)+.036*groove(aBack))*Math.sin(pi*t);
    return [x+(rx+offset)*Math.cos(a)*s, y+.13*t*Math.cos(a)-.08*t*Math.sin(a),
            z+(rz+offset)*Math.sin(a)*(1+.025*Math.cos(3*a))*s];
  };
  const front=t=>1.24+.08*Math.sin(pi*t), back=t=>4.27+.13*t;
  surface('rv',0,39,33,(u,t)=>vent(t,front(t)+(back(t)-front(t))*u),palette.rv,false);
  surface('lv',0,45,33,(u,t)=>vent(t,back(t)+(front(t)+TAU-back(t))*u),palette.lv,false);
  // Infundibulum continuous with the anterior RV free wall.
  tube('rv',1,[[-.36,-.02,.10,.11],[-.27,.18,.22,.27],[-.17,.36,.35,.335],[-.04,.51,.44,.34],[.07,.62,.51,.322],[.13,.74,.53,.28]],{color:'#b97166',around:25});
  chamber('ra',[-.79,.69,.015],[.57,.58,.52],-.05);
  chamber('ra',[-.62,.98,.34],[.37,.205,.24],.15,'#ac7988');
  chamber('la',[.14,.91,-.45],[.72,.49,.47],.06);
  tube('laa',1,[[.45,1.02,-.40,.25],[.72,1.12,-.27,.28],[.91,1.15,-.04,.24],[1.02,1.13,.17,.17],[.97,1.02,.35,.11],[.82,.98,.43,.008]],{around:22,color:'#da8978'});
  tube('laa',1,[[.88,1.09,-.10,.15],[1.07,1.13,.01,.14],[1.16,1.13,.13,.035]]);
  tube('aorta',1,[[-.07,.65,.02,.30],[-.13,.99,.10,.29],[-.22,1.42,.10,.26],[-.18,1.77,.05,.25],[.02,1.94,-.10,.235],[.34,1.91,-.30,.219],[.51,1.69,-.53,.201],[.54,1.19,-.75,.186],[.51,.62,-.90,.17],[.43,-.35,-.94,.15],[.38,-.86,-.94,.14]],{open:[1],around:26});
  tube('aorta',1,[[-.14,1.79,.025,.14],[-.22,2.04,.075,.128],[-.28,2.18,.07,.116],[-.32,2.37,.07,.098]],{open:[1]});
  tube('aorta',1,[[-.27,2.15,.07,.088],[-.42,2.21,.03,.085],[-.58,2.27,0,.077]],{open:[1]});
  tube('aorta',1,[[.046,1.9,-.11,.105],[.08,2.13,-.13,.096],[.08,2.38,-.14,.080]],{open:[1]});
  tube('aorta',1,[[.29,1.89,-.27,.114],[.43,2.09,-.30,.102],[.56,2.22,-.35,.086]],{open:[1]});
  tube('pa',1,[[.105,.60,.51,.23],[.17,.82,.56,.283],[.25,1.14,.46,.265],[.34,1.37,.25,.25],[.36,1.44,-.04,.21]],{around:24});
  tube('pa',1,[[.34,1.42,.02,.208],[.57,1.45,-.10,.20],[.86,1.48,-.23,.18],[1.22,1.54,-.30,.15]],{open:[1]});
  tube('pa',1,[[.32,1.43,.01,.202],[-.04,1.40,-.27,.194],[-.48,1.39,-.38,.174],[-.95,1.42,-.36,.154],[-1.3,1.43,-.28,.13]],{open:[1]});
  tube('svc',1,[[-.88,.88,-.10,.235],[-.95,1.24,-.10,.225],[-.98,1.62,-.16,.205],[-.98,1.94,-.18,.186]],{open:[1]});
  tube('ivc',1,[[-.88,.51,-.22,.242],[-.93,.20,-.27,.238],[-.91,-.19,-.34,.222],[-.92,-.58,-.38,.210],[-.93,-1.04,-.4,.182],[-.98,-1.55,-.43,.144]],{open:[1]});
  tube('hepatic',1,[[-.91,-.61,-.38,.13],[-1.12,-.72,-.37,.126],[-1.36,-.86,-.31,.102],[-1.57,-1.02,-.25,.075]],{open:[1]});
  tube('hepatic',1,[[-.91,-.71,-.40,.116],[-1.00,-.87,-.23,.108],[-1.10,-1.05,-.08,.09],[-1.16,-1.22,.06,.065]],{open:[1]});
  tube('hepatic',1,[[-.94,-.75,-.38,.103],[-.74,-.90,-.32,.10],[-.57,-1.07,-.23,.081],[-.45,-1.17,-.13,.058]],{open:[1]});
  for(const side of [-1,1]) for(const top of [0,1]){
    const h=top?.98:.63;
    tube('pv',1,[[.14+side*.31,h,-.56,.16],[.14+side*.58,h+.03,-.66,.155],
      [.14+side*.86,h+(top?.10:-.06),-.75,.14],[.14+side*1.08,h+(top?.17:-.10),-.80,.122]],{open:[1]});
  }

  // Coronaries follow the actual epicardial surface including the interventricular grooves.
  function epicardial(points,r0,r1){
    const path=points.map(([t,a],i)=>[...vent(t,a,.026),r0+(r1-r0)*i/(points.length-1)]);
    tube('coronary',1,path,{around:9,seg:Math.max(10,points.length*4)});
  }
  const lad=[[.91,1.08],[.79,1.24],[.63,1.31],[.49,1.28],[.34,1.28],[.21,1.35],[.09,1.40],[.035,1.59]];
  epicardial(lad,.041,.008);
  epicardial([[.82,1.24],[.76,.98],[.66,.77],[.54,.59],[.42,.48]],.028,.005);
  epicardial([[.64,1.31],[.60,1.06],[.51,.89],[.41,.78],[.30,.71]],.025,.004);
  epicardial([[.48,1.28],[.43,1.56],[.36,1.66],[.28,1.78]],.021,.004);
  epicardial([[.88,1.00],[.93,.62],[.95,.05],[.94,-.49],[.91,-.93],[.88,-1.58]],.038,.013);
  epicardial([[.94,.03],[.79,-.01],[.68,.095],[.56,.04],[.44,.10]],.026,.005);
  epicardial([[.93,1.92],[.89,2.28],[.85,2.70],[.84,3.08],[.86,3.55],[.87,3.95],[.84,4.35]],.040,.023);
  epicardial([[.86,2.75],[.73,2.72],[.60,2.62],[.46,2.58],[.31,2.45]],.027,.006);
  epicardial([[.84,4.35],[.69,4.31],[.52,4.30],[.31,4.27],[.12,4.23]],.028,.005);

  epicardial([[.74,1.00],[.69,.87],[.64,.66],[.57,.47]],.015,.0035);
  epicardial([[.61,1.45],[.55,1.61],[.46,1.81]],.017,.003);
  epicardial([[.62,.95],[.55,.91],[.49,.79],[.44,.77]],.012,.003);
  epicardial([[.75,2.72],[.70,2.51],[.66,2.38],[.60,2.31]],.016,.0035);
  epicardial([[.90,.62],[.84,.52],[.75,.43],[.67,.42]],.019,.003);
  // Atrial view. AV free edges meet during systole; semilunar cusps retract.
  const valves=[
    ['mitral',.525,.69,-.35,.438,.323,2,-.16], ['tricuspid',-.555,.66,.00,.438,.36,3,.16],
    ['aortic_valve',-.01,.72,.075,.220,.203,3,.06], ['pulmonary_valve',.235,.73,.563,.227,.207,3,-.10]
  ];
  function section(u,v,beat){
    const a=u*TAU, radius=v*(1+.04*Math.cos(3*a-.5));
    return [.025+1.14*radius*Math.cos(a),.615+.032*radius*Math.cos(a)-.10*beat,.035+.89*radius*Math.sin(a)];
  }
  function inOrifice(u,v){
    const [px,,pz]=section(u,v,0);
    return valves.some(([,x,,z,rx,rz,,turn])=>{
      const dx=px-x, dz=pz-z, co=Math.cos(turn),si=Math.sin(turn);
      return ((co*dx+si*dz)/rx)**2+((-si*dx+co*dz)/rz)**2<1.015;
    });
  }
  // The section has a true opening under each annulus; its tissue never spans an orifice.
  surface('lv',2,144,52,section,'#b16c64',true,true,inOrifice);
  surface('rv',2,96,10,(u,v,b)=>{
    const p=section(u,1,b),r=1-.10*v;
    return [p[0]*r,p[1]-.35*v,p[2]*r];
  },'#99615b',true,true);

  for(const [id,x,y,z,rx,rz,n,turn] of valves){
    const av=id==='mitral'||id==='tricuspid';
    function place(xx,yy,zz,beat){
      return [x+xx*Math.cos(turn)-zz*Math.sin(turn),y+yy-.10*beat,z+zz*Math.cos(turn)+xx*Math.sin(turn)];
    }
    surface(id,2,48,10,(u,v,b)=>{
      const a=u*TAU, t=v*TAU, ridge=av?.023:.019;
      return place((rx+ridge*Math.cos(t))*Math.cos(a),ridge*Math.sin(t)+.028*Math.cos(2*a),(rz+ridge*Math.cos(t))*Math.sin(a),b);
    },palette[id],true,true);
    surface(id,2,40,9,(u,v,b)=>{
      const a=u*TAU, r=1-.987*v;
      return place(rx*r*Math.cos(a),-.049-.56*Math.pow(v,.62),rz*r*Math.sin(a),b);
    },av?'#642f41':'#603e49',true,true);
    for(let l=0;l<n;l++){
      surface(id,2,20,9,(u,v,b)=>{
        const theta=(l+u)*TAU/n+(av?0:pi/6), scallop=Math.sin(pi*u);
        const open=av?1-b:b, radius=1-v*((1-open)*.985+open*(.16+.22*scallop));
        let xx=rx*radius*Math.cos(theta), zz=rz*radius*Math.sin(theta);
        if(n===2){
          // Anterior and posterior leaflets meet along a transverse coaptation line.
          xx=rx*Math.cos(theta)*(1-.12*v);
          zz=rz*Math.sin(theta)*(1-v*(.992-open*.54));
        }
        const deep=av?-.17*open:.085*open;
        const yy=.027*Math.cos(2*theta)*(1-v)+v*(deep*scallop-.037)+.058*Math.sin(pi*v)*scallop;
        return place(xx,yy,zz,b);
      },mix(rgb(palette[id]),[1,.87,.76],l%2?.08:.20),false,true);
    }
  }
  return {vertices:new Float32Array(vertices), indices:new Uint16Array(indices)};
}

const PRESETS={
  front:{yaw:-.16,tilt:.19,center:[-.08,.33,0],zoom:1},
  back:{yaw:pi-.11,tilt:.13,center:[-.07,.31,-.05],zoom:1},
  valves:{yaw:-.075,tilt:1.32,center:[0,.56,.11],zoom:1.62},
  inferior:{yaw:-.79,tilt:-.25,center:[-.30,-.27,-.22],zoom:1.18}
};
const ANCHORS={
  aorta:[-.17,1.72,.27],mitral:[.54,.69,-.40],laa:[1.04,1.12,.11],hepatic:[-1.35,-.87,-.27],
  tricuspid:[-.58,.67,-.02],aortic_valve:[-.037,.79,.07],pulmonary_valve:[.28,.82,.58],
  lv:[.69,-.72,.58],rv:[-.47,-.11,.79],la:[.27,1.12,-.82],ra:[-1.13,.72,.35],
  pa:[.29,1.18,.60],pv:[.95,1.06,-.72],svc:[-.98,1.67,-.08],
  ivc:[-.96,-1.27,-.37],coronary:[.31,-.29,.79]
};
// The overlay only shows landmarks in a preset orientation. Free rotation uses surface picking.
const GUIDE={
  front:[['aorta',-1,-24],['laa',1,-4],['hepatic',-1,18],['lv',1,21]],
  back:[['pv',-1,-21],['la',1,-19],['ivc',1,20]],
  valves:[['mitral',1,-16],['tricuspid',-1,-4],['aortic_valve',-1,-54],['pulmonary_valve',1,35]],
  inferior:[['hepatic',-1,-14],['ivc',1,28],['ra',-1,-36]]
};

function createGL(canvas,mesh){
  const gl=canvas.getContext('webgl',{alpha:true,antialias:true,premultipliedAlpha:false,preserveDrawingBuffer:false});
  if(!gl) return null;
  const vs=`
    attribute vec3 p0,p1,n0,n1,base;
    attribute float item;
    uniform vec4 cam; uniform vec3 center; uniform vec2 extent; uniform float phase,cut;
    varying vec3 normal,col,modelPos; varying float depth,id,visible;
    vec3 rot(vec3 p){
      float x=cam.x*p.x-cam.y*p.z, z=cam.y*p.x+cam.x*p.z;
      return vec3(x,cam.z*p.y-cam.w*z,cam.w*p.y+cam.z*z);
    }
    void main(){
      vec3 pos=mix(p0,p1,phase), r=rot(pos-center); float layer=floor(item/32.0);
      id=mod(item,32.0); visible=1.0;
      if((cut<0.5&&layer>1.5)||(cut>0.5&&layer<1.5)) visible=0.0;
      normal=rot(mix(n0,n1,phase)); col=base; modelPos=p0; depth=r.z;
      gl_Position=vec4(r.x*extent.x,r.y*extent.y,-r.z*.16,1.);
    }`;
  const fs=`
    precision mediump float;
    uniform float selected,picking;
    varying vec3 normal,col,modelPos; varying float depth,id,visible;
    void main(){
      if(visible<.5) discard;
      if(picking>.5){gl_FragColor=vec4(id/255.,0.,0.,1.);return;}
      vec3 n=normalize(normal); if(n.z<0.) n=-n;
      float key=max(0.,dot(n,normalize(vec3(-.43,.67,.75))));
      float fill=max(0.,dot(n,normalize(vec3(.78,.02,.42))));
      float spec=pow(max(0.,dot(n,normalize(vec3(-.29,.41,.866)))),24.);
      float rim=pow(1.-max(0.,n.z),3.);
      float fiber=.013*sin(58.*modelPos.y+14.*modelPos.x+4.*sin(6.*modelPos.z));
      float dither=.011*sin(dot(modelPos,vec3(87.,79.,57.)))*sin(98.*modelPos.z-15.*modelPos.x);
      float light=.43+.53*key+.15*fill+clamp(depth*.038,-.045,.075)+fiber+dither;
      vec3 c=col*light+vec3(.19,.145,.12)*spec+vec3(.085,.135,.146)*rim;
      if(abs(id-selected)<.4) c=mix(c,vec3(1.,.76,.49),.18)+.046*rim;
      gl_FragColor=vec4(c,1.);
    }`;
  function shader(type,src){
    const sh=gl.createShader(type); gl.shaderSource(sh,src); gl.compileShader(sh);
    if(!gl.getShaderParameter(sh,gl.COMPILE_STATUS)) throw Error(gl.getShaderInfoLog(sh));
    return sh;
  }
  const prog=gl.createProgram();
  gl.attachShader(prog,shader(gl.VERTEX_SHADER,vs)); gl.attachShader(prog,shader(gl.FRAGMENT_SHADER,fs)); gl.linkProgram(prog);
  if(!gl.getProgramParameter(prog,gl.LINK_STATUS)) throw Error(gl.getProgramInfoLog(prog));
  gl.useProgram(prog);
  const buf=gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER,buf); gl.bufferData(gl.ARRAY_BUFFER,mesh.vertices,gl.STATIC_DRAW);
  const ib=gl.createBuffer(); gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,ib); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER,mesh.indices,gl.STATIC_DRAW);
  for(const [name,num,offset] of [['p0',3,0],['p1',3,3],['n0',3,6],['n1',3,9],['base',3,12],['item',1,15]]){
    const a=gl.getAttribLocation(prog,name);gl.enableVertexAttribArray(a);gl.vertexAttribPointer(a,num,gl.FLOAT,false,64,4*offset);
  }
  const u=Object.fromEntries(['cam','center','extent','phase','cut','selected','picking'].map(s=>[s,gl.getUniformLocation(prog,s)]));
  const fb=gl.createFramebuffer(), tex=gl.createTexture(), depth=gl.createRenderbuffer();
  let fw=0,fh=0;
  function resizeTarget(){
    if(fw===canvas.width&&fh===canvas.height) return;
    fw=canvas.width; fh=canvas.height;
    gl.bindTexture(gl.TEXTURE_2D,tex); gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.NEAREST);
    gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,fw,fh,0,gl.RGBA,gl.UNSIGNED_BYTE,null);
    gl.framebufferTexture2D(gl.FRAMEBUFFER,gl.COLOR_ATTACHMENT0,gl.TEXTURE_2D,tex,0);
    gl.bindRenderbuffer(gl.RENDERBUFFER,depth);gl.renderbufferStorage(gl.RENDERBUFFER,gl.DEPTH_COMPONENT16,fw,fh);
    gl.framebufferRenderbuffer(gl.FRAMEBUFFER,gl.DEPTH_ATTACHMENT,gl.RENDERBUFFER,depth);
  }
  function draw(s,pick=false){
    gl.bindFramebuffer(gl.FRAMEBUFFER,pick?fb:null); if(pick) resizeTarget();
    gl.viewport(0,0,canvas.width,canvas.height); gl.enable(gl.DEPTH_TEST); gl.disable(gl.DITHER);
    gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
    gl.uniform4f(u.cam,Math.cos(s.yaw),Math.sin(s.yaw),Math.cos(s.tilt),Math.sin(s.tilt));
    gl.uniform3fv(u.center,s.center);gl.uniform2f(u.extent,2*s.scale/s.w,2*s.scale/s.h);
    gl.uniform1f(u.phase,s.phase);gl.uniform1f(u.cut,s.view==='valves'?1:0);
    gl.uniform1f(u.selected,regionIndex[s.selected]||0);gl.uniform1f(u.picking,pick?1:0);
    gl.drawElements(gl.TRIANGLES,mesh.indices.length,gl.UNSIGNED_SHORT,0);
  }
  return {limit:1.75,draw,pick(x,y,s){
    draw(s,true); const px=new Uint8Array(4);
    gl.readPixels(clamp(Math.floor(x*fw/s.w),0,fw-1),clamp(fh-1-Math.floor(y*fh/s.h),0,fh-1),1,1,gl.RGBA,gl.UNSIGNED_BYTE,px);
    gl.bindFramebuffer(gl.FRAMEBUFFER,null);return px[0];
  }};
}

// Depth-buffered software rendering keeps the same 3D surfaces selectable without WebGL.
function createSoftware(canvas,mesh){
  const ctx=canvas.getContext('2d'), v=mesh.vertices, ix=mesh.indices, n=v.length/16;
  const screen=new Float32Array(n*6);
  let depths,ids,img;
  function draw(s){
    const w=canvas.width,h=canvas.height;
    if(!img||img.width!==w||img.height!==h){img=ctx.createImageData(w,h);depths=new Float32Array(w*h);ids=new Uint8Array(w*h);}
    depths.fill(-Infinity);ids.fill(0);img.data.fill(0);
    const cy=Math.cos(s.yaw),sy=Math.sin(s.yaw),ct=Math.cos(s.tilt),st=Math.sin(s.tilt),factor=s.scale*w/s.w, ph=s.phase;
    for(let i=0;i<n;i++){
      const k=i*16,j=i*6;
      let x=v[k]+(v[k+3]-v[k])*ph-s.center[0],y=v[k+1]+(v[k+4]-v[k+1])*ph-s.center[1],z=v[k+2]+(v[k+5]-v[k+2])*ph-s.center[2];
      const zr=sy*x+cy*z;
      screen[j]=w*.5+factor*(cy*x-sy*z);screen[j+1]=h*.5-factor*(ct*y-st*zr);screen[j+2]=st*y+ct*zr;
      x=v[k+6]+(v[k+9]-v[k+6])*ph;y=v[k+7]+(v[k+10]-v[k+7])*ph;z=v[k+8]+(v[k+11]-v[k+8])*ph;
      const zt=sy*x+cy*z, sign=(st*y+ct*zt)<0?-1:1, nx=(cy*x-sy*z)*sign,ny=(ct*y-st*zt)*sign,nz=(st*y+ct*zt)*sign;
      const fiber=.014*Math.sin(54*v[k+1]+12*v[k]+3*Math.sin(7*v[k+2]));
      const light=.43+fiber+.53*Math.max(0,-.43*nx+.67*ny+.75*nz)+.15*Math.max(0,.88*nx+.02*ny+.47*nz)+clamp(screen[j+2]*.038,-.045,.075);
      const spec=.15*Math.pow(Math.max(0,-.29*nx+.41*ny+.866*nz),24), rim=.10*Math.pow(1-Math.max(0,nz),3);
      const sel=(Math.round(v[k+15])%32===regionIndex[s.selected]) ? .18 : 0;
      for(let c=0;c<3;c++)screen[j+3+c]=255*((v[k+12+c]*light+spec+rim)*(1-sel)+[1,.76,.49][c]*sel);
    }
    const pix=img.data;
    for(let t=0;t<ix.length;t+=3){
      const info=v[16*ix[t]+15],layer=Math.floor(info/32);
      if(s.view==='valves'?layer!==2:layer===2) continue;
      const a=6*ix[t],b=6*ix[t+1],c=6*ix[t+2];
      const ax=screen[a],ay=screen[a+1],bx=screen[b],by=screen[b+1],cx=screen[c],cyy=screen[c+1];
      const den=(by-cyy)*(ax-cx)+(cx-bx)*(ay-cyy);
      if(Math.abs(den)<1e-7) continue;
      const x0=Math.max(0,Math.floor(Math.min(ax,bx,cx))),x1=Math.min(w-1,Math.ceil(Math.max(ax,bx,cx)));
      const y0=Math.max(0,Math.floor(Math.min(ay,by,cyy))),y1=Math.min(h-1,Math.ceil(Math.max(ay,by,cyy)));
      for(let y=y0;y<=y1;y++)for(let x=x0;x<=x1;x++){
        const f=((by-cyy)*(x+.5-cx)+(cx-bx)*(y+.5-cyy))/den, g=((cyy-ay)*(x+.5-cx)+(ax-cx)*(y+.5-cyy))/den, l=1-f-g;
        if(f<0||g<0||l<0)continue;
        const pos=y*w+x,zz=f*screen[a+2]+g*screen[b+2]+l*screen[c+2];
        if(zz<depths[pos])continue;
        depths[pos]=zz;ids[pos]=info%32;
        for(let ch=0;ch<3;ch++)pix[pos*4+ch]=f*screen[a+3+ch]+g*screen[b+3+ch]+l*screen[c+3+ch];
        pix[pos*4+3]=255;
      }
    }
    ctx.putImageData(img,0,0);
  }
  return {limit:.9,software:true,draw,pick(x,y,s){return ids?.[clamp(Math.floor(y*canvas.height/s.h),0,canvas.height-1)*canvas.width+clamp(Math.floor(x*canvas.width/s.w),0,canvas.width-1)]||0;}};
}

function mountHeart(onPick){
  let canvas=document.getElementById('heart'),overlay=document.getElementById('overlay');
  const box=document.getElementById('viewport'),ctx=overlay.getContext('2d');
  const mesh=buildHeart();
  let engine;
  function useSoftware(){
    const replacement=canvas.cloneNode(false);canvas.replaceWith(replacement);canvas=replacement;
    engine=createSoftware(canvas,mesh);
  }
  try{engine=createGL(canvas,mesh);}catch(e){console.info('3B yazılım görünümü',e.message);}
  if(!engine) useSoftware();
  const s={view:'front',selected:'aorta',...PRESETS.front,playing:!matchMedia('(prefers-reduced-motion: reduce)').matches,
    guides:true,clock:.58,phase:0,w:1,h:1,scale:1,zoomExtra:1};
  let tags=[],dirty=true,inView=true,last=0,tick=null,drag=null;
  function resize(){
    const rect=box.getBoundingClientRect(); s.w=Math.max(1,rect.width);s.h=Math.max(1,rect.height);
    const dpr=window.devicePixelRatio||1, ratio=Math.min(dpr,engine.limit), od=Math.min(dpr,2);
    canvas.width=Math.max(1,Math.round(s.w*ratio));canvas.height=Math.max(1,Math.round(s.h*ratio));
    overlay.width=Math.round(s.w*od);overlay.height=Math.round(s.h*od);
    ctx.setTransform(od,0,0,od,0,0); dirty=true; schedule();
  }
  function project(p){
    const [x,y,z]=sub(p,s.center),cy=Math.cos(s.yaw),sy=Math.sin(s.yaw),ct=Math.cos(s.tilt),st=Math.sin(s.tilt),zr=sy*x+cy*z;
    return [s.w/2+s.scale*(cy*x-sy*z),s.h/2-s.scale*(ct*y-st*zr)];
  }
  function guides(){
    ctx.clearRect(0,0,s.w,s.h);tags=[];
    const base=PRESETS[s.view],turn=Math.atan2(Math.sin(s.yaw-base.yaw),Math.cos(s.yaw-base.yaw));
    if(!s.guides||Math.abs(turn)>.47||Math.abs(s.tilt-base.tilt)>.34)return;
    const compact=s.w<450;
    const list=GUIDE[s.view],h=compact?23:25, margin=compact?6:12;
    ctx.font=(compact?'500 10px':'500 11px')+' system-ui,sans-serif';
    const proposed=list.map(([id,side,shift])=>{
      let p=beatPoint(ANCHORS[id],id,s.phase);
      if(s.view==='valves')p=[p[0],p[1]-.10*s.phase,p[2]];
      const [x,y]=project(p),r=CATALOG.regions[regionIndex[id]-1],label=r.short;
      const w=Math.ceil(ctx.measureText(label).width)+16;
      return {id,x,y,w,h,side,label,tx:side===1?s.w-margin-w:margin,ty:clamp(y+shift,15,s.h-16)};
    }).filter(o=>o.x>=0&&o.x<=s.w&&o.y>=8&&o.y<=s.h-8);
    for(const side of [-1,1]){
      const group=proposed.filter(o=>o.side===side).sort((a,b)=>a.ty-b.ty);
      group.forEach((o,i)=>{if(i)o.ty=Math.max(o.ty,group[i-1].ty+h+5);});
      for(let i=group.length-1;i>=0;i--){group[i].ty=Math.min(group[i].ty,i===group.length-1?s.h-h/2-4:group[i+1].ty-h-5);}
    }
    for(const o of proposed){
      const {id,x,y,w,side,tx,ty,label}=o, edge=side===1?tx:tx+w, focus=id===s.selected;
      ctx.lineWidth=focus?1.35:1;ctx.strokeStyle=focus?'#c0e8d6':'#89a8ad';
      ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(edge+(side===1?-8:8),ty);ctx.lineTo(edge,ty);ctx.stroke();
      ctx.fillStyle=focus?'#c4f1d6':'#d2dddc';ctx.beginPath();ctx.arc(x,y,focus?3.6:2.9,0,TAU);ctx.fill();
      ctx.fillStyle=focus?'#c4e9d4':'#203b43';ctx.strokeStyle=focus?'#c4e9d4':'#455f65';
      ctx.beginPath();ctx.roundRect(tx,ty-h/2,w,h,5);ctx.fill();ctx.stroke();
      ctx.fillStyle=focus?'#173d32':'#ecf3ed';ctx.textBaseline='middle';ctx.fillText(label,tx+8,ty+.5);
      tags.push({id,x:tx,y:ty-h/2,w,h});
    }
  }
  function redraw(){
    s.scale=Math.min(s.w/3.66,s.h/4.67)*s.zoom*s.zoomExtra;
    const u=s.clock;
    s.phase=u<.39?Math.pow(Math.sin(pi*u/.39),.74):0;
    engine.draw(s);guides();dirty=false;
    document.getElementById('phase').textContent=u<.39?'Sistol':'Diyastol';
    document.getElementById('beat-indicator').style.opacity=String(.48+.50*s.phase);
  }
  function frame(ts){
    tick=null;
    if(!inView||document.hidden){last=0;return;}
    if(dirty||s.playing){
      const interval=engine.software?88:32;
      if(dirty||ts-last>=interval){
        if(s.playing&&last)s.clock=(s.clock+Math.min(ts-last,170)/940)%1;
        last=ts;redraw();
      }
      if(s.playing)schedule();
    }
  }
  function schedule(){if(tick===null&&inView&&!document.hidden)tick=requestAnimationFrame(frame);}
  function refresh(){dirty=true;schedule();}
  function view(id){
    s.view=id;Object.assign(s,PRESETS[id]);s.zoomExtra=1;
    document.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.view===id)));
    refresh();
  }
  function zoom(step){s.zoomExtra=clamp(s.zoomExtra*step,.72,1.85);refresh();}
  function motion(){
    const b=document.getElementById('motion');b.textContent=s.playing?'Durdur':'Oynat';
    b.setAttribute('aria-label',s.playing?'Kalp hareketini durdur':'Kalp hareketini oynat');b.setAttribute('aria-pressed',String(!s.playing));
  }
  function toggle(){s.playing=!s.playing;last=0;motion();refresh();}
  document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>view(b.dataset.view)));
  document.getElementById('zoom-in').onclick=()=>zoom(1.14);document.getElementById('zoom-out').onclick=()=>zoom(1/1.14);
  document.getElementById('motion').onclick=toggle;
  document.getElementById('guides').onclick=e=>{s.guides=!s.guides;e.currentTarget.setAttribute('aria-pressed',String(s.guides));refresh();};
  document.getElementById('home').onclick=()=>view(s.view);
  box.addEventListener('pointerdown',e=>{
    if(e.button!==0||drag)return;
    drag={id:e.pointerId,x:e.clientX,y:e.clientY,oy:s.yaw,ot:s.tilt,moved:false};box.setPointerCapture(e.pointerId);
  });
  box.addEventListener('pointermove',e=>{
    if(!drag||e.pointerId!==drag.id)return;
    const dx=e.clientX-drag.x,dy=e.clientY-drag.y;
    if(Math.hypot(dx,dy)>5)drag.moved=true;
    if(drag.moved){s.yaw=drag.oy-dx*.009;s.tilt=clamp(drag.ot+dy*.008,-1.53,1.53);box.classList.add('grabbing');refresh();}
  });
  box.addEventListener('pointerup',e=>{
    if(!drag||e.pointerId!==drag.id)return;
    const moved=drag.moved;drag=null;box.classList.remove('grabbing');
    if(moved)return;
    const rect=box.getBoundingClientRect(),x=e.clientX-rect.left,y=e.clientY-rect.top;
    const label=tags.find(t=>x>=t.x-2&&x<=t.x+t.w+2&&y>=t.y-3&&y<=t.y+t.h+3);
    if(label){onPick(label.id);return;}
    const picked=engine.pick(x,y,s),r=CATALOG.regions[picked-1];
    if(r)onPick(r.id);
  });
  box.addEventListener('pointercancel',()=>{drag=null;box.classList.remove('grabbing');});
  box.addEventListener('keydown',e=>{
    const d={ArrowLeft:[.13,0],ArrowRight:[-.13,0],ArrowUp:[0,.12],ArrowDown:[0,-.12]}[e.key];
    if(d){e.preventDefault();s.yaw+=d[0];s.tilt=clamp(s.tilt+d[1],-1.53,1.53);refresh();}
  });
  canvas.addEventListener('webglcontextlost',e=>{e.preventDefault();useSoftware();resize();});
  if(window.IntersectionObserver)new IntersectionObserver(([e])=>{inView=e.isIntersecting;last=0;if(inView)refresh();}).observe(box);
  document.addEventListener('visibilitychange',()=>{last=0;refresh();});
  new ResizeObserver(resize).observe(box);
  motion();view('front');resize();
  return {setRegion(id,fromList=false){
    s.selected=id;const r=CATALOG.regions[regionIndex[id]-1];
    if(fromList)view(r.view);else refresh();
  },getView:()=>s.view};
}

const byId = id=>document.getElementById(id);
const allRegions=CATALOG.regions;
const regions=Object.fromEntries(allRegions.map(r=>[r.id,r]));
const select=byId('region'), optionLetters='ABCDE';
const state={scope:'neu-kalp-atlasi-ornek-v1',banks:{},records:{},region:'aorta',bankStatus:'standalone',flags:new Set(),pendingFlag:null};
let model,frameOrigin=null,lastHeight=0;

function shuffle(items){
  const out=items.slice();
  for(let i=out.length-1;i>0;i--){const j=Math.floor(Math.random()*(i+1));[out[i],out[j]]=[out[j],out[i]];}
  return out;
}
function storeState(){
  try{sessionStorage.setItem(state.scope,JSON.stringify({region:state.region,records:state.records,flags:[...state.flags]}));}catch{}
}
function loadState(){
  let raw={};try{raw=JSON.parse(sessionStorage.getItem(state.scope)||'{}')||{};}catch{}
  state.records=raw.records&&typeof raw.records==='object'?raw.records:{};
  state.flags=new Set(Array.isArray(raw.flags)?raw.flags:[]);
  state.region=Object.hasOwn(regions,raw.region)?raw.region:'aorta';
}
function bankFor(id){return state.banks[id]?.length?state.banks[id]:CATALOG.samples[id];}
function recordFor(id){
  const bank=bankFor(id),ids=bank.map(q=>q.id),old=state.records[id];
  if(old?.order?.length===ids.length&&new Set(old.order).size===ids.length&&ids.every(q=>old.order.includes(q))&&old.answers&&Number.isInteger(old.index)&&old.index>=0&&old.index<ids.length)return old;
  return state.records[id]={order:shuffle(ids),index:0,answers:{},pick:null,done:false};
}
function current(){
  const bank=bankFor(state.region),rec=recordFor(state.region);
  return {q:bank.find(x=>x.id===rec.order[rec.index]),rec,bank};
}
function make(tag,cls,text){
  const el=document.createElement(tag);
  if(cls)el.className=cls;if(text!==undefined)el.textContent=text;
  return el;
}
function safeSource(feedback,q){
  const source=q.source;if(!source||!source[0])return;
  if(/^https?:\/\//i.test(source[1]||'')){
    const a=make('a','',source[0]+' ↗');a.href=source[1];a.target='_blank';a.rel='noopener noreferrer';feedback.append(a);
  }else feedback.append(make('span','reference',source[0]));
}
function scoreOf(rec,bank){return bank.reduce((sum,q)=>sum+(rec.answers[q.id]===q.key?1:0),0);}
function render(){
  const {q,rec,bank}=current(),id=state.region;
  const answered=Object.hasOwn(rec.answers,q.id),selection=answered?rec.answers[q.id]:rec.pick;
  const totalAnswered=Object.keys(rec.answers).length,score=scoreOf(rec,bank),fromSheet=Boolean(state.banks[id]?.length);
  select.value=id;
  byId('source').textContent=fromSheet?'Kurum bankası':'Örnek sorular';
  byId('source').classList.toggle('bank',fromSheet);
  byId('q-index').textContent=rec.done?'Tur tamamlandı':'Soru '+(rec.index+1)+' / '+bank.length;
  byId('score').textContent=score+' doğru · '+(totalAnswered-score)+' yanlış';
  byId('q-fill').style.width=(100*totalAnswered/bank.length)+'%';
  byId('exercise').hidden=rec.done;byId('complete').hidden=!rec.done;
  byId('stem').textContent=q.stem;
  const choices=byId('choices');choices.replaceChildren();
  q.options.forEach(([letter,text])=>{
    const button=make('button','opt');button.type='button';button.disabled=answered;
    button.setAttribute('aria-pressed',String(selection===letter));button.append(make('span','letter',letter),document.createTextNode(text));
    if(answered&&letter===q.key)button.classList.add('correct');
    if(answered&&letter===selection&&letter!==q.key)button.classList.add('wrong');
    button.onclick=()=>{
      if(rec.done||Object.hasOwn(rec.answers,q.id))return;
      rec.pick=letter;storeState();
      [...choices.children].forEach((b,i)=>b.setAttribute('aria-pressed',String(q.options[i][0]===letter)));
      byId('submit').disabled=false;
    };
    choices.append(button);
  });
  const feedback=byId('feedback');feedback.replaceChildren();feedback.hidden=!answered||rec.done;
  feedback.classList.toggle('negative',answered&&selection!==q.key);
  if(answered){
    const answer=q.options.find(([l])=>l===q.key);
    feedback.append(make('strong','',(selection===q.key?'Doğru. ':'Doğru yanıt '+q.key+' · ')+answer[1]));
    if(q.why)feedback.append(make('div','',q.why));
    safeSource(feedback,q);
  }
  byId('submit').disabled=!rec.done&&!answered&&!selection;
  byId('submit').textContent=rec.done?'Bu yapıyı yeniden çöz':answered?(rec.index+1===bank.length?'Sonucu gör':'Sonraki soru  →'):'Yanıtı kontrol et';
  byId('result').textContent=bank.length+' soruda '+score+' doğru, '+(totalAnswered-score)+' yanlış. Başka bir yapı seçerek devam edebilirsiniz.';
  byId('flag').hidden=!fromSheet||rec.done||!frameOrigin;
  byId('flag').disabled=state.flags.has(q.id)||state.pendingFlag?.qid===q.id;
  byId('flag-status').textContent=state.flags.has(q.id)?'Düzeltme isteği kaydedildi.':state.pendingFlag?.qid===q.id?'Kaydediliyor…':'';
  const done=allRegions.reduce((n,r)=>n+(recordFor(r.id).done?1:0),0);
  byId('course-label').textContent=done+' / '+allRegions.length+' yapı tamamlandı';
  byId('course-fill').style.width=100*done/allRegions.length+'%';
  const note=byId('bank-note');
  if(state.bankStatus==='standalone')note.textContent='Bu önizlemede her yapı için kaynaklı iki örnek soru bulunur.';
  else if(state.bankStatus==='ready')note.textContent=fromSheet?'':'Bu yapı için eşleşen aktif kurum sorusu bulunamadı. Örnek sorular gösteriliyor.';
  else note.textContent=state.bankStatus==='schema'?'SoruBankasi başlıkları okunamadı. Örnek sorular gösteriliyor.':'Kurum soru bankası şu anda kullanılamıyor. Örnek sorular gösteriliyor.';
  note.hidden=!note.textContent;
}
function choose(id,fromList=false,move=false){
  if(!Object.hasOwn(regions,id))return;
  state.region=id;model?.setRegion(id,fromList);render();storeState();
  if(move&&window.matchMedia('(max-width:740px)').matches)byId('quiz').scrollIntoView({block:'start',behavior:'instant'});
}
for(const group of [...new Set(allRegions.map(r=>r.group))]){
  const og=make('optgroup');og.label=group;
  for(const r of allRegions.filter(r=>r.group===group)){const opt=make('option','',r.name);opt.value=r.id;og.append(opt);}
  select.append(og);
}
select.onchange=()=>choose(select.value,true);
byId('to-model').onclick=()=>byId('viewport').scrollIntoView({block:'center'});
byId('submit').onclick=()=>{
  const {rec,q,bank}=current();
  if(rec.done){delete state.records[state.region];recordFor(state.region);}
  else if(Object.hasOwn(rec.answers,q.id)){
    rec.pick=null;
    if(rec.index+1>=bank.length)rec.done=true;else rec.index++;
  }else if(q.options.some(([letter])=>letter===rec.pick)){rec.answers[q.id]=rec.pick;}
  storeState();render();
};
function post(type,body,origin=frameOrigin||'*'){
  if(window.parent!==window)window.parent.postMessage({isStreamlitMessage:true,type:'streamlit:'+type,...body},origin);
}
function frameHeight(){
  if(!frameOrigin)return;
  const height=Math.ceil(document.querySelector('.atlas').getBoundingClientRect().height)+2;
  if(height!==lastHeight){lastHeight=height;post('setFrameHeight',{height});}
}
byId('flag').onclick=()=>{
  const {q}=current();
  if(!frameOrigin||!state.banks[state.region]?.some(x=>x.id===q.id)||state.pendingFlag||state.flags.has(q.id))return;
  state.pendingFlag={qid:q.id,nonce:Date.now().toString(36)+'-'+Math.random().toString(36).slice(2,9)};
  render();post('setComponentValue',{dataType:'json',value:state.pendingFlag});
};
window.addEventListener('message',e=>{
  if(e.source!==window.parent||e.data?.type!=='streamlit:render'||!e.data.args?.atlasScope)return;
  if(frameOrigin&&e.origin!==frameOrigin)return;
  frameOrigin=e.origin==='null'?'*':e.origin;
  const args=e.data.args,nextScope='neu-kalp-atlasi-'+args.atlasScope;
  const changed=state.scope!==nextScope;
  if(changed){state.scope=nextScope;loadState();}
  state.banks=args.banks||{};state.bankStatus=args.status;
  const ack=args.ack;
  if(ack&&ack.nonce===state.pendingFlag?.nonce){
    state.pendingFlag=null;
    if(ack.ok){state.flags.add(ack.qid);storeState();}
  }
  if(changed)model?.setRegion(state.region,true);
  render();if(ack&&!ack.ok&&current().q.id===ack.qid)byId('flag-status').textContent='Kaydedilemedi. Yeniden deneyebilirsiniz.';
  frameHeight();
});
loadState();render();
model=mountHeart(id=>choose(id,false,true));model.setRegion(state.region,true);
new ResizeObserver(frameHeight).observe(document.querySelector('.atlas'));
post('componentReady',{apiVersion:1});

</script>
</body>
</html>
'''

@st.cache_resource(show_spinner=False)
def _atlas_directory(html):
    # Keep the TemporaryDirectory alive for as long as Streamlit serves this component.
    directory = tempfile.TemporaryDirectory(prefix="neu_kalp_atlasi_")
    Path(directory.name, "index.html").write_text(html, encoding="utf-8")
    return directory

@st.cache_data(ttl=60, show_spinner=False)
def _atlas_read_bank(sheet_id, index):
    try:
        if _get_service_account_info().get("type") != "service_account":
            return {}, {}, "unavailable"
    except FileNotFoundError:
        return {}, {}, "unavailable"
    return _atlas_bank(load_data(sheet_id, index, required_col="SoruID"))

def _render_heart_atlas():
    banks, lookup, status = _atlas_read_bank(SHEET_ID, QUESTION_WS_INDEX)
    component = components.declare_component("neu_kalp_atlasi", path=_atlas_directory(_ATLAS_HTML).name)
    scope = hashlib.sha256(f"{SHEET_ID}/{QUESTION_WS_INDEX}".encode()).hexdigest()[:12]
    previous = st.session_state.get("atlas_review_ack", {})
    event = component(atlasScope=scope, banks=banks, status=status, ack=previous,
                      key="neu_kalp_atlasi", default=None)
    if not isinstance(event, dict):
        return
    uid, nonce = event.get("qid"), event.get("nonce")
    if not isinstance(uid, str) or not isinstance(nonce, str) or not 1 <= len(nonce) <= 80 or previous.get("nonce") == nonce:
        return
    target = lookup.get(uid)
    ok = bool(target and flag_question_for_review(SHEET_ID, QUESTION_WS_INDEX, *target))
    st.session_state.atlas_review_ack = {"qid": uid, "nonce": nonce, "ok": ok}
    st.rerun()


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
    mode = st.radio(
        "Soru bankası modu",
        ["Kalp atlası", "Karışık test", "Fotoğraflı test", "Videolu test"],
        horizontal=True, key="soru_bankasi_modu",
    )
    if mode == "Kalp atlası":
        _render_heart_atlas()
        st.stop()

    st.header("🧠 Kardiyoloji Soru Bankası")

    # Karışık test eski dosyadan, medya soruları ikinci dosyadaki isimli sekmelerden okunur.
    media_kind = "photo" if mode == "Fotoğraflı test" else "video" if mode == "Videolu test" else None
    quiz_sheet_id = SHEET_ID if not media_kind else MEDIA_SHEET_ID
    quiz_ws = QUESTION_WS_INDEX if not media_kind else MEDIA_PHOTO_TAB if media_kind == "photo" else MEDIA_VIDEO_TAB
    if media_kind and not _media_sheet_is_configured():
        st.warning("Yeni Google Sheets bağlantısı henüz ayarlanmamış.")
        st.code('MEDIA_SHEET_ID = "YENI_SHEETS_ID_BURAYA"', language="python")
        st.info("web_app.py dosyasında bu değeri yeni Google Sheets ID'si ile değiştirin. Secrets'a yeni bir ID eklemeniz gerekmiyor.")
        st.stop()

    dfq = load_data(quiz_sheet_id, quiz_ws, required_col="SoruID")
    if dfq.empty:
        if media_kind:
            st.warning(f"'{quiz_ws}' sekmesi okunamadı veya henüz soru eklenmedi.")
            st.info("Yeni Google Sheets'i servis hesabının client_email adresiyle Düzenleyici olarak paylaşın. Sekme adlarını ve başlıkları kontrol edin.")
        else:
            st.warning("Henüz soru yok veya SoruBankasi sekmesi başlıkları uygun değil.")
            st.info("İlk satır: `SoruID | Aktif | Kategori | Soru | A | B | C | D | E | Dogru | Aciklama | Kaynak`. Varsayılan sekme indeksi: 8.")
        st.stop()

    # Yeni medya tablolarında Kaynak isteğe bağlıdır; eski testin şeması değişmez.
    required_cols = ["SoruID", "Aktif", "Kategori", "Soru", "A", "B", "C", "D", "E", "Dogru", "Aciklama"]
    if not media_kind:
        required_cols.append("Kaynak")
    missing_cols = [c for c in required_cols if c not in dfq.columns]
    if missing_cols:
        st.error(f"{quiz_ws} sekmesinde eksik kolon var: " + ", ".join(missing_cols))
        st.info("Başlıklar: `SoruID | Aktif | Kategori | Soru | A | B | C | D | E | Dogru | Aciklama | Kaynak` + fotoğrafta `GorselURL`, videoda `VideoURL`.")
        st.stop()
    if "Kaynak" not in dfq.columns:
        dfq["Kaynak"] = ""

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
    quiz_source_signature = (mode, tuple(question_uids_current))

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
    if media_kind:
        _show_question_media(row, media_kind)

    radio_options = list(range(len(secenekler)))

    quiz_uid = str(row.get("_quiz_uid", f"{soru_id}_{q_index}"))
    selected = st.radio(
        "Cevabınız:",
        options=radio_options,
        format_func=lambda i: f"{secenekler[i][0]}) {secenekler[i][1]}",
        index=st.session_state.quiz_selected if st.session_state.quiz_selected is not None else None,
        disabled=st.session_state.quiz_answered,
        key=f"quiz_radio_{media_kind or 'standard'}_{quiz_uid}",
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
                quiz_sheet_id,
                quiz_ws,
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
- Relaksasyon bozulursa **e′ düşer**; compliance bozulursa **LAP yükselir**.
- **Grade I = gevşeme bozukluğu**; **Grade II–III = basınç yükü**.
- **LVEDP erken bozulur**, LAP/PCWP daha geç yükselir.
- **E/e′ LAP’ı**, **Ar-A LVEDP’yi** daha iyi anlatır.
- **HFpEF tanısı için EF normal yetmez**; yüksek filling pressure kanıtı gerekir.
- **PH’de LAP yüksek mi?** sorusu, hastanın **Grup 2 mi PAH tarafı mı** olduğunu belirler.
- **Restriktif KMP’de e′ düşük**; **konstriksiyonda septal e′ korunur**.
- Mitral kapak hastaysa **mitral inflow’a**, annülüs hastaysa **e′ye** dikkat.
- **LAVI kronik yükü**, **LARS daha erken fonksiyonel bozulmayı** gösterebilir.
- **MR + normal EF:** E/e′ güvenilmez; **Ar-A >30 ms** ve **IVRT/TE-e′ <5.6** daha değerli.
- **Restriktif = kas hasta → e′ düşük**.
- **Konstriktif = kılıf hasta → e′ korunur**.
- **HCM’de >orta MR varsa** E/e′ ve LAVI yanıltıcı; **Ar-A ve TR** daha güvenilir.
- **PH’de septal e′ etkilenebilir**; bu yüzden **lateral E/e′ ve LARS** daha değerli olabilir.
- **AF’de filling pressure yüksekse** mitral E dalgası atımdan atıma daha az değişir.
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

                search_cols = [c for c in ["Dosya Numarası", "Hekim", "Tarih", "Eppendorf Numarası"] if c in show.columns]
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
                        "Dosya Numarası", "Adı Soyadı", "Tarih", "Hekim", "İletişim", "Eppendorf Numarası",
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

            iletisim_col, eppendorf_col = st.columns(2)
            with iletisim_col:
                iletisim = st.text_input("İletişim", value=gs("İletişim"))
            with eppendorf_col:
                eppendorf_no = st.text_input(
                    "Eppendorf Numarası",
                    value=gs("Eppendorf Numarası"),
                    help="Kan örneği için tüp/eppendorf kodu. Sheet’te kolon yoksa kayıt sırasında en sona otomatik eklenir."
                )

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
                    "Eppendorf Numarası": eppendorf_no,
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
