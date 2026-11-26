# web_app.py
# NEÜ-KARDİYO | Streamlit + Google Sheets (CRUD)
# Not: Excel/CSV indirme YOK (isteğe göre kaldırıldı)

import base64
from html import escape
import hashlib
import json
import re
import tempfile
import unicodedata
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import requests

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

# Google Drive: Fotoğraf ve videolar tek klasörde tutulur.
# Drive klasör URL'sindeki /folders/ kısmından sonraki ID'yi girin.
MEDIA_DRIVE_FOLDER_ID = "1PkQu5DBmYKKNrLBHQtnLJwCyNgM6f2OQ"


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
QUESTION_WS_INDEX = 2  # Soru bankası dosyasındaki üçüncü sekme (metin soruları).

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


def _media_folder_is_configured():
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{10,}", MEDIA_DRIVE_FOLDER_ID.strip()) and
                MEDIA_DRIVE_FOLDER_ID != "YENI_DRIVE_KLASOR_ID_BURAYA")


def _media_link(value):
    """Only http(s) links are accepted as legacy URL input."""
    url = str(value or "").strip()
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"https", "http"} or not parsed.netloc:
        return ""
    return url


def _drive_file_id(url):
    """Extract a file ID from standard Google Drive sharing URLs."""
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


@st.cache_resource(show_spinner=False)
def _drive_credentials():
    """The same service account as Sheets; never expose its token to the browser."""
    info = _get_service_account_info()
    return ServiceAccountCredentials.from_json_keyfile_dict(
        info, ["https://www.googleapis.com/auth/drive.readonly"]
    )


def _drive_get(url, *, params=None, stream=False, timeout=(10, 45)):
    # oauth2client refreshes the token on demand; all requests are server-side.
    token = _drive_credentials().get_access_token().access_token
    return requests.get(
        url,
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        stream=stream,
        timeout=timeout,
    )


@st.cache_data(ttl=120, max_entries=3, show_spinner=False)
def _list_drive_media(folder_id):
    """List files in the shared folder, not in the entire Google Drive.

    Returns a filename -> metadata lookup. No public-sharing URLs required.
    """
    items = {}
    page_token = None
    while True:
        params = {
            "q": f"'{folder_id}' in parents and trashed = false",
            "fields": "nextPageToken,files(id,name,mimeType,size,modifiedTime)",
            "pageSize": 1000,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if page_token:
            params["pageToken"] = page_token
        response = _drive_get("https://www.googleapis.com/drive/v3/files", params=params)
        try:
            response.raise_for_status()
            data = response.json()
        finally:
            response.close()
        for item in data.get("files", []):
            # Case-insensitive lookup; duplicate names must be renamed by the owner.
            key = str(item.get("name", "")).strip().casefold()
            if key:
                items.setdefault(key, []).append(item)
        page_token = data.get("nextPageToken")
        if not page_token:
            return items


@st.cache_data(ttl=3600, max_entries=6, show_spinner=False)
def _download_drive_media(file_id, modified_time, max_bytes):
    """Download only a size-limited media file; the bytes stay on Streamlit server.

    modified_time is used as a cache-busting parameter when the file is updated.
    """
    response = _drive_get(
        f"https://www.googleapis.com/drive/v3/files/{file_id}",
        params={"alt": "media", "supportsAllDrives": "true"},
        stream=True, timeout=(10, 90),
    )
    try:
        response.raise_for_status()
        declared_size = response.headers.get("Content-Length", "")
        if declared_size.isdigit() and int(declared_size) > max_bytes:
            raise ValueError(f"Dosya {max_bytes // (1024 * 1024)} MB sınırını aşıyor.")
        contents, total = [], 0
        for part in response.iter_content(chunk_size=256 * 1024):
            if not part:
                continue
            total += len(part)
            if total > max_bytes:
                raise ValueError(f"Dosya {max_bytes // (1024 * 1024)} MB sınırını aşıyor.")
            contents.append(part)
        return b"".join(contents)
    finally:
        response.close()


def _show_question_video(source):
    st.markdown(
        f'<video src="{escape(source, quote=True)}" controls controlslist="nodownload" '
        'playsinline loop oncontextmenu="return false" '
        'style="display:block;width:100%;height:auto"></video>',
        unsafe_allow_html=True,
    )


def _show_drive_media_by_name(filename, kind):
    """Look up the exact filename in the private Drive folder and display it."""
    if not _media_folder_is_configured():
        st.warning("Drive klasörü ayarlanmadı: web_app.py içinde MEDIA_DRIVE_FOLDER_ID değerini girin.")
        return
    filename = str(filename).strip()
    if not filename or "/" in filename or "\\" in filename or len(filename) > 250:
        st.warning("Dosya adını uzantısıyla yazın. Örnek: coronary_sinus.png")
        return
    try:
        index = _list_drive_media(MEDIA_DRIVE_FOLDER_ID)
        matches = index.get(filename.casefold(), [])
        if not matches:
            st.warning(f"Drive klasöründe '{filename}' bulunamadı. Dosya adı ve uzantısını kontrol edin.")
            st.caption("Yeni yüklediyseniz 'Drive listesini yenile' düğmesini kullanın.")
            return
        if len(matches) > 1:
            st.error(f"Klasörde '{filename}' adında birden fazla dosya var. Her dosyaya benzersiz ad verin.")
            return
        file = matches[0]
        mime = str(file.get("mimeType", "")).lower()
        accepted = (
            {"image/jpeg", "image/png", "image/webp", "image/gif"}
            if kind == "photo" else {"video/mp4", "video/webm", "video/ogg"}
        )
        if mime not in accepted:
            st.warning(f"'{filename}' dosyasının biçimi ({mime or 'bilinmiyor'}) desteklenmiyor. "
                       + ("PNG/JPG/WebP/GIF kullanın." if kind == "photo" else "MP4 (H.264) önerilir."))
            return
        limit = 15 * 1024 * 1024 if kind == "photo" else 60 * 1024 * 1024
        size = str(file.get("size", ""))
        if size.isdigit() and int(size) > limit:
            st.warning(f"'{filename}' fazla büyük. "
                       f"{'Fotoğraf' if kind == 'photo' else 'Video'} başına sınır "
                       f"{limit // (1024 * 1024)} MB; videoyu sıkıştırın.")
            return
        payload = _download_drive_media(file["id"], file.get("modifiedTime", ""), limit)
        if kind == "photo":
            st.image(payload, caption="Ekokardiyografi sorusu", use_container_width=True)
        else:
            encoded = base64.b64encode(payload).decode("ascii")
            _show_question_video(f"data:{mime};base64,{encoded}")
    except requests.exceptions.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else "?"
        st.error(f"Drive dosyasına erişilemedi (HTTP {code}). Klasör paylaşımını ve Drive API'yi kontrol edin.")
    except requests.exceptions.RequestException:
        st.error("Drive bağlantısı sırasında ağ hatası oluştu; yeniden deneyin.")
    except ValueError as exc:
        st.warning(str(exc))
    except Exception:
        st.error("Medya yüklenemedi. Klasör ID'sini, dosya adını ve servis hesabı erişimini kontrol edin.")


def _show_question_media(row, kind):
    """Use Drive filename first, or fall back to the older URL columns."""
    if kind == "photo":
        filename_cols = ("GorselDosya", "GörselDosya", "DosyaAdi", "DosyaAdı")
        link_cols = ("GorselURL", "GörselURL", "FotoURL", "ResimURL", "MedyaURL")
    else:
        filename_cols = ("VideoDosya", "DosyaAdi", "DosyaAdı")
        link_cols = ("VideoURL", "MedyaURL")

    raw_name = next((str(row.get(k, "")).strip() for k in filename_cols
                     if str(row.get(k, "")).strip()), "")
    if raw_name:
        _show_drive_media_by_name(raw_name, kind)
        return

    raw_url = next((str(row.get(k, "")).strip() for k in link_cols
                    if str(row.get(k, "")).strip()), "")
    if not raw_url:
        st.info("Bu soruya henüz medya eklenmemiş. Sheets'te dosya adını yazın.")
        return
    url = _media_link(raw_url)
    if not url:
        # Backward compatibility: a filename placed into the old GorselURL/
        # VideoURL column is also accepted, so no Sheets migration is needed.
        _show_drive_media_by_name(raw_url, kind)
        return
    drive_id = _drive_file_id(url)
    try:
        if kind == "photo":
            view_url = f"https://drive.google.com/thumbnail?id={drive_id}&sz=w1600" if drive_id else url
            st.image(view_url, caption="Soruyla ilgili görüntü", use_container_width=True)
        elif drive_id:
            components.iframe(f"https://drive.google.com/file/d/{drive_id}/preview", height=475, scrolling=False)
            st.caption("Drive video bağlantısında izleyici erişimi gerekir. Özel dosyalar için 'VideoDosya' sütununu kullanın.")
        elif urlparse(url).hostname in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}:
            st.video(url, loop=True)
        else:
            _show_question_video(url)
    except Exception:
        st.warning("URL ile medya gösterilemedi. Drive klasöründeki dosya adını kullanabilirsiniz.")


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
    "apex": (r"\b(?:apeks\w*|apex\w*|"
             r"api[kc]al(?! (?:[2345]|iki|uc|dort|bes|two|three|four|five|kesit\w*|pencere\w*|view\w*)\b)\w*|"
             r"tak[oa]\s*tsubo\w*|stres\w* (?:(?:induklu|induced) )?(?:kardiyomiyopati\w*|cardiomyopath\w*)|kirik kalp sendrom\w*)\b"),
    "prosthesis": (r"\b(?:protez\w*|prosthe(?:sis|tic)\w*|biyoprotez\w*|bioprotez\w*|bioprosthe\w*|"
                  r"(?:mekanik|mechanical) (?:\w+ ){0,2}(?:kapak\w*|kapag\w*|val[vf]\w*)|"
                  r"paravalv\w*|pannus\w*|tavi|tavr|hasta protez uyumsuz\w*)\b"),
    "valve_mass": (r"\b(?:ve[gj]etasyon\w*|vegetation\w*|endokardit\w*|endocarditis|nbte|"
                  r"(?:fibroelastom|miksom|myxom)\w*|libman sacks|(?:kardiyak|intrakardiyak|intrakardiyal|valvuler|"
                  r"intrakardial|kardiyal|kalpteki|kalp|kapak\w*|kapag\w*) (?:\w+ ){0,2}(?:kitle\w*|tumor\w*)|"
                  r"(?:(?:kardiyak|intrakardiyak|valvuler|kapak\w*|kapag\w*|protez\w*) (?:uzerinde\w* )?tromb\w*)|"
                  r"(?:cardiac|intracardiac|valvular|valve) (?:\w+ ){0,2}(?:mass\w*|tumou?r\w*|thromb\w*))\b"),
    "cardiomyopathy": r"\b(?:kardiyo?miyopati\w*|kardiyomyopati\w*|cardiomyopath\w*|kmp|hcm|hkm|hocm|dcm|dkm|arvc|lvnc)\b",
    "myocardium": (r"\b(?:miyokar[dt](?:i|in|ina)?(?! (?:enfarkt|infarkt|iskemi))|myocardium|kalp kas\w*|endokardit\w*|endocarditis|"
                   r"(?:miyokard|myokard|myocard|perikard|pericard|miyoperikard|myopericard|perimiyokard|perimyocard)it\w*)\b"),
}
_ATLAS_PATTERNS = {key: re.compile(pattern) for key, pattern in _ATLAS_TERMS.items()}
_ATLAS_CLINICAL_TOPICS = {"apex", "prosthesis", "valve_mass", "myocardium", "cardiomyopathy"}
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
            label = _atlas_fold(part)
            if label in {"kitle", "kitleler", "trombus", "thrombus"}:
                topics.add("valve_mass")
            elif label == "ie":
                topics.update(("valve_mass", "myocardium"))
    # Clinical terms may cross a structure boundary, e.g. "mekanik aort kapağı".
    topics.update(key for key in _ATLAS_CLINICAL_TOPICS if _ATLAS_PATTERNS[key].search(normalized))
    # Consume the more specific phrase before matching its containing structure.
    for key in ("aortic_valve", "laa"):
        pattern = _ATLAS_PATTERNS[key]
        if pattern.search(normalized):
            topics.add(key)
            normalized = pattern.sub(" ", normalized)
    topics.update(key for key, pattern in _ATLAS_PATTERNS.items()
                  if key not in _ATLAS_CLINICAL_TOPICS and pattern.search(normalized))
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
            category_topics = _atlas_topics(row.get("Kategori"), as_tags=True)
            stem_topics = _atlas_topics(stem)
            topics = category_topics | (stem_topics & _ATLAS_CLINICAL_TOPICS) if category_topics else stem_topics
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
    .valve-views{margin-top:8px;align-items:center}.valve-views span{font-size:11px;color:#c3d3cf;margin-right:3px}
    .valve-views button{font-size:11px;padding:5px 9px}
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
    #topic-detail{font-size:12px;color:var(--mute);line-height:1.45;margin:-6px 0 15px}
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
    .login-notice{margin:16px 0 6px;padding:18px 16px;border:1px solid #d2dfd1;border-radius:9px;background:#eff5ec;color:#315745;font-size:15px;line-height:1.55}
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
  <div class="intro"><div><h1>Kalp atlası</h1><p id="atlas-instructions">Kalbi sürükleyerek döndürün. Bir yapıya dokunarak inceleyin.</p></div><div class="course" hidden><span id="course-label"></span></div></div>
  <main>
    <section aria-label="Etkileşimli anatomik model">
      <div class="model">
        <div class="panel-head"><h2>Anatomik görünüm</h2><span class="phase"><i id="beat-indicator"></i><span id="phase">Diyastol</span></span></div>
        <div class="views" role="group" aria-label="Model görünümü">
          <button data-view="front" aria-pressed="true">Ön</button><button data-view="back" aria-pressed="false">Arka</button><button data-view="valves" aria-pressed="false">Kapak düzlemi</button><button data-view="inferior" aria-pressed="false">Alt</button>
        </div>
        <div id="valve-views" class="views valve-views" role="group" aria-label="Mitral kapak görünümü" hidden>
          <span>Mitral konum</span><button type="button" data-valve="valves" aria-pressed="true">Doğal kapak</button><button type="button" data-valve="prosthetic" aria-pressed="false">Mekanik protez</button>
        </div>
        <div id="viewport" class="viewport" tabindex="0" role="group" aria-label="Döndürülebilen kalp modeli. Ok tuşlarıyla döndürün veya sorular için yapı listesini kullanın."><canvas id="heart"></canvas><canvas id="overlay" aria-hidden="true"></canvas></div>
        <div class="tools"><div class="toolgroup"><button id="motion" type="button">Durdur</button><button id="guides" type="button" aria-pressed="true">Etiketler</button></div><div class="toolgroup"><button class="sign" id="zoom-out" aria-label="Uzaklaştır">−</button><button class="sign" id="zoom-in" aria-label="Yakınlaştır">+</button><button id="home" title="Geçerli görünümün başlangıç açısına dön">Açıyı sıfırla</button></div></div>
      </div>
      <div class="model-foot"><span><strong>3B + zaman</strong> · Şematik kalp döngüsü</span><span id="region-count"></span></div>
    </section>
    <section class="right" id="quiz" aria-label="Seçilen yapının soruları">
      <div class="right-top"><span class="right-kicker">Seçilen yapı</span><span class="source-badge" id="source" hidden></span></div>
      <label class="select-wrap"><span class="sr">Anatomik yapı seç</span><select id="region"></select></label>
      <p id="topic-detail" hidden></p>
      <p class="login-notice" id="login-notice" role="status">Soruları görmek için kullanıcı adı girin.</p>
      <div id="question-content" hidden>
      <div class="meter-label"><span id="q-index"></span><span id="score"></span></div>
      <div id="exercise"><h2 class="question" id="stem"></h2><div class="options" id="choices" role="group" aria-labelledby="stem"></div><div id="feedback" class="feedback" role="status" hidden></div></div>
      <div class="end" id="complete" hidden><h3>Bu yapı tamamlandı.</h3><p id="result"></p></div>
      <button class="primary" id="submit" type="button">Yanıtı kontrol et</button>
      <div class="actions"><button class="text-button mobile-back" id="to-model">↑ Modele dön</button><button class="text-button" id="flag" hidden>Soruyu düzeltme için bildir</button></div><p class="flag-status" role="status" id="flag-status"></p>
      </div>
    </section>
  </main>
  <p class="bank-notice" id="bank-note"></p>
</div>
<script>
'use strict';
const CATALOG={"regions": [{"id": "aorta", "name": "Aorta", "short": "Aorta", "group": "Büyük damarlar", "view": "front"}, {"id": "mitral", "name": "Mitral kapak", "short": "Mitral kapak", "group": "Kapaklar", "view": "valves"}, {"id": "laa", "name": "Sol atriyal apendiks", "short": "Sol atriyal apendiks", "group": "Kalp boşlukları", "view": "front"}, {"id": "hepatic", "name": "Hepatik venler", "short": "Hepatik venler", "group": "Büyük damarlar", "view": "inferior"}, {"id": "aortic_valve", "name": "Aort kapağı", "short": "Aort kapağı", "group": "Kapaklar", "view": "valves"}, {"id": "tricuspid", "name": "Triküspit kapak", "short": "Triküspit", "group": "Kapaklar", "view": "valves"}, {"id": "pulmonary_valve", "name": "Pulmoner kapak", "short": "Pulmoner kapak", "group": "Kapaklar", "view": "valves"}, {"id": "lv", "name": "Sol ventrikül", "short": "Sol ventrikül", "group": "Kalp boşlukları", "view": "front"}, {"id": "rv", "name": "Sağ ventrikül", "short": "Sağ ventrikül", "group": "Kalp boşlukları", "view": "front"}, {"id": "la", "name": "Sol atriyum", "short": "Sol atriyum", "group": "Kalp boşlukları", "view": "back"}, {"id": "ra", "name": "Sağ atriyum", "short": "Sağ atriyum", "group": "Kalp boşlukları", "view": "front"}, {"id": "pa", "name": "Pulmoner arter", "short": "Pulmoner arter", "group": "Büyük damarlar", "view": "front"}, {"id": "pv", "name": "Pulmoner venler", "short": "Pulmoner venler", "group": "Büyük damarlar", "view": "back"}, {"id": "svc", "name": "Vena kava superior", "short": "V. kava superior", "group": "Büyük damarlar", "view": "front"}, {"id": "ivc", "name": "Vena kava inferior", "short": "V. kava inferior", "group": "Büyük damarlar", "view": "inferior"}]};
CATALOG.regions.push(
  {id:'apex',name:'Sol ventrikül apeksi',short:'Apeks',group:'Kalp duvarı',view:'front'},
  {id:'cardiomyopathy',name:'Kardiyomiyopatiler',short:'Kardiyomiyopatiler',group:'Kalp duvarı',view:'valves'},
  {id:'myocardium',name:'Kalp kası (miyokart)',short:'Miyokart',group:'Kalp duvarı',view:'front',detail:'Bu bölümde endokardit, miyokardit ve perikardit vakalarını tutulan yapıya göre ayırt edebilirsiniz.'},
  {id:'prosthesis',name:'Protez kapak',short:'Protez kapak',group:'Kapaklar',view:'prosthetic',detail:'Modelde mitral konumda çift diskli mekanik protez görülüyor. Sorular aort ve mitral protezlerini kapsar.'},
  {id:'valve_mass',name:'Kapak üzerindeki kitle',short:'Kapak kitlesi',group:'Kapaklar',view:'valves',detail:'Triküspit yaprakçığına bağlı kitle şematiktir. Her vakada kitleyi soruda verilen bulgularla değerlendirin.'}
);

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
  if (['lv','rv','apex','myocardium'].includes(id)){
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
  mitral:'#e1b892',tricuspid:'#bdcdbc',aortic_valve:'#e1a078',pulmonary_valve:'#a8cbd4',
  apex:'#d89176',myocardium:'#ad4f4f',prosthesis:'#bcc9c9',valve_mass:'#e2b660'
};
const rgb = h => [1,3,5].map(i=>parseInt(h.slice(i,i+2),16)/255);

function buildHeart(){
  const vertices=[], indices=[], landmarks={};
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
  // All adjacent patches share the original ventricular surface and the same motion.
  // Each triangle has one selectable structure, including at the edge of the apex.
  const tip=.22, muscleLow=.31, muscleHigh=.71;
  function ventricularPoint(side,t,u,offset=0){
    const a=front(t), b=back(t);
    return vent(t,side==='rv'?a+(b-a)*u:b+(a+TAU-b)*u,offset);
  }
  function wallBand(id,side,start,end,rows,columns){
    surface(id,0,columns,rows,(u,v)=>ventricularPoint(side,start+(end-start)*v,u),palette[id],false);
  }
  for(const [side,columns] of [['rv',40],['lv',46]])wallBand('apex',side,0,tip,10,columns);
  wallBand('lv','lv',tip,1,27,46);
  wallBand('rv','rv',tip,muscleLow,4,40);
  wallBand('rv','rv',muscleHigh,1,11,40);
  function muscleEdges(v){
    const center=.19+.06*v, width=.153*Math.pow(Math.max(0,Math.sin(pi*v)),.7);
    return [0,center-width,center+width,1];
  }
  for(const [i,id,columns] of [[0,'rv',12],[1,'myocardium',16],[2,'rv',31]]){
    surface(id,0,columns,20,(u,v)=>{
      const edges=muscleEdges(v), t=muscleLow+(muscleHigh-muscleLow)*v;
      return ventricularPoint('rv',t,edges[i]+(edges[i+1]-edges[i])*u);
    },palette[id],false);
  }
  // Parallel fascicles mark the schematic window onto the ventricular muscle.
  for(const f of [.15,.32,.49,.66,.83]){
    surface('myocardium',0,2,18,(u,v)=>{
      const h=.11+.77*v, t=muscleLow+(muscleHigh-muscleLow)*h;
      const [,left,right]=muscleEdges(h), along=f+.12*(v-.5)+.010*(u-.5);
      return ventricularPoint('rv',t,left+(right-left)*along,.005);
    },'#d68473',false);
  }
  for(const [id,p] of [['apex',ventricularPoint('lv',.115,.85)],['myocardium',ventricularPoint('rv',.50,.222)]]){
    landmarks[id]=[p,beatPoint(p,id,1)];
  }
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
  landmarks.cardiomyopathy=[section(.10,.86,0),section(.10,.86,1)];
  surface('cardiomyopathy',2,144,52,section,'#b16c64',true,true,inOrifice);
  surface('rv',2,96,10,(u,v,b)=>{
    const p=section(u,1,b),r=1-.10*v;
    return [p[0]*r,p[1]-.35*v,p[2]*r];
  },'#99615b',true,true);

  for(const [id,x,y,z,rx,rz,n,turn] of valves){
    const av=id==='mitral'||id==='tricuspid';
    // Layer 2 is shared. Layers 3 and 4 occupy the same mitral orifice in alternative views.
    const layer=id==='mitral'?3:2;
    function place(xx,yy,zz,beat){
      return [x+xx*Math.cos(turn)-zz*Math.sin(turn),y+yy-.10*beat,z+zz*Math.cos(turn)+xx*Math.sin(turn)];
    }
    surface(id,layer,48,10,(u,v,b)=>{
      const a=u*TAU, t=v*TAU, ridge=av?.023:.019;
      return place((rx+ridge*Math.cos(t))*Math.cos(a),ridge*Math.sin(t)+.028*Math.cos(2*a),(rz+ridge*Math.cos(t))*Math.sin(a),b);
    },palette[id],true,true);
    surface(id,layer,40,9,(u,v,b)=>{
      const a=u*TAU, r=1-.987*v;
      return place(rx*r*Math.cos(a),-.049-.56*Math.pow(v,.62),rz*r*Math.sin(a),b);
    },av?'#642f41':'#603e49',true,true);
    function leaflet(l,u,v,b){
      const theta=(l+u)*TAU/n+(av?0:pi/6), scallop=Math.sin(pi*u);
      const open=av?1-b:b, radius=1-v*((1-open)*.985+open*(.16+.22*scallop));
      let xx=rx*radius*Math.cos(theta), zz=rz*radius*Math.sin(theta);
      if(n===2){
        xx=rx*Math.cos(theta)*(1-.12*v);
        zz=rz*Math.sin(theta)*(1-v*(.992-open*.54));
      }
      const deep=av?-.17*open:.085*open;
      const yy=.027*Math.cos(2*theta)*(1-v)+v*(deep*scallop-.037)+.058*Math.sin(pi*v)*scallop;
      return place(xx,yy,zz,b);
    }
    for(let l=0;l<n;l++){
      surface(id,layer,20,9,(u,v,b)=>leaflet(l,u,v,b),mix(rgb(palette[id]),[1,.87,.76],l%2?.08:.20),false,true);
    }
    if(id==='tricuspid'){
      // The pedicle stays attached to the atrial face of this moving leaflet.
      function massCenter(v,b){
        const root=leaflet(0,.77,.32,b);
        return add(root,[-v*(.125+.09*b),.25*v,v*(.045-.04*b)]);
      }
      surface('valve_mass',2,30,18,(u,v,b)=>{
        const a=TAU*u, body=Math.pow(Math.max(0,Math.sin(pi*v)),.70);
        const radius=.019*(1-v)+(.067+.109*v)*body;
        const lobe=1+.17*Math.cos(3*a+2*v)+.08*Math.sin(5*a-4*v);
        return add(massCenter(v,b),[radius*lobe*Math.cos(a),.022*body*Math.cos(2*a+v),radius*lobe*Math.sin(a)]);
      },palette.valve_mass,true,true);
      landmarks.valve_mass=[massCenter(.63,0),massCenter(.63,1)];
    }
    if(id==='mitral'){
      const prostheticLayer=4, radius=.354;
      // A circular sewing cuff sits inside the native annular footprint.
      function rim(major,minor,height,color){
        surface('prosthesis',prostheticLayer,64,12,(u,v,b)=>{
          const angle=u*TAU, crossSection=v*TAU, r=major+minor*Math.cos(crossSection);
          return place(r*Math.cos(angle),height+minor*Math.sin(crossSection),r*Math.sin(angle),b);
        },color,true,true);
      }
      // The outer cuff bridges the native annulus to the circular mechanical housing.
      surface('prosthesis',prostheticLayer,64,5,(u,v,b)=>{
        const a=u*TAU, cuff=.020*Math.sin(pi*v);
        return place(((1-v)*(rx+.022)+v*radius)*Math.cos(a),.020+cuff,
                     ((1-v)*(rz+.020)+v*radius)*Math.sin(a),b);
      },'#aabdc0',true,true);
      rim(radius,.029,.042,'#dbe1d9');rim(radius-.027,.015,.033,'#647d87');
      // A dark recess gives the openings depth when the occluders swing into the ventricle.
      surface('prosthesis',prostheticLayer,48,8,(u,v,b)=>{
        const a=u*TAU, r=(radius-.022)*(1-v);
        return place(r*Math.cos(a),-.40-.08*v,r*Math.sin(a),b);
      },'#423a46',true,true);
      for(const sign of [-1,1]){
        const disk=(u,v,b)=>{
          const a=pi*u, r=radius-.045, hinge=.102, d=r*Math.sin(a)*v-hinge;
          const angle=(76-72*b)*pi/180;
          return place(r*Math.cos(a),.034-d*Math.sin(angle),sign*(.007+hinge+d*Math.cos(angle)),b);
        };
        surface('prosthesis',prostheticLayer,38,8,disk,'#465560',false,true);
        surface('prosthesis',prostheticLayer,38,2,(u,v,b)=>{
          const p=disk(u,.96+.04*v,b);p[1]+=.004;return p;
        },'#a6b9b9',false,true);
      }
      landmarks.prosthesis=[0,1].map(b=>place(radius,.063,0,b));
    }
  }
  return {vertices:new Float32Array(vertices), indices:new Uint16Array(indices), landmarks};
}

const PRESETS={
  front:{yaw:-.16,tilt:.19,center:[-.08,.33,0],zoom:1},
  back:{yaw:pi-.11,tilt:.13,center:[-.07,.31,-.05],zoom:1},
  valves:{yaw:-.075,tilt:1.32,center:[0,.56,.11],zoom:1.62},
  inferior:{yaw:-.79,tilt:-.25,center:[-.30,-.27,-.22],zoom:1.18}
};
PRESETS.prosthetic=PRESETS.valves;
const sectionLayer=view=>view==='valves'?3:view==='prosthetic'?4:0;
const ANCHORS={
  aorta:[-.17,1.72,.27],mitral:[.54,.69,-.40],laa:[1.04,1.12,.11],hepatic:[-1.35,-.87,-.27],
  tricuspid:[-.58,.67,-.02],aortic_valve:[-.037,.79,.07],pulmonary_valve:[.28,.82,.58],
  lv:[.69,-.72,.58],rv:[-.47,-.11,.79],la:[.27,1.12,-.82],ra:[-1.13,.72,.35],
  pa:[.29,1.18,.60],pv:[.95,1.06,-.72],svc:[-.98,1.67,-.08],
  ivc:[-.96,-1.27,-.37]
};
// The overlay only shows landmarks in a preset orientation. Free rotation uses surface picking.
const GUIDE={
  front:[['aorta',-1,-24],['laa',1,-4],['myocardium',-1,-7],['hepatic',-1,18],['lv',1,4],['apex',1,11]],
  back:[['pv',-1,-21],['la',1,-19],['ivc',1,20]],
  valves:[['mitral',1,-16],['tricuspid',-1,-8],['valve_mass',-1,24],['aortic_valve',-1,-60],['pulmonary_valve',1,35],['cardiomyopathy',1,20]],
  prosthetic:[['prosthesis',1,-16],['tricuspid',-1,-8],['valve_mass',-1,24],['aortic_valve',-1,-60],['pulmonary_valve',1,35],['cardiomyopathy',1,20]],
  inferior:[['hepatic',-1,-14],['ivc',1,28],['ra',-1,-36],['apex',1,15]]
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
      if(cut<0.5 ? layer>1.5 : (abs(layer-2.0)>.25 && abs(layer-cut)>.25)) visible=0.0;
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
    gl.uniform1f(u.phase,s.phase);gl.uniform1f(u.cut,sectionLayer(s.view));
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
    const pix=img.data, cut=sectionLayer(s.view);
    for(let t=0;t<ix.length;t+=3){
      const info=v[16*ix[t]+15],layer=Math.floor(info/32);
      if(cut ? layer!==2&&layer!==cut : layer>1) continue;
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
  let tags=[],dirty=true,inView=true,last=0,tick=null,drag=null,lastValveView='valves';
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
      const endpoints=mesh.landmarks[id];
      let p=endpoints?mix(endpoints[0],endpoints[1],s.phase):beatPoint(ANCHORS[id],id,s.phase);
      if(!endpoints&&sectionLayer(s.view))p=[p[0],p[1]-.10*s.phase,p[2]];
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
    const onPlane=Boolean(sectionLayer(id));
    if(onPlane)lastValveView=id;
    document.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.view===(onPlane?'valves':id))));
    document.getElementById('valve-views').hidden=!onPlane;
    document.querySelectorAll('[data-valve]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.valve===id)));
    refresh();
  }
  function zoom(step){s.zoomExtra=clamp(s.zoomExtra*step,.72,1.85);refresh();}
  function motion(){
    const b=document.getElementById('motion');b.textContent=s.playing?'Durdur':'Oynat';
    b.setAttribute('aria-label',s.playing?'Kalp hareketini durdur':'Kalp hareketini oynat');b.setAttribute('aria-pressed',String(!s.playing));
  }
  function toggle(){s.playing=!s.playing;last=0;motion();refresh();}
  document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>view(b.dataset.view==='valves'?lastValveView:b.dataset.view)));
  document.querySelectorAll('[data-valve]').forEach(b=>b.addEventListener('click',()=>{
    view(b.dataset.valve);onPick(b.dataset.valve==='prosthetic'?'prosthesis':'mitral',false);
  }));
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
    if(fromList){
      const sharedValve=r.view==='valves'&&id!=='mitral';
      view(sharedValve?lastValveView:r.view);
    }else refresh();
  },getView:()=>s.view};
}

const byId = id=>document.getElementById(id);
const allRegions=CATALOG.regions;
byId('region-count').textContent=allRegions.length+' seçilebilir yapı';
const regions=Object.fromEntries(allRegions.map(r=>[r.id,r]));
const select=byId('region'), optionLetters='ABCDE';
const state={scope:'neu-kalp-atlasi-guest',banks:{},records:{},region:'aorta',questionsEnabled:false,bankStatus:'locked',flags:new Set(),pendingFlag:null};
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
function bankFor(id){return state.banks[id] || [];}
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
  const id=state.region,enabled=state.questionsEnabled;
  select.value=id;
  byId('question-content').hidden=!enabled;
  byId('login-notice').hidden=enabled;
  byId('source').hidden=!enabled;
  byId('course-label').parentElement.hidden=!enabled;
  byId('atlas-instructions').textContent=enabled?'Kalbi sürükleyerek döndürün. Bir yapıya dokunup sorusunu çözün.':'Kalbi sürükleyerek döndürün. Bir yapıya dokunarak inceleyin.';
  if(!enabled || !bankFor(id).length){
    byId("question-content").hidden=true;
    byId("source").hidden=true;
    byId("course-label").parentElement.hidden=true;
    for(const field of ['stem','choices','feedback','q-index','score','result','flag-status','bank-note','topic-detail','course-label'])byId(field).replaceChildren();
    byId('topic-detail').hidden=true;
    byId('bank-note').hidden=!enabled;
    if(enabled) byId('bank-note').textContent=state.bankStatus==='ready'?'Bu bölge için henüz aktif soru yok.':'Soru bankası şu anda okunamıyor.';
    byId('submit').disabled=true;
    return;
  }
  const {q,rec,bank}=current();
  const answered=Object.hasOwn(rec.answers,q.id),selection=answered?rec.answers[q.id]:rec.pick;
  const totalAnswered=Object.keys(rec.answers).length,score=scoreOf(rec,bank),fromSheet=q.id.startsWith('s-');
  select.value=id;
  const detail=byId('topic-detail');
  detail.textContent=regions[id].detail||'';detail.hidden=!detail.textContent;
  byId('source').textContent='Kurum bankası';
  byId('source').classList.toggle('bank',fromSheet);
  byId('q-index').textContent=rec.done?'Tur tamamlandı':'Soru '+(rec.index+1)+' / '+bank.length;
  byId('score').textContent=score+' doğru · '+(totalAnswered-score)+' yanlış';
  byId('exercise').hidden=rec.done;byId('complete').hidden=!rec.done;
  byId('stem').textContent=q.stem;
  const choices=byId('choices');choices.replaceChildren();
  q.options.forEach(([letter,text])=>{
    const button=make('button','opt');button.type='button';button.disabled=answered;
    button.setAttribute('aria-pressed',String(selection===letter));button.append(make('span','letter',letter),document.createTextNode(text));
    if(answered&&letter===q.key)button.classList.add('correct');
    if(answered&&letter===selection&&letter!==q.key)button.classList.add('wrong');
    button.onclick=()=>{
      if(!state.questionsEnabled||rec.done||Object.hasOwn(rec.answers,q.id))return;
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
  const available=allRegions.filter(r=>bankFor(r.id).length);
  const done=available.reduce((n,r)=>n+(recordFor(r.id).done?1:0),0);
  byId('course-label').textContent=done+' / '+available.length+' yapı tamamlandı';
  const note=byId('bank-note');
  note.hidden=true;
}
function choose(id,fromList=false,move=false){
  if(!Object.hasOwn(regions,id))return;
  state.region=id;model?.setRegion(id,fromList);render();storeState();
  if(move&&state.questionsEnabled&&window.matchMedia('(max-width:740px)').matches)byId('quiz').scrollIntoView({block:'start',behavior:'instant'});
}
for(const group of [...new Set(allRegions.map(r=>r.group))]){
  const og=make('optgroup');og.label=group;
  for(const r of allRegions.filter(r=>r.group===group)){const opt=make('option','',r.name);opt.value=r.id;og.append(opt);}
  select.append(og);
}
select.onchange=()=>choose(select.value,true);
byId('to-model').onclick=()=>byId('viewport').scrollIntoView({block:'center'});
let atlasStreak=0;
byId('submit').onclick=()=>{
  if(!state.questionsEnabled || !bankFor(state.region).length)return;
  const {rec,q,bank}=current();
  if(rec.done){atlasStreak=0;delete state.records[state.region];recordFor(state.region);}
  else if(Object.hasOwn(rec.answers,q.id)){
    rec.pick=null;
    if(rec.index+1>=bank.length)rec.done=true;else rec.index++;
  }else if(q.options.some(([letter])=>letter===rec.pick)){rec.answers[q.id]=rec.pick;
    atlasStreak=rec.pick===q.key ? atlasStreak+1 : 0;
    if(atlasStreak && frameOrigin){
      post('setComponentValue',{dataType:'json',value:{type:'streak',qid:q.id,nonce:crypto.randomUUID(),streak:atlasStreak}});
    }
  }
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
  if(!state.questionsEnabled || !bankFor(state.region).length)return;
  const {q}=current();
  if(!frameOrigin||!q.id.startsWith('s-')||state.pendingFlag||state.flags.has(q.id))return;
  state.pendingFlag={qid:q.id,nonce:Date.now().toString(36)+'-'+Math.random().toString(36).slice(2,9)};
  render();post('setComponentValue',{dataType:'json',value:state.pendingFlag});
};
window.addEventListener('message',e=>{
  if(e.source!==window.parent||e.data?.type!=='streamlit:render'||!e.data.args?.atlasScope)return;
  if(frameOrigin&&e.origin!==frameOrigin)return;
  frameOrigin=e.origin==='null'?'*':e.origin;
  const args=e.data.args,nextScope='neu-kalp-atlasi-'+args.atlasScope;
  const changed=state.scope!==nextScope;
  if(changed){state.scope=nextScope;state.pendingFlag=null;atlasStreak=0;loadState();}
  state.questionsEnabled=args.questionsEnabled===true;
  state.banks=state.questionsEnabled?(args.banks||{}):{};state.bankStatus=args.status;
  const ack=args.ack;
  if(ack&&ack.nonce===state.pendingFlag?.nonce){
    state.pendingFlag=null;
    if(ack.ok){state.flags.add(ack.qid);storeState();}
  }
  if(changed)model?.setRegion(state.region,true);
  render();if(state.questionsEnabled&&ack&&!ack.ok&&current().q?.id===ack.qid)byId('flag-status').textContent='Kaydedilemedi. Yeniden deneyebilirsiniz.';
  frameHeight();
});
loadState();render();
model=mountHeart((id,move=true)=>choose(id,false,move));model.setRegion(state.region,true);
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

def _quiz_records_sheet():
    book = connect_to_gsheets().open_by_key(MEDIA_SHEET_ID)
    try:
        return book.worksheet("SeriRekorlari")
    except gspread.WorksheetNotFound:
        try:
            return book.add_worksheet(title="SeriRekorlari", rows=1000, cols=3)
        except gspread.exceptions.APIError:
            return book.worksheet("SeriRekorlari")


def _rank_quiz_records(rows, mode):
    best = {}
    for row in rows:
        if len(row) < 3 or row[0] != mode or not row[2].isdigit():
            continue
        name, score = row[1], int(row[2])
        key = name.casefold()
        if score > best.get(key, ("", 0))[1]:
            best[key] = (name, score)
    return sorted(best.values(), key=lambda entry: (-entry[1], entry[0].casefold()))


def _record_quiz_streak(mode, streak):
    if streak < 1:
        return
    sheet = _quiz_records_sheet()
    name = st.session_state.quiz_player
    ranks = _rank_quiz_records(sheet.get_all_values(), mode)
    if all(player.casefold() != name.casefold() or score < streak for player, score in ranks):
        sheet.append_row([mode, name, streak], value_input_option="RAW")


def _render_heart_atlas():
    player = st.session_state.get("quiz_player", "")
    questions_enabled = bool(player)
    banks, lookup, status = _atlas_read_bank(MEDIA_SHEET_ID, QUESTION_WS_INDEX) if questions_enabled else ({}, {}, "locked")
    component = components.declare_component("neu_kalp_atlasi", path=_atlas_directory(_ATLAS_HTML).name)
    scope = hashlib.sha256(f"{MEDIA_SHEET_ID}/{QUESTION_WS_INDEX}/{player.casefold()}".encode()).hexdigest()[:12]
    previous = st.session_state.get("atlas_review_ack", {})
    event = component(atlasScope=scope, questionsEnabled=questions_enabled, banks=banks, status=status, ack=previous,
                      key=f"neu_kalp_atlasi_{scope}", default=None)
    if not questions_enabled or not isinstance(event, dict):
        return
    uid, nonce = event.get("qid"), event.get("nonce")
    if not isinstance(uid, str) or not isinstance(nonce, str) or not 1 <= len(nonce) <= 80 or previous.get("nonce") == nonce:
        return
    if event.get("type") == "streak":
        streak = event.get("streak")
        if type(streak) is int and streak > 0:
            try:
                _record_quiz_streak("Kalp atlası", streak)
            except gspread.exceptions.GSpreadException:
                st.warning("Atlas rekoru kaydedilemedi. Yeniden denemek için sayfada bir işlem yapın.")
                return
        st.session_state.atlas_review_ack = {"nonce": nonce, "ok": True}
        st.rerun()
    target = lookup.get(uid)
    ok = bool(target and flag_question_for_review(MEDIA_SHEET_ID, QUESTION_WS_INDEX, *target))
    st.session_state.atlas_review_ack = {"qid": uid, "nonce": nonce, "ok": ok}
    st.rerun()


# ===================== KLİNİK ÇALIŞMALAR =====================
CLINICAL_STUDIES = (
    "🏥 H-Type HT Çalışması",
    "🫀 AV tam blok-ileti sistemi pacing",
    "🫀 AFMR – TEE LV-GLS",
    "⚡ Kardiyoversiyon-Ablasyon / TEE-GLS",
    "🫁 PBMV – RV-PA Coupling",
)


# ===================== KATETERİZASYON SİMÜLASYONU (HTML) =====================
_CATH_SIM_HTML = r"""<!DOCTYPE html>
<html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Kardiyak Kateterizasyon Simülasyonu</title>
<style>
:root{--bg:#f4f6f9;--card:#fff;--tx:#1b2430;--mu:#5d6b7c;--bd:#dde2e8;--grid:#e3e8ee;--ac:#c0392b;--sh:#eef1f5;box-sizing:border-box;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0f141a;--card:#18202a;--tx:#e6ebf1;--mu:#9aa7b6;--bd:#2a3542;--grid:#27313d;--sh:#212b37;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#0f141a;--card:#18202a;--tx:#e6ebf1;--mu:#9aa7b6;--bd:#2a3542;--grid:#27313d;--sh:#212b37;color-scheme:dark}
html{scroll-padding-top:env(safe-area-inset-top,0px)}
body{margin:0;background:var(--bg);color:var(--tx);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding:16px}
h1{font-size:21px;margin:4px 0}.sub{color:var(--mu);margin:0 0 12px}
.bar{display:flex;flex-wrap:wrap;gap:14px;align-items:center;margin-bottom:10px}
select,input{font:inherit}select{padding:5px 8px;border-radius:8px;border:1px solid var(--bd);background:var(--card);color:var(--tx)}
.grp{margin:6px 0}.grp small{display:block;color:var(--mu);font-size:12px;margin-bottom:3px}
button{font:inherit;padding:6px 12px;margin:0 6px 6px 0;border-radius:18px;border:1px solid var(--bd);background:var(--card);color:var(--tx);cursor:pointer}
button.on{background:var(--ac);border-color:var(--ac);color:#fff}
.grid{display:grid;grid-template-columns:1fr 290px;gap:12px;margin:10px 0}
@media(max-width:760px){.grid{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:12px;margin-bottom:12px}
canvas{display:block;width:100%;height:300px}
#live{font-size:13px;margin-top:6px;display:flex;flex-direction:column;gap:2px}
#live b{font-variant-numeric:tabular-nums}
svg{width:100%;height:auto;max-height:360px}
svg .ch{fill:var(--sh);stroke:var(--bd)}svg text{fill:var(--mu);font-size:11px}
svg .pth{fill:none;stroke:var(--mu);stroke-width:2;stroke-dasharray:4 3;opacity:.7}
svg .dt{fill:var(--bd)}svg .dt.on{fill:var(--ac);stroke:var(--tx);stroke-width:1.5}
#info h2{font-size:17px;margin:0 0 6px}#info ul{margin:6px 0;padding-left:20px}
.tag{display:inline-block;font-size:12px;color:var(--mu);margin-right:6px}
.nm{background:var(--sh);padding:6px 10px;border-radius:8px;margin:6px 0}
.pit{border-left:3px solid var(--ac);padding-left:10px;margin:8px 0}
.foot{color:var(--mu);font-size:12px}.sg{display:grid;grid-template-columns:repeat(auto-fit,minmax(135px,1fr));gap:8px}.sg div{background:var(--sh);border-radius:8px;padding:6px 10px}.sg small{display:block;color:var(--mu);font-size:11px}.sg b{font-size:17px}.sg .al b{color:var(--ac)}.cp{fill:none;stroke:var(--mu);stroke-width:2;stroke-dasharray:4 3;opacity:.4}.cp.on{stroke:var(--ac);stroke-width:3;stroke-dasharray:none;opacity:.95}svg .dt{stroke:var(--mu);stroke-width:1}.tabs{display:flex;gap:6px;margin:6px 0 10px}.tabs button{margin:0;border-radius:10px}#where{margin-top:6px}
summary{cursor:pointer;font-weight:600}
</style></head><body><div class="wrap">
<h1>Sağ ve Sol Kalp Kateterizasyonu Simülasyonu</h1>
<p class="sub">Kateter pozisyonunu ve klinik senaryoyu seçin; basınç dalgalarını EKG ile birlikte izleyin.</p>
<div class="tabs"><button data-t="k" class="on">Klasik</button><button data-t="c">Canlı</button></div>
<div class="bar">
<label>Senaryo <select id="sc"></select></label>
<label>Kalp hızı <input type="range" id="hr" min="50" max="120" value="70"> <b id="hrv">70</b>/dk</label>
<span>Tansiyon <b id="bp">–</b> mmHg</span>
<label><input type="checkbox" id="rs" checked> Solunum</label>
<label><input type="checkbox" id="mkc" checked> Ölçüm noktaları</label>
</div>
<div id="livectl" class="card" hidden>
<div class="grp"><small>Kateter yolu (kalp üzerinde sürükleyin, kaydırıcıyı kullanın veya otomatik ilerletin)</small><button data-r="R" class="on">Sağ kalp: SVC → RA → RV → PA → wedge</button><button data-r="L">Sol kalp: Ao → LV (retrograd)</button><button data-r="T">Transseptal: RA → LA</button></div>
<div class="bar"><input type="range" id="us" min="0" max="1000" value="0" style="flex:1;min-width:180px"><button id="auto">▶ Otomatik ilerlet</button></div>
<div id="where"></div></div>
<div id="btns"></div>
<div class="grid">
<div class="card"><canvas id="cv"></canvas><div id="live"></div></div>
<div class="card"><div id="hv"></div><svg id="old" viewBox="0 0 220 240" aria-label="Kalp şeması">
<rect class="ch" x="30" y="95" width="55" height="55" rx="14"/><text x="48" y="126">RA</text>
<rect class="ch" x="40" y="155" width="60" height="68" rx="14"/><text x="58" y="192">RV</text>
<rect class="ch" x="135" y="95" width="55" height="45" rx="14"/><text x="152" y="122">LA</text>
<rect class="ch" x="108" y="145" width="72" height="78" rx="14"/><text x="136" y="188">LV</text>
<path class="pth" id="pR" d="M52,12 C52,50 56,90 57,122 C60,150 66,170 70,187 C85,150 90,110 95,75 L130,58"/>
<path class="pth" id="pL" d="M205,15 L175,70 L150,110 L145,182"/>
<path class="pth" d="M130,58 L162,118" style="opacity:.35"/>
<path class="pth" d="M57,122 L176,112" style="opacity:.35"/>
<circle class="dt" id="d-RA" cx="57" cy="122" r="7"/>
<circle class="dt" id="d-RV" cx="70" cy="187" r="7"/>
<circle class="dt" id="d-PA" cx="95" cy="75" r="7"/>
<circle class="dt" id="d-PCWP" cx="130" cy="58" r="7"/>
<circle class="dt" id="d-LA" cx="176" cy="112" r="7"/>
<circle class="dt" id="d-Ao" cx="175" cy="70" r="7"/>
<circle class="dt" id="d-LV" cx="145" cy="182" r="7"/>
<text x="102" y="78">PA</text><text x="138" y="52">wedge</text><text x="182" y="66">Ao</text>
</svg></div></div>
<div class="card" id="sum"></div>
<div class="card" id="info"></div>
<details class="card"><summary>Genel prosedür</summary>
<p><b>Sağ kalp:</b> İnternal juguler, femoral veya brakiyal ven (ultrason eşliğinde) → balonlu (Swan-Ganz) kateter RA → RV → PA → wedge sırasıyla ilerletilir. Her pozisyonda basınç ve gerekirse satürasyon alınır; kardiyak output termodilüsyon veya Fick ile bulunur, PVR = (mPAP − PAWP) / KO hesaplanır.</p>
<p><b>Sol kalp:</b> Radyal (veya femoral) arter → retrograd olarak çıkan aorta → aort kapağı geçilerek LV (aort stenozunda kılavuz telle). LVEDP, pull-back gradienti ve ventrikülografi alınır; koroner anjiyografi ile birleştirilebilir. Alternatif: transseptal yolla LA’nın doğrudan ölçümü.</p></details>
<p class="foot">Dalga biçimleri fizyolojik verilere dayanan modelle üretilmiş şematik simülasyondur; hasta kaydı değildir. Değerler eğitim amaçlıdır.</p>
</div>
<script>
const $=s=>document.querySelector(s);
const NORM={
RA:[[0,4],[.1,8],[.17,5],[.22,5.5],[.3,2],[.45,4],[.58,6],[.68,2],[.85,3]],
RV:[[0,3],[.1,6],[.18,5],[.24,12],[.3,25],[.4,23],[.5,15],[.58,3],[.7,1],[.85,3]],
PA:[[0,10],[.2,10],[.28,20],[.34,25],[.42,20],[.52,15],[.56,13],[.58,14],[.7,11],[.85,10]],
PCWP:[[0,6],[.05,6],[.2,9],[.3,6],[.45,6],[.62,10],[.75,6],[.9,5]],
Ao:[[0,80],[.2,80],[.28,110],[.34,120],[.45,105],[.53,98],[.55,95],[.57,98],[.7,90],[.85,82]],
LV:[[0,6],[.1,9],[.2,10],[.25,50],[.3,110],[.36,120],[.45,100],[.52,60],[.58,15],[.65,3],[.75,5],[.9,6]]};
const SC={
normal:{n:"Normal hemodinami",d:{},note:"Normal hemodinami: RA ortalama 2–6, PA 15–30/4–12, PAWP 6–12, LVEDP 5–12 mmHg."},
as:{n:"Aort stenozu",d:{
LV:[[0,12],[.1,15],[.2,17],[.25,60],[.3,130],[.37,180],[.45,170],[.52,100],[.58,20],[.65,8],[.75,10],[.9,11]],
Ao:[[0,70],[.2,70],[.3,85],[.38,115],[.45,118],[.52,100],[.55,92],[.57,95],[.7,82],[.85,74]],
PCWP:[[0,10],[.2,14],[.3,10],[.45,10],[.62,15],[.75,9],[.9,9]]},
note:"Aort stenozu: LV sistolik basıncı çok yüksek, Ao yükselimi yavaş ve geç (parvus et tardus), LVEDP artmış (LVH). Gradienti görmek için “LV + Aorta” modunu seçin."},
ms:{n:"Mitral stenoz",d:{
PCWP:[[0,17],[.05,18],[.15,24],[.2,21],[.3,17],[.45,16],[.6,21],[.7,18],[.85,17]],
LV:[[0,5],[.1,7],[.2,8],[.25,45],[.3,100],[.36,112],[.45,95],[.52,55],[.58,10],[.65,2],[.75,4],[.9,5]],
PA:[[0,22],[.2,22],[.28,38],[.34,45],[.42,35],[.52,28],[.56,25],[.58,26],[.7,23],[.85,22]],
RV:[[0,6],[.1,9],[.18,8],[.24,18],[.3,42],[.4,38],[.5,25],[.58,6],[.7,3],[.85,5]],
RA:[[0,6],[.1,12],[.17,8],[.22,8],[.3,4],[.45,6],[.58,8],[.68,3],[.85,5]]},
note:"Mitral stenoz: PCWP ve PA yüksek (pasif pulmoner venöz hipertansiyon), LV diyastol basıncı normal-düşük; fark diyastolik transmitral gradienttir. “PCWP + LV” modunu seçin."},
mr:{n:"Ağır mitral yetersizliği",d:{
PCWP:[[0,12],[.05,12],[.2,15],[.3,9],[.4,11],[.5,20],[.6,36],[.66,30],[.75,14],[.9,12]],
PA:[[0,20],[.2,20],[.28,35],[.34,45],[.42,36],[.52,28],[.56,24],[.58,25],[.7,22],[.85,21]]},
note:"Ağır MY: PCWP’de T dalgasından sonra dev v dalgası görülür; ortalama PCWP ve PA yükselir. v dalgasını mutlaka ortalamaya dahil edin."},
ph:{n:"Prekapiller pulmoner hipertansiyon",d:{
PA:[[0,28],[.2,28],[.28,55],[.34,72],[.42,58],[.52,42],[.56,36],[.58,38],[.7,31],[.85,29]],
RV:[[0,5],[.1,10],[.18,9],[.24,25],[.3,60],[.36,74],[.45,62],[.52,35],[.58,8],[.7,5],[.85,5]],
RA:[[0,9],[.1,14],[.17,10],[.22,10],[.3,6],[.45,8],[.58,10],[.68,6],[.85,8]]},
note:"Prekapiller PH: PA ve RV sistolik yüksek, PAWP normal (≤15), RA artmış. (mPAP − PAWP)/KO ile PVR >2 WU bulunur."},
kons:{n:"Konstriktif perikardit",d:{
RA:[[0,15],[.1,19],[.17,16],[.22,16],[.3,12],[.45,15],[.58,19],[.68,11],[.85,14]],
RV:[[0,17],[.1,19],[.18,18],[.24,25],[.3,38],[.4,34],[.5,22],[.58,6],[.65,17],[.72,18],[.85,17]],
LV:[[0,17],[.1,19],[.2,19],[.25,55],[.3,105],[.36,115],[.45,98],[.52,55],[.58,7],[.64,16],[.72,18],[.9,18]],
PA:[[0,17],[.2,17],[.28,30],[.34,38],[.42,30],[.52,24],[.56,21],[.58,22],[.7,18],[.85,17]],
PCWP:[[0,16],[.05,16],[.2,19],[.3,15],[.45,15],[.62,19],[.75,15],[.9,15]]},r:{LV:-.12,RV:.2},
note:"Konstriksiyon: RA’da belirgin x ve y inişi (M/W şekli); RV ve LV’de dip-plato (kare kök) işareti; diyastol sonu basınçlar eşitlenir (LVEDP − RVEDP ≤5 mmHg); RV sistolik 50’nin altında. Solunumda ventriküler diskordans: inspiryumda RV sistolik yükselirken LV düşer (RKMP’den ayırt ettirir)."},
tam:{n:"Kardiyak tamponad",d:{
RA:[[0,14],[.1,17],[.17,15],[.22,15],[.3,10],[.45,13],[.58,15],[.68,14.5],[.85,14]],
RV:[[0,14],[.1,16],[.18,15],[.24,18],[.3,28],[.4,26],[.5,18],[.58,14],[.7,13.5],[.85,14]],
PA:[[0,14],[.2,14],[.28,22],[.34,28],[.42,22],[.52,18],[.56,16],[.58,17],[.7,15],[.85,14.5]],
PCWP:[[0,14],[.05,14],[.2,16],[.3,13],[.45,13.5],[.62,15],[.75,14],[.9,14]],
LV:[[0,13],[.1,14],[.2,14.5],[.25,40],[.3,85],[.36,95],[.45,80],[.52,50],[.58,17],[.65,13],[.75,13.5],[.9,13]],
Ao:[[0,65],[.2,65],[.28,85],[.34,95],[.45,84],[.53,76],[.55,72],[.57,74],[.7,70],[.85,66]]},r:{Ao:-.35,LV:-.12},
note:"Tamponad: RA basıncı yüksek, x inişi korunmuş ama y inişi yok; RA ≈ RVEDP ≈ PCWP (yaklaşık 14 mmHg, diyastolik eşitlenme); inspiryumda Ao/LV sistolik düşüşü 10 mmHg’yi aşar (pulsus paradoksus). Solunum kutusunu açık tutun."},
tr:{n:"Ağır triküspit yetersizliği",d:{
RA:[[0,10],[.1,12],[.17,12],[.22,16],[.3,14],[.4,18],[.5,22],[.58,24],[.68,12],[.85,10]],
RV:[[0,6],[.1,10],[.18,10],[.24,20],[.3,35],[.36,38],[.45,32],[.52,22],[.58,10],[.7,5],[.85,6]],
PA:[[0,14],[.2,14],[.28,28],[.34,36],[.42,28],[.52,20],[.56,17],[.58,18],[.7,15],[.85,14]]},
note:"Ağır TY: RA’da x inişi kaybolur, c ve v birleşerek dev bir sistolik dalga oluşturur (ventrikülizasyon); RA trasası RV basıncına benzer. Termodilüsyonla KO ölçümü güvenilmez olabilir."},
hocm:{n:"HOKMP (istirahat)",d:{
LV:[[0,10],[.1,14],[.2,16],[.25,55],[.3,100],[.36,115],[.42,150],[.46,160],[.5,130],[.56,40],[.62,8],[.72,8],[.9,10]],
Ao:[[0,75],[.2,75],[.27,100],[.31,125],[.36,118],[.42,110],[.46,120],[.52,108],[.55,92],[.57,96],[.7,85],[.85,78]],
PCWP:[[0,10],[.2,13],[.3,9],[.45,10],[.62,17],[.75,9],[.9,9]]},
note:"HOKMP: LV sistolik tepe geç ve yüksek, Ao’da ani yükselme-çentik-kubbe (spike-and-dome) görünümü; LV–Ao gradienti dinamik. Sol ventrikül çıkış yolu obstrüksiyonu: tepe gradient ≥30 mmHg. “LV + Aorta” modunda gradienti görün."},
hocmp:{n:"HOKMP (provokasyon)",d:{
LV:[[0,10],[.1,14],[.2,16],[.25,55],[.3,95],[.36,120],[.42,185],[.46,215],[.5,170],[.56,40],[.62,8],[.72,8],[.9,10]],
Ao:[[0,72],[.2,72],[.27,95],[.31,108],[.36,95],[.42,88],[.46,95],[.52,90],[.55,80],[.57,83],[.7,76],[.85,73]],
PCWP:[[0,12],[.2,16],[.3,11],[.45,12],[.62,22],[.75,11],[.9,11]]},
note:"Provokasyon (Valsalva, amil nitrit veya VES sonrası vuruş): gradient belirgin artar, Ao nabız basıncı daralır (Brockenbrough–Braunwald–Morrow işareti). Tepe gradient ≥50 mmHg septal redüksiyon düşünülen eşiktir."}};
Object.assign(SC,{
rkmp:{n:"Restriktif kardiyomiyopati",d:{
RA:[[0,12],[.1,16],[.17,13],[.22,13],[.3,9],[.45,12],[.58,16],[.68,9],[.85,11]],
RV:[[0,13],[.1,15],[.18,14],[.24,24],[.3,48],[.38,55],[.45,45],[.52,30],[.58,9],[.65,14],[.75,15],[.85,14]],
LV:[[0,23],[.1,26],[.2,25],[.25,55],[.3,105],[.36,115],[.45,98],[.52,55],[.58,12],[.64,22],[.72,24],[.9,23]],
PA:[[0,28],[.2,28],[.28,45],[.34,55],[.42,45],[.52,36],[.56,32],[.58,33],[.7,29],[.85,28]],
PCWP:[[0,22],[.05,22],[.2,26],[.3,21],[.45,21],[.62,26],[.75,21],[.9,21]]},
note:"RKMP: dip-plato var (konstriksiyona benzer) ancak LVEDP, RVEDP’den belirgin yüksektir (>5 mmHg), PA sistolik genellikle 50 mmHg üzeridir, RVEDP/RV sistolik oranı 1/3’ün altındadır ve solunumda ventriküler diskordans yoktur. Konstriksiyon ile karşılaştırın."},
ay:{n:"Ağır aort yetersizliği",d:{
Ao:[[0,48],[.2,42],[.27,100],[.31,160],[.36,170],[.45,150],[.53,110],[.55,102],[.57,104],[.7,75],[.85,58]],
LV:[[0,18],[.1,24],[.2,28],[.25,60],[.3,120],[.36,170],[.45,150],[.52,95],[.58,22],[.62,10],[.7,16],[.8,20],[.9,22]],
PCWP:[[0,16],[.05,16],[.2,19],[.3,15],[.45,15],[.62,18],[.75,15],[.9,15]]},
note:"Ağır AY: Ao nabız basıncı geniş (≈170/42), diyastolik Ao basıncı düşük, LVEDP yüksek; fark daralır. Ao’da belirgin çentik yoktur. “LV + Aorta” modunda diyastolik yaklaşmayı izleyin."},
asd:{n:"ASD (soldan sağa şant)",s:{RA:84,RV:85,PA:85},d:{
RA:[[0,6],[.1,10],[.17,7],[.22,7],[.3,4],[.45,6],[.58,9],[.68,3],[.85,5]],
RV:[[0,4],[.1,7],[.18,6],[.24,13],[.3,32],[.4,30],[.5,17],[.58,4],[.7,2],[.85,4]],
PA:[[0,12],[.2,12],[.28,28],[.34,35],[.42,27],[.52,19],[.56,16],[.58,17],[.7,13],[.85,12]]},
note:"ASD: oksimetri basamağı RA düzeyindedir (SVC %70 → RA %84); PA satürasyonu yüksektir, Qp/Qs ≈2. Sağ kalp hacim yüklenir. RV hacim yüklenmesi ve Qp/Qs >1,5 kapatma için önemli ölçütlerdir. RA ile LA trasalarını karşılaştırın."},
vsd:{n:"VSD (soldan sağa şant)",s:{RV:85,PA:85},d:{
RV:[[0,5],[.1,8],[.18,7],[.24,18],[.3,42],[.4,48],[.5,30],[.58,6],[.7,3],[.85,5]],
PA:[[0,18],[.2,18],[.28,38],[.34,48],[.42,38],[.52,26],[.56,22],[.58,24],[.7,19],[.85,18]],
PCWP:[[0,11],[.05,11],[.2,14],[.3,10],[.45,10],[.62,14],[.75,10],[.9,10]]},
note:"VSD: oksimetri basamağı RV düzeyindedir (RA %72 → RV %85); PA basıncı ve PCWP artar, Qp/Qs ≈2. Basınç yükü arttıkça Eisenmenger riski doğar."}});
const COL={LA:"#d0489b",RA:"#8a5cd6",RV:"#2b7bd6",PA:"#16a085",PCWP:"#e08a00",Ao:"#2b6fd6",LV:"#d6382b"};
const MODES={RA:["RA"],LA:["LA"],RV:["RV"],PA:["PA"],PW:["PCWP"],AO:["Ao"],LV:["LV"],O1:["LV","Ao"],O2:["PCWP","LV"],O3:["LA","LV"]};
const LBL={RA:"RA",LA:"Sol atriyum (transseptal)",
RV:"RV",PA:"Pulmoner arter",PW:"PCWP (wedge)",AO:"Aorta",LV:"LV",O1:"LV + Aorta",O2:"PCWP + LV",O3:"LA + LV"};
const INFO={
RA:{t:"Sağ atriyum (RA)",pos:"Venöz girişten SVC’ye, oradan RA’ya ilerletilir; ilk trasa burada alınır.",nm:"Ortalama 2–6 mmHg",
pts:["a dalgası: atriyal kontraksiyon, EKG’de P’yi izler; AF’de kaybolur.","c: triküspit kapanması (küçük); x inişi: atriyal gevşeme.","v dalgası: sistol sonunda venöz dolum, T’ye denk gelir; y inişi: triküspit açılması.","TY: dev c-v dalgası; TS: büyük a; tamponad: y inişi kaybı; konstriksiyon: belirgin x ve y (M/W şekli)."],
pit:"Sıfır seviyesi orta aksiller hatta olmalı; basıncı ekspiryum sonunda okuyun."},
RV:{t:"Sağ ventrikül (RV)",pos:"Balon şişikken triküspit kapağından geçilir; ventriküler ekstrasistol sık görülür.",nm:"Sistolik 15–30, EDP 2–8 mmHg",
pts:["Hızlı sistolik yükselme; sistolik tepe, çıkış darlığı yoksa PA sistoliğine eşittir.","Diyastolde düşük basınç: erken dolum, ardından a dalgası (RVEDP).","RV’den PA’ya geçişte diyastolik basınç aniden yükselir (step-up) ve dikrotik çentik belirir."],
pit:"Sol dal bloğunda kateter tam blok yapabilir. Konstriksiyon/RKMP’de dip-plato (kare kök) işareti aranır."},
PA:{t:"Pulmoner arter (PA)",pos:"Pulmoner kapak geçilir; balonlu kateter ana PA’dan dal artere ilerletilir. Mikst venöz satürasyon buradan alınır.",nm:"15–30 / 4–12 (ort 9–18) mmHg; PH: mPAP >20 mmHg",
pts:["Dikrotik çentik = pulmoner kapağın kapanması.","mPAP, PAWP ve KO ile PVR hesaplanır: (mPAP − PAWP) / KO.","Prekapiller PH: PAWP ≤15 ve PVR >2 WU; postkapiller PH: PAWP >15."],
pit:"KO için termodilüsyon (RA’dan salin) veya Fick kullanılır; ağır TY’de termodilüsyon güvenilmez olabilir."},
PW:{t:"Pulmoner kapiller wedge (PCWP)",pos:"Balon yaklaşık 1–1,5 mL ile şişirilerek distal PA dalına oturtulur; trasa atriyal tipe döner.",nm:"Ortalama 6–12 mmHg (≤15)",
pts:["LA basıncının sönümlü ve 70–100 ms gecikmiş yansıması: a dalgası QRS’ten sonra, v dalgası T’den sonra görülür.","Mitral hastalık yoksa PAWP ortalaması LVEDP’yi iyi yansıtır.","MY: dev v dalgası; MS: ortalama yüksek, y inişi yavaş."],
pit:"Overwedge (aşırı şişirme) basıncı yapay yükseltir; doğrulama için trasa şekli veya wedge satürasyonu (≥%95) kullanılır. Ekspiryum sonunda ölçün."},
AO:{t:"Aorta",pos:"Radyal/femoral arter girişi ile retrograd olarak çıkan aorta ilerletilir.",nm:"Sistolik 100–140, diyastolik 60–90 mmHg",
pts:["Hızlı sistolik yükselme; dikrotik çentik = aort kapağının kapanması.","Geniş nabız basıncı: AY; dar ve geç yükselim (parvus et tardus): AD.","Aort diyastolik basıncı LVEDP’den çok yüksektir; AY’de bu fark azalır."],
pit:"Çentiğin hemen altındaki diyastolik basınç, LV ile birlikte okunduğunda anlam kazanır."},
LA:{t:"Sol atriyum (LA)",pos:"Femoral venden transseptal girişle (foramen ovale veya septal ponksiyon) LA’ya ulaşılır; PFO varsa kateter doğrudan geçebilir.",nm:"Ortalama 4–12 mmHg (PCWP ile benzer)",
pts:["LA dalgaları PCWP ile aynıdır ama gecikmesiz ve sönümsüzdür: a dalgası P’den hemen sonra, v dalgası T dalgası sonunda görülür.","PCWP ile karşılaştırın: LA’daki v dalgası daha erken ve daha belirgindir; PCWP bu trasanın 70–100 ms gecikmiş, sönümlenmiş yansımasıdır.","Mitral stenozda LA–LV gradienti en doğru yöntemdir; PCWP gecikme düzeltmesi gerekmez."],
pit:"Transseptal ponksiyon tamponad, aort ponksiyonu ve emboli riski taşır; yalnızca PCWP güvenilmezse (mekanik mitral protez, belirsiz tanı) tercih edilir."},
LV:{t:"Sol ventrikül (LV)",pos:"Aort kapağı retrograd geçilir (AD’de kılavuz telle); ventriküler ekstrasistol ve emboli riski vardır.",nm:"Sistolik 100–140, LVEDP 5–12 mmHg",
pts:["İzovolümetrik kasılma → ejeksiyon (LV Ao’yu aşınca kapak açılır) → izovolümetrik gevşeme → hızlı dolum.","LVEDP, QRS başlangıcında (a dalgası sonrası) ölçülür; 16–18 mmHg üzeri artmış dolum basıncıdır."],
pit:"Ekstrasistol sonrası vuruşlar ölçüme alınmaz; LVEDP için eş zamanlı EKG kullanın."},
O1:{t:"Pull-back: LV → Aorta",pos:"LV ve Ao trasaları üst üste getirilir; gölgeli alan sistolik transvalvüler gradienttir.",nm:"Normalde gradient yok (5 mmHg’nin altı)",
pts:["Pik-to-pik gradient = LV sistolik tepe − Ao sistolik tepe.","Ortalama gradient = ejeksiyon boyunca LV−Ao farkının ortalaması.","Hakki: AVA ≈ KO (L/dk) / √ortalama gradient. Ağır AD: ortalama gradient ≥40 mmHg, AVA 1,0 cm² altı."],
pit:"Eş zamanlı kayıt idealdir; sıralı geri çekmede hız ve kontraktilite değişir, ekstrasistol sonrası vuruş hatalıdır."},
O3:{t:"LA + LV: doğrudan mitral gradient",pos:"Transseptal LA ve LV eş zamanlı kaydedilir; PCWP gecikmesi olmadığı için mitral gradient en doğru bu yöntemle ölçülür.",nm:"Normalde diyastolik gradient 0–2 mmHg",
pts:["Gölgeli alan: LA basıncının LV’nin üstünde kaldığı diyastolik transmitral gradient.","PCWP + LV moduyla karşılaştırın: PCWP’nin gecikmesi ve sönümü gradienti abartabilir; LA’da v dalgası daha erken ve belirgindir.","Hakki: MVA ≈ KO / √ortalama gradient; klinik olarak anlamlı MS: MVA ≤1,5 cm²."],
pit:"Transseptal giriş riskleri (tamponad, aort ponksiyonu, emboli) nedeniyle seçilmiş olgularda kullanılır; LA ve LV kayıtları eş zamanlı olmalıdır."},
O2:{t:"PCWP + LV: mitral gradient",pos:"Wedge ve LV eş zamanlı kaydedilir; diyastolde PCWP > LV ise mitral kapakta engel vardır.",nm:"Normalde diyastolik gradient 0–2 mmHg",
pts:["Gölgeli alan: diyastolik transmitral gradient.","Hakki: MVA ≈ KO (L/dk) / √ortalama gradient.","Klinik olarak anlamlı MS: MVA ≤1,5 cm²."],
pit:"Wedge gecikmesi (70–100 ms) gradienti abartır; trasayı zamanda kaydırarak düzeltin veya transseptal LA basıncı ölçün."}};
/* PCHIP tablosu */
function mk(p){const X=[],Y=[];for(let k=-1;k<=1;k++)for(const q of p){X.push(q[0]+k);Y.push(q[1])}
const n=X.length,d=[],m=[];for(let i=0;i<n-1;i++)d[i]=(Y[i+1]-Y[i])/(X[i+1]-X[i]);
m[0]=d[0];m[n-1]=d[n-2];for(let i=1;i<n-1;i++)m[i]=d[i-1]*d[i]<=0?0:2*d[i-1]*d[i]/(d[i-1]+d[i]);
const T=new Float32Array(720);let j=0;
for(let s=0;s<720;s++){const x=s/720;while(X[j+1]<=x)j++;const h=X[j+1]-X[j],t=(x-X[j])/h,t2=t*t,t3=t2*t;
T[s]=(2*t3-3*t2+1)*Y[j]+(t3-2*t2+t)*h*m[j]+(-2*t3+3*t2)*Y[j+1]+(t3-t2)*h*m[j+1]}
return T}
let TB={},mode="RA",scn="normal",hr=70,ymax=40,beat=0,last=0,W=600,RESP=true,MKS=true,tm=0,BASE={},MKR={},WIN=6;
const val=(k,p)=>{const u=p*720,i=Math.floor(u),f=u-i,T=TB[k];return T[i%720]*(1-f)+T[(i+1)%720]*f};
const S=k=>Array.from({length:360},(_,i)=>val(k,i/360));
const am=(a,l,h,f)=>{let b=l;for(let i=l;i<=h;i++)if(f?a[i]<a[b]:a[i]>a[b])b=i;return b/360};
function MK(k){const a=S(k);
if(k=="RA")return[[am(a,18,90),"a",0],[am(a,90,150,1),"x",1],[am(a,162,270),"v",0],[am(a,225,300,1),"y",1]];
if(k=="PCWP"||k=="LA")return[[am(a,18,90),"a",0],[am(a,162,270),"v",0]];
if(k=="RV"||k=="LV")return[[.19,"EDP",1],[am(a,72,216),"sist",0]];
return[[am(a,72,216),"sist",0],[am(a,180,216,1),"",0],[am(a,0,359,1),"dia",1]]}
const CO={as:4.5,ms:3.8,mr:4.2,ph:3.5,kons:3.6,tam:3,tr:4,rkmp:3.5,ay:6,asd:5,vsd:5};
const ROWS={normal:'co,rap,spap,mpap,pawp,lvedp,pvr,svr',as:'co,gp2p,gmean,ava,lvedp,ao,pawp',ms:'co,pawp,mpap,mg,mva,pvr,spap',mr:'co,pawp,vw,spap,mpap,lvedp,pvr',ph:'co,rap,rvs,spap,mpap,pawp,tpg,pvr',kons:'rap,rvs,lvedp,pawp,eq,rvr,dedp,spap',tam:'co,rap,rvs,lvedp,pawp,eq,ao',tr:'co,rap,rvs,spap,mpap,pvr',hocm:'lvot,lvedp,ao,pawp,co',hocmp:'lvot,lvedp,ao,pawp,co',rkmp:'rap,rvs,lvedp,pawp,spap,eq,dedp,rvr',ay:'ao,pp,lvedp,pawp,co',asd:'qpqs,co,rap,spap,mpap,pawp,pvr',vsd:'qpqs,co,rvs,spap,mpap,pawp,pvr'};
Object.assign(CO,{hfpef:4.5});ROWS.hfpef='co,rap,spap,mpap,pawp,lvedp,ao,pvr';
Object.assign(SC,{hfpef:{n:'HFpEF (korunmuş EF)',d:{
LV:[[0,18],[.1,21],[.2,24],[.25,65],[.3,130],[.36,150],[.45,135],[.52,80],[.58,25],[.65,12],[.72,16],[.8,19],[.9,21]],
Ao:[[0,75],[.2,75],[.28,120],[.34,150],[.45,132],[.53,112],[.55,106],[.57,109],[.7,92],[.85,80]],
PCWP:[[0,19],[.05,19],[.2,25],[.3,19],[.45,19],[.62,26],[.75,19],[.9,18]],
PA:[[0,18],[.2,18],[.28,36],[.34,45],[.42,36],[.52,28],[.56,25],[.58,26],[.7,20],[.85,19]],
RV:[[0,6],[.1,10],[.18,9],[.24,18],[.3,38],[.4,45],[.5,28],[.58,7],[.7,5],[.85,6]],
RA:[[0,9],[.1,13],[.17,10],[.22,10],[.3,6],[.45,9],[.58,12],[.68,6],[.85,8]]},
note:'HFpEF: sistolik işlev korunmuş (EF ≥%50), ancak LV sert ve geç gevşiyor: LVEDP ≥16 mmHg ve PAWP >15 mmHg, PCWP’de belirgin a ve v dalgaları, izole postkapiller PH ve hipertansif Ao. İstirahatte PAWP normal olabilir; egzersizde PAWP ≥25 mmHg tanıyı destekler.'}});
function sum(){const f=(v,d)=>v.toFixed(d).replace('.',','),sc=SC[scn],co=CO[scn]||5,s=Object.assign({SVC:70,IVC:76,PA:71},sc.s||{}),qq=sc.s?(98-(3*s.SVC+s.IVC)/4)/(98-s.PA):1;
const PA=S('PA'),AO=S('Ao'),PW=S('PCWP'),LV=S('LV'),RV=S('RV'),rap=avg(S('RA')),mp=avg(PA),pw=avg(PW),le=LV[68],re=RV[68],rs=mx(RV),map=avg(AO),pvr=(mp-pw)/(co*qq),
gm=avg(LV.map((v,i)=>v-AO[i]).filter((v,i)=>i>=72&&i<=216&&v>0)),gp=mx(LV)-mx(AO),
mg=avg(PW.map((v,i)=>v-LV[i]).filter((v,i)=>(i<72||i>216)&&v>0)),eqv=[rap,re,le,pw],rg=mx(eqv)-mn(eqv),vv=mx(PW.slice(162,270)),pp=mx(AO)-mn(AO),ava=co/Math.sqrt(gm),mva=co/Math.sqrt(Math.max(mg,1));
const T={co:['KO (varsayım)',f(co,1)+' L/dk',co<4],qpqs:['Qp/Qs',f(qq,1),qq>=1.5],rap:['RA ortalama',f(rap,0)+' mmHg',rap>8],rvs:['RV sist/EDP',R(rs)+'/'+R(re)+' mmHg',re>8],spap:['sPAP',R(mx(PA))+' mmHg',mx(PA)>35],mpap:['mPAP',f(mp,0)+' mmHg',mp>20],pawp:['PAWP ortalama',f(pw,0)+' mmHg',pw>15],vw:['PCWP v dalgası',R(vv)+' mmHg',vv-pw>10],lvedp:['LVEDP',R(le)+' mmHg',le>16],ao:['Ao sist/dia (ort.)',R(mx(AO))+'/'+R(mn(AO))+' ('+R(map)+')',false],pp:['Nabız basıncı',R(pp)+' mmHg',pp>60],tpg:['TPG',R(mp-pw)+' mmHg',mp-pw>12],pvr:['PVR',f(pvr,1)+' WU',pvr>2],svr:['SVR',f((map-rap)/co,1)+' WU',false],gp2p:['Pik-to-pik gradient',R(gp)+' mmHg',gp>20],gmean:['Ort. gradient (LV–Ao)',R(gm)+' mmHg',gm>20],ava:['AVA (Hakki)',f(ava,1)+' cm²',ava<1],mg:['Ort. diyastolik gradient (PCWP–LV)',f(mg,0)+' mmHg',mg>5],mva:['MVA (Hakki)',f(mva,1)+' cm²',mva<=1.5],lvot:['LVOT tepe gradient',R(gp)+' mmHg',gp>=30],eq:['Diyastol sonu fark (RA, RVEDP, LVEDP, PAWP)',R(rg)+' mmHg',rg<=5],rvr:['RVEDP / RV sist',f(re/rs,2),re/rs>1/3],dedp:['LVEDP − RVEDP',R(le-re)+' mmHg',le-re>5]};
const rw=ROWS[scn].split(',');let n='';
if(rw.includes('mpap'))n=mp<=20?'mPAP ≤20 mmHg: pulmoner hipertansiyon yok.':pw<=15?(pvr>2?'Prekapiller pulmoner hipertansiyon (PAWP ≤15, PVR >2 WU).':'mPAP >20 ama PVR ≤2 WU: hiperkinetik akım (şant) ile uyumlu.'):(pvr>2?'Kombine pre- ve postkapiller PH (PAWP >15, PVR >2 WU).':'İzole postkapiller PH (PAWP >15, PVR ≤2 WU).');
if(rw.includes('eq')&&rg<=5)n+=' Diyastol sonu basınçlar eşitlenmiş (fark ≤5 mmHg).';
return `<h3 style='margin:0 0 8px;font-size:16px'>Hemodinamik özet: ${sc.n}</h3><div class='sg'>${rw.map(k=>`<div class='${T[k][2]?'al':''}'><small>${T[k][0]}</small><b>${T[k][1]}</b></div>`).join('')}</div><p class='foot'>${n}</p><p class='foot'>Kırmızı: referans aralığı dışı. Değerler ekspiryum sonu taban trasasından hesaplanır; KO senaryo için varsayımdır (gerçekte termodilüsyon veya Fick). Şantta PVR, Qp ile hesaplanır.</p>`}
function sat(){const s=Object.assign({SVC:70,IVC:76,RA:72,RV:71,PA:71,PCWP:98,LA:98,LV:98,Ao:98},SC[scn].s||{});
let h="<div>SpO₂ (oksimetri): "+MODES[mode].map(k=>k+" <b>%"+s[k]+"</b>").join(" · ")+"</div>";
if(SC[scn].s){const mv=(3*s.SVC+s.IVC)/4;h+="<div>Qp/Qs ≈ <b>"+((98-mv)/(98-s.PA)).toFixed(1)+"</b> (RA %"+s.RA+" · RV %"+s.RV+" · PA %"+s.PA+"; SVC %"+s.SVC+")</div>"}return h}
function vr(k,p,t){if(k=='X'){const q=LIVE;return q.w<=.001?vr(q.a,p,t):q.w>=.999?vr(q.b,p,t):(1-q.w)*vr(q.a,p,t)+q.w*vr(q.b,p,t)}let v=val(k,p);if(!RESP)return v;const i=Math.sin(6.2832*t/4),d=(SC[scn].r||{})[k],b=BASE[k];if(d)v=b+(v-b)*(1+d*i);return v-(k=="Ao"?2:3)*i}
const avg=a=>a.reduce((s,v)=>s+v,0)/(a.length||1),mx=a=>Math.max(...a),mn=a=>Math.min(...a),R=v=>Math.round(v);
const ecg=p=>{const g=(m,s,a)=>a*Math.exp(-Math.pow((p-m)/s,2));return g(.1,.04,.15)+g(.18,.013,-.12)+g(.2,.017,1.1)+g(.222,.015,-.25)+g(.43,.06,.3)};
function stat(k){const a=S(k);
if(k=="RA"||k=="PCWP"||k=="LA")return `<span style="color:${COL[k]}">●</span> ${k}: ortalama <b>${R(avg(a))}</b> · a <b>${R(mx(a.slice(18,90)))}</b> · v <b>${R(mx(a.slice(162,270)))}</b> mmHg`;
if(k=="RV"||k=="LV")return `<span style="color:${COL[k]}">●</span> ${k}: <b>${R(mx(a))}/${R(a[68])}</b> mmHg (sistolik / EDP)`;
return `<span style="color:${COL[k]}">●</span> ${k}: <b>${R(mx(a))}/${R(mn(a))}</b> mmHg (ortalama ${R(avg(a))})`}
function grad(){if(mode=="O1"){const L=S("LV"),A=S("Ao"),d=L.map((v,i)=>v-A[i]).filter((v,i)=>i>=72&&i<=216&&v>0);
return `Pik-to-pik gradient: <b>${R(mx(L)-mx(A))}</b> mmHg · ortalama gradient: <b>${R(avg(d))}</b> mmHg (yaklaşık)`}
if((mode=="O2"||mode=="O3")){const P=S(MODES[mode][0]),L=S("LV"),d=P.map((v,i)=>v-L[i]).filter((v,i)=>(i<72||i>216)&&v>0);
return `Ortalama diyastolik gradient: <b>${R(avg(d))}</b> mmHg (yaklaşık)`}return ""}
function render(){
TB={};for(const k in NORM)TB[k]=mk(SC[scn].d[k]||NORM[k]);
{const P=TB.PCWP,L=new Float32Array(720),mP=avg(Array.from(P));for(let s=0;s<720;s++)L[s]=mP+(P[(s+65)%720]-mP)*1.25;TB.LA=L}
for(const k in TB){BASE[k]=mn(S(k));MKR[k]=MK(k);MAXT[k]=mx(S(k))}
const ks=MODES[mode];let m=0;ks.forEach(k=>m=Math.max(m,mx(S(k))));if(!LIVEON)ymax=Math.ceil(m*1.15/10)*10;
document.querySelectorAll("#btns button").forEach(b=>b.classList.toggle("on",b.dataset.m==mode));
document.querySelectorAll(".dt").forEach(d=>d.classList.toggle("on",ks.some(k=>d.id=="d-"+k)));
const pm={RA:'R',RV:'R',PA:'R',PW:'R',AO:'L',LV:'L',LA:'T',O1:'L',O2:'RL',O3:'TL'}[mode];['R','L','T'].forEach(c=>{const e=$('#p'+c);if(e)e.classList.toggle('on',pm.includes(c))});
const A=S('Ao');$('#bp').textContent=R(mx(A))+'/'+R(mn(A))+' ('+R(avg(A))+')';
$("#live").innerHTML=ks.map(stat).join("")+(grad()?"<div>"+grad()+"</div>":"")+sat()+'<div style="color:var(--mu)">Tablodaki değerler ekspiryum sonu (solunum etkisiz) taban değerleridir; grafikteki noktalar solunumla değişir.</div>';
$("#sum").innerHTML=sum();const I=INFO[mode];
$("#info").innerHTML=`<h2>${I.t}</h2><div class="nm">Normal: <b>${I.nm}</b></div><p><span class="tag">Kateter</span>${I.pos}</p><ul>${I.pts.map(x=>"<li>"+x+"</li>").join("")}</ul><div class="pit"><b>Dikkat:</b> ${I.pit}</div><p><span class="tag">Senaryo</span>${SC[scn].note}</p>`}
/* Arayüz */
$("#sc").innerHTML=Object.keys(SC).map(k=>`<option value="${k}">${SC[k].n}</option>`).join("");
$("#btns").innerHTML=[["Sağ kalp (venöz)",["RA","RV","PA","PW"]],["Sol kalp (arteriyel retrograd veya transseptal)",["AO","LV","LA"]],["Gradient / pull-back",["O1","O2","O3"]]]
.map(g=>`<div class="grp"><small>${g[0]}</small>${g[1].map(k=>`<button data-m="${k}">${LBL[k]}</button>`).join("")}</div>`).join("");
$("#btns").onclick=e=>{if(e.target.dataset.m){mode=e.target.dataset.m;render()}};
$("#sc").onchange=e=>{scn=e.target.value;render()};
$("#hr").oninput=e=>{hr=+e.target.value;$("#hrv").textContent=hr};
$("#rs").onchange=e=>{RESP=e.target.checked};$("#mkc").onchange=e=>{MKS=e.target.checked};
/* Çizim */
const cv=$("#cv"),cx=cv.getContext("2d");
function fit(){const r=devicePixelRatio||1;W=cv.clientWidth;cv.width=W*r;cv.height=300*r;cx.setTransform(r,0,0,r,0,0)}
addEventListener("resize",fit);fit();
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
function loop(ts){const dt=last?(ts-last)/1000:0;last=ts;beat+=dt*hr/60;
tm+=dt;if(LIVEON)liveStep(dt);if(HB){const f=beat%1,s=f>.2&&f<.55?Math.sin(Math.PI*(f-.2)/.35):0;HB.style.transform='scale('+(1-.035*s)+')'}const T=60/hr,ph=x=>(((beat-(1-x/W)*WIN/T)%1)+1)%1,tt=x=>tm-(1-x/W)*WIN,yv=v=>276-(v/ymax)*176;
cx.clearRect(0,0,W,300);cx.font="11px system-ui";cx.lineWidth=1;cx.strokeStyle=css("--grid");cx.fillStyle=css("--mu");
const st=ymax<=40?10:ymax<=100?20:50;
for(let v=0;v<=ymax;v+=st){const y=yv(v);cx.beginPath();cx.moveTo(30,y);cx.lineTo(W,y);cx.stroke();cx.fillText(v,2,y+4)}
cx.fillText("EKG",2,12);cx.fillText("mmHg",2,96);
if(RESP){cx.fillText("Solunum",2,74);cx.strokeStyle="#8896a8";cx.lineWidth=1.2;cx.beginPath();for(let x=50;x<=W;x+=3){const y=76-Math.sin(6.2832*tt(x)/4)*9;x==50?cx.moveTo(x,y):cx.lineTo(x,y)}cx.stroke()}
cx.strokeStyle="#2fa84f";cx.lineWidth=1.6;cx.beginPath();
for(let x=30;x<=W;x+=1){const y=48-ecg(ph(x))*26;x==30?cx.moveTo(x,y):cx.lineTo(x,y)}cx.stroke();
const ks=LIVEON?['X']:MODES[mode];
if(ks.length==2){cx.fillStyle=mode=="O1"?"rgba(214,56,43,.22)":"rgba(224,138,0,.28)";
const first=ks[0],second=ks[1];
for(let x=30;x<=W;x+=2){const p=ph(x),a=vr(first,p,tt(x)),b=vr(second,p,tt(x));if(a>b){const ya=yv(a),yb=yv(b);cx.fillRect(x,ya,2,yb-ya)}}}
ks.forEach(k=>{cx.strokeStyle=COL[k];cx.lineWidth=2.2;cx.beginPath();
for(let x=30;x<=W;x+=2){const y=yv(vr(k,ph(x),tt(x)));x==30?cx.moveTo(x,y):cx.lineTo(x,y)}cx.stroke()});
if(MKS){cx.font="10px system-ui";const nl=W>480;
ks.forEach(k=>MKR[k].forEach(([f,l,dn])=>{
if(mode=="O1"&&l!="sist")return;if((mode=="O2"||mode=="O3")&&l!=(k=="LV"?"EDP":"v"))return;
for(let n=Math.floor(beat-WIN/T)-1;n<=Math.floor(beat)+1;n++){
const x=W*(1-(beat-(n+f))*T/WIN);if(x<34||x>W-4)continue;
const v=vr(k,f,tm-(1-x/W)*WIN),y=yv(v);
cx.fillStyle=COL[k];cx.strokeStyle=css("--card");cx.lineWidth=1.5;cx.beginPath();cx.arc(x,y,3.5,0,6.283);cx.fill();cx.stroke();
if(nl&&l){cx.fillStyle=css("--tx");cx.textAlign="center";cx.fillText(l+" "+R(v),x,dn?y+14:y-8)}}}));cx.textAlign="left"}
requestAnimationFrame(loop)}
$('#old').remove();
$('#hv').innerHTML=`<svg viewBox='0 0 300 340' aria-label='Kalp'><defs><radialGradient id='gB' cx='50%' cy='40%' r='75%'><stop offset='0' stop-color='#9cc4ff' stop-opacity='.12'/><stop offset='1' stop-color='#2b6fd6' stop-opacity='.55'/></radialGradient><radialGradient id='gR' cx='50%' cy='40%' r='75%'><stop offset='0' stop-color='#ffb3a8' stop-opacity='.12'/><stop offset='1' stop-color='#d6382b' stop-opacity='.55'/></radialGradient></defs><g id='hb' style='transform-origin:155px 240px'>
<ellipse cx='155' cy='238' rx='120' ry='108' fill='rgba(214,120,120,.07)'/>
<g fill='none'><path d='M96,6V150M112,252V334' stroke='rgba(60,120,220,.3)' stroke-width='26'/><path d='M172,160V70C172,30 238,30 238,80V334' stroke='rgba(224,70,60,.3)' stroke-width='28'/><path d='M140,175V96C120,72 85,76 52,90' stroke='rgba(60,120,220,.3)' stroke-width='24'/><path d='M140,100C165,78 195,84 214,106' stroke='rgba(60,120,220,.3)' stroke-width='16'/><path d='M268,138L236,152M270,172L238,168' stroke='rgba(224,70,60,.3)' stroke-width='9'/></g>
<g stroke-width='1.5'><path d='M62,150C56,112 96,106 124,124C146,138 152,168 148,196C145,218 122,224 98,220C72,214 66,184 62,150Z' fill='url(#gB)' stroke='rgba(70,130,230,.8)'/><path d='M104,218C108,270 140,305 176,322C172,282 166,240 162,202C140,206 120,209 104,218Z' fill='url(#gB)' stroke='rgba(70,130,230,.8)'/><path d='M184,142C198,118 250,116 264,148C272,176 250,192 214,190C190,187 176,162 184,142Z' fill='url(#gR)' stroke='rgba(230,80,70,.8)'/><path d='M166,198C200,180 254,190 254,236C254,286 216,318 176,322C178,290 172,236 166,198Z' fill='url(#gR)' stroke='rgba(230,80,70,.8)'/></g>
<path d='M152,205C162,240 170,285 177,322' fill='none' stroke='rgba(255,255,255,.3)' stroke-width='3'/>
<g fill='none' stroke-width='1.6' style='stroke:var(--tx);stroke-opacity:.45'><ellipse cx='128' cy='214' rx='20' ry='5'/><ellipse cx='140' cy='172' rx='12' ry='4'/><ellipse cx='205' cy='194' rx='22' ry='5'/><ellipse cx='172' cy='176' rx='12' ry='4'/></g>
<g fill='rgba(255,255,255,.18)'><ellipse cx='146' cy='272' rx='4' ry='9'/><ellipse cx='208' cy='282' rx='5' ry='10'/><ellipse cx='228' cy='262' rx='4' ry='9'/></g>
<g fill='none' stroke='rgba(230,80,70,.6)' stroke-width='1.6'><path d='M172,184C182,225 184,275 178,314'/><path d='M104,166C98,196 110,214 126,222'/></g>
<path class='cp' style='opacity:.2' d='M56,92C90,150 150,138 236,152'/>
<path id='pR' class='cp' d='M97,8V150L95,165C102,195 118,214 128,224L138,262C146,235 145,200 140,170V100C120,76 85,80 56,92'/>
<path id='pL' class='cp' d='M238,334V80C238,40 172,40 172,72V176C180,205 200,230 214,250'/>
<path id='pT' class='cp' d='M95,165C125,172 180,166 236,152'/>
<circle class='dt' id='d-RA' cx='95' cy='165' r='8'/><circle class='dt' id='d-RV' cx='138' cy='262' r='8'/><circle class='dt' id='d-PA' cx='140' cy='110' r='8'/><circle class='dt' id='d-PCWP' cx='56' cy='92' r='8'/><circle class='dt' id='d-Ao' cx='172' cy='110' r='8'/><circle class='dt' id='d-LA' cx='236' cy='152' r='8'/><circle class='dt' id='d-LV' cx='214' cy='250' r='8'/>
<text x='62' y='200'>RA</text><text x='116' y='290'>RV</text><text x='150' y='112'>PA</text><text x='30' y='76'>wedge</text><text x='181' y='112'>Ao</text><text x='206' y='176'>LA</text><text x='196' y='292'>LV</text><text x='112' y='22'>SVC</text><text x='128' y='326'>IVC</text>
</g></svg>`;
const HB=$('#hb');
const MAXT={},LIVE={a:'RA',b:'RA',w:0},TM={RA:'RA',RV:'RV',PA:'PA',PCWP:'PW',Ao:'AO',LV:'LV',LA:'LA'};
let LIVEON=false,route='R',u=0,auto=false,dir=1,lastDom='';
const sv=$('#hv svg'),tip=document.createElementNS('http://www.w3.org/2000/svg','circle');
tip.setAttribute('r','6');tip.style.cssText='fill:var(--ac);stroke:#fff;stroke-width:2;display:none';HB.appendChild(tip);
const RT={R:{p:$('#pR'),seg:['RA','RV','PA','PCWP'],bt:[[128,224],[140,176],[80,86]],nm:['SVC / sağ atriyum','Sağ ventrikül','Pulmoner arter','Wedge (PCWP)'],tr:['Triküspit kapağı geçiliyor','Pulmoner kapak geçiliyor','Balon şişirilip wedge’e oturtuluyor']},
L:{p:$('#pL'),seg:['Ao','LV'],bt:[[172,180]],nm:['Aorta (retrograd)','Sol ventrikül'],tr:['Aort kapağı geçiliyor']},
T:{p:$('#pT'),seg:['RA','LA'],bt:[[152,168]],nm:['Sağ atriyum','Sol atriyum'],tr:['İnteratriyal septum (transseptal ponksiyon)']}};
for(const q of Object.values(RT)){const n=300,len=q.p.getTotalLength();q.len=len;q.pts=[];for(let i=0;i<=n;i++){const t=q.p.getPointAtLength(i/n*len);q.pts.push([t.x,t.y])}
q.b=q.bt.map(([x,y])=>{let bi=0,bd=1e9;q.pts.forEach((t,i)=>{const d=(t[0]-x)**2+(t[1]-y)**2;if(d<bd){bd=d;bi=i}});return bi/n*len})}
function setU(v){const L=RT[route].len;u=Math.max(0,Math.min(L,v));$('#us').value=u/L*1000}
function setAuto(v){auto=v;$('#auto').textContent=v?'⏸ Durdur':'▶ Otomatik ilerlet'}
function liveStep(dt){const r=RT[route],L=r.len;
if(auto){u+=dir*dt*L/14;if(u>=L){u=L;dir=-1}if(u<=0){u=0;dir=1}$('#us').value=u/L*1000}
const d=10;let i=0;while(i<r.b.length&&u>r.b[i])i++;let a=r.seg[i],b=a,w=0,tr='';
for(let j=0;j<r.b.length;j++)if(Math.abs(u-r.b[j])<d){a=r.seg[j];b=r.seg[j+1];w=(u-r.b[j]+d)/(2*d);w=w*w*(3-2*w);tr=r.tr[j];break}
LIVE.a=a;LIVE.b=b;LIVE.w=w;const dom=w<.5?a:b;
if(dom!==lastDom){lastDom=dom;mode=TM[dom];render()}
MKR.X=MKR[dom];COL.X=COL[dom];
const tg=Math.ceil(((1-w)*MAXT[a]+w*MAXT[b])*1.15/10)*10;ymax+=(tg-ymax)*Math.min(1,dt*6);
const pt=r.p.getPointAtLength(u);tip.setAttribute('cx',pt.x);tip.setAttribute('cy',pt.y);
for(const c in RT){const q=RT[c],on=c==route;q.p.classList.toggle('on',on);q.p.style.strokeDasharray=on?u+' 99999':''}
$('#where').innerHTML='<b>'+(tr?tr+'…':r.nm[i])+'</b>'}
let drag=false;
function pick(e){const p=new DOMPoint(e.clientX,e.clientY).matrixTransform(sv.getScreenCTM().inverse());let bi=0,bd=1e9;RT[route].pts.forEach((t,i)=>{const d=(t[0]-p.x)**2+(t[1]-p.y)**2;if(d<bd){bd=d;bi=i}});setU(bi/300*RT[route].len)}
sv.addEventListener('pointerdown',e=>{if(LIVEON){drag=true;setAuto(false);sv.setPointerCapture(e.pointerId);pick(e)}});
sv.addEventListener('pointermove',e=>{if(drag)pick(e)});
sv.addEventListener('pointerup',()=>{drag=false});
$('#us').oninput=e=>{setAuto(false);setU(+e.target.value/1000*RT[route].len)};
$('#auto').onclick=()=>setAuto(!auto);
document.querySelectorAll('[data-r]').forEach(b=>b.onclick=()=>{route=b.dataset.r;document.querySelectorAll('[data-r]').forEach(x=>x.classList.toggle('on',x==b));setAuto(false);dir=1;setU(0);lastDom=''});
document.querySelectorAll('.tabs button').forEach(b=>b.onclick=()=>{LIVEON=b.dataset.t=='c';document.querySelectorAll('.tabs button').forEach(x=>x.classList.toggle('on',x==b));$('#btns').hidden=LIVEON;$('#livectl').hidden=!LIVEON;tip.style.display=LIVEON?'':'none';sv.style.touchAction=LIVEON?'none':'';
if(LIVEON){lastDom='';setU(0)}else{setAuto(false);for(const c in RT)RT[c].p.style.strokeDasharray='';render()}});
render();requestAnimationFrame(loop);
</script></body></html>
"""


# ===================== KATETERİZASYON HEMODİNAMİ HESAPLAYICI (HTML) =====================
_CATH_CALC_HTML = r"""<!DOCTYPE html>
<html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Kateterizasyon Hemodinami Hesaplayıcı</title>
<style>
:root{--bg:#f4f6f9;--card:#fff;--tx:#1b2430;--mu:#5d6b7c;--bd:#dde2e8;--sh:#eef1f5;--ac:#c0392b;--ok:#1f9d6b;--wa:#d99a00;--ba:#d6363e;--in:#2f6fd1;--chip:rgba(255,255,255,.86)}
@media (prefers-color-scheme:dark){:root{--bg:#0f141a;--card:#18202a;--tx:#e6ebf1;--mu:#9aa7b6;--bd:#2a3542;--sh:#212b37;--chip:rgba(24,32,42,.86);color-scheme:dark}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1040px;margin:0 auto;padding:14px}
h1{font-size:21px;margin:2px 0}.sub{color:var(--mu);margin:0 0 12px;font-size:14px}
h2{font-size:16px;margin:0 0 8px}
.card{background:var(--card);border:1px solid var(--bd);border-radius:14px;padding:12px 14px;margin-bottom:12px}
.bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
button,select,input{font:inherit;color:var(--tx)}
button{padding:6px 12px;border-radius:18px;border:1px solid var(--bd);background:var(--card);cursor:pointer}
button.pri{background:var(--ac);border-color:var(--ac);color:#fff}
select{padding:5px 8px;border-radius:8px;border:1px solid var(--bd);background:var(--card)}
.pt{display:grid;grid-template-columns:repeat(auto-fill,minmax(118px,1fr));gap:8px 10px;margin-top:10px}
.pt label{display:flex;flex-direction:column;font-size:12px;color:var(--mu)}
.pt input,.pt select{margin-top:2px;padding:5px 8px;border-radius:8px;border:1px solid var(--bd);background:var(--card);width:100%}
.pt .calc{font-size:12px;color:var(--mu);align-self:end;padding-bottom:6px}
.pt .calc b{color:var(--tx)}
/* sahne */
#stageWrap{position:relative;width:100%;overflow:hidden}
#stage{position:absolute;left:0;top:0;width:980px;height:790px;transform-origin:0 0}
#heart{position:absolute;inset:0;width:980px;height:790px}
.chip{position:absolute;background:var(--chip);backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);border:1px solid var(--bd);border-left:5px solid var(--bd);border-radius:12px;padding:6px 8px 7px;box-shadow:0 4px 14px rgba(0,0,0,.12);transition:border-color .3s,box-shadow .3s}
.chip.ok{border-left-color:var(--ok)}.chip.warn{border-left-color:var(--wa)}.chip.bad{border-left-color:var(--ba);box-shadow:0 0 0 2px rgba(214,54,62,.25),0 4px 14px rgba(0,0,0,.12)}
.chip:focus-within{box-shadow:0 0 0 3px rgba(47,111,209,.35),0 6px 18px rgba(0,0,0,.18)}
.ct{font-weight:700;font-size:13px;display:flex;align-items:baseline;gap:6px;margin-bottom:3px;white-space:nowrap}
.ct small{font-weight:400;color:var(--mu);font-size:11px;overflow:hidden;text-overflow:ellipsis}
.fs{display:flex;flex-wrap:wrap;gap:5px}
.f{display:flex;flex-direction:column;font-size:10.5px;color:var(--mu);line-height:1.2}
.f input{width:46px;padding:3px 4px;margin-top:1px;border:1px solid var(--bd);border-radius:6px;background:var(--card);text-align:center;font-size:13px;font-variant-numeric:tabular-nums}
.f input.sat{border-color:#c9a3a8}
.f input::placeholder{color:var(--mu);opacity:.75}
.out{font-size:11.5px;margin-top:3px;color:var(--tx);font-variant-numeric:tabular-nums}
.out b{font-size:13px}
#chipGrid{display:none;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:8px;margin-top:8px}
.compact #chipGrid{display:grid}
.compact #chipGrid .chip{position:static;width:auto!important}
.legend{display:flex;flex-wrap:wrap;gap:12px;font-size:12px;color:var(--mu);margin-top:6px;align-items:center}
.legend i{display:inline-block;width:12px;height:12px;border-radius:3px;vertical-align:-2px;margin-right:4px}
.satbar{width:120px;height:10px;border-radius:5px;background:linear-gradient(90deg,#3c4fa8,#7b5aa6 55%,#d8323b);display:inline-block;vertical-align:-1px}
/* sonuçlar */
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}
.tile{background:var(--sh);border-radius:10px;padding:7px 10px;border-top:3px solid transparent}
.tile small{display:block;color:var(--mu);font-size:11.5px}
.tile b{font-size:20px;font-variant-numeric:tabular-nums}.tile span{font-size:12px;color:var(--mu)}
.tile em{display:block;font-style:normal;font-size:10.5px;color:var(--mu)}
.tile.ok{border-top-color:var(--ok)}.tile.warn{border-top-color:var(--wa)}.tile.bad{border-top-color:var(--ba)}.tile.bad b{color:var(--ba)}
.tile.na{opacity:.55}
.g2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:760px){.g2{grid-template-columns:1fr}}
.viz svg{width:100%;height:auto;display:block}
.viz text{font-family:inherit}
.headline{border-radius:14px;padding:14px 16px;margin-bottom:12px;color:#fff;background:linear-gradient(120deg,#33475b,#4b6584)}
.headline.bad{background:linear-gradient(120deg,#9b1c24,#d6363e)}.headline.warn{background:linear-gradient(120deg,#9a6a00,#d99a00)}.headline.ok{background:linear-gradient(120deg,#0f6b48,#1f9d6b)}
.headline small{opacity:.85;font-size:12px;display:block}.headline b{font-size:22px;line-height:1.2;display:block;margin:2px 0}
.headline .chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}.headline .chips span{background:rgba(255,255,255,.18);border-radius:12px;padding:2px 9px;font-size:12.5px}
.fd{list-style:none;padding:0;margin:0}
.fd li{display:flex;gap:10px;padding:8px 4px;border-bottom:1px solid var(--bd)}
.fd li:last-child{border-bottom:0}
.fd .ic{flex:0 0 22px;height:22px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#fff;font-size:13px;font-weight:700}
.fd .ok .ic{background:var(--ok)}.fd .warn .ic{background:var(--wa)}.fd .bad .ic{background:var(--ba)}.fd .info .ic{background:var(--in)}
.fd b{display:block;font-size:14px}.fd span{font-size:13px;color:var(--mu)}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{border-bottom:1px solid var(--bd);padding:5px 6px;text-align:left}
th{color:var(--mu);font-weight:600}
.rk{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;color:#fff}
.rk.l{background:var(--ok)}.rk.i{background:var(--wa)}.rk.h{background:var(--ba)}
details{margin-top:4px}summary{cursor:pointer;font-weight:600}
textarea{width:100%;min-height:180px;font:12.5px/1.45 ui-monospace,Menlo,Consolas,monospace;border:1px solid var(--bd);border-radius:8px;background:var(--sh);color:var(--tx);padding:8px}
.foot{color:var(--mu);font-size:12px}
.note{font-size:12px;color:var(--mu)}
/* svg sınıfları */
.chm{stroke-width:3;transition:fill .5s,stroke .4s}
.chm.ok{stroke:var(--ok)}.chm.warn{stroke:var(--wa)}.chm.bad{stroke:var(--ba)}.chm.na{stroke:rgba(120,130,145,.55)}
.chm.bad{filter:url(#glow)}
.lbl{font-weight:800;font-size:46px;fill:#fff;opacity:.16;pointer-events:none}
.vlbl{font-weight:700;font-size:13px;fill:var(--mu)}
#beat{transform-box:view-box;transform-origin:450px 470px;animation:beat 0.857s ease-in-out infinite}
@keyframes beat{0%,100%{transform:scale(1)}12%{transform:scale(1.012)}30%{transform:scale(.993)}}
@media (prefers-reduced-motion:reduce){#beat{animation:none}}
.shunt{display:none}.shunt.on{display:inline}
@media print{.noprint{display:none}#stageWrap{break-inside:avoid}}
</style></head><body><div class="wrap">

<h1>Kalp Kateterizasyonu Hemodinami Hesaplayıcı</h1>
<p class="sub">Basınç ve oksimetri değerlerini kalbin üzerindeki ilgili boşluğa girin. Debi (Fick/TD), direnç, şant, kapak alanı ve PH sınıflaması anında hesaplanır, kalp üzerinde renklendirilir ve yorumlanır.</p>

<div class="card noprint">
  <div class="bar">
    <label>Örnek vaka <select id="preset">
      <option value="">— seçin —</option>
      <option value="normal">Normal hemodinami</option>
      <option value="pah">Prekapiller PH (PAH)</option>
      <option value="cpc">Sol kalp hastalığı – CpcPH</option>
      <option value="ipc">Sol kalp hastalığı – IpcPH</option>
      <option value="asd">Sekundum ASD (sol→sağ şant)</option>
      <option value="vsd">VSD (ventriküler düzey şant)</option>
      <option value="as">Ciddi aort darlığı</option>
      <option value="ms">Ciddi mitral darlık</option>
      <option value="shock">Kardiyojenik şok (AMI)</option>
      <option value="cp">Konstriktif perikardit</option>
    </select></label>
    <button id="clear">Temizle</button>
    <button id="copy" class="pri">📋 Raporu kopyala</button>
    <button id="print">🖨️ Yazdır</button>
  </div>
  <div class="pt">
    <label>Boy (cm)<input id="h" inputmode="decimal"></label>
    <label>Kilo (kg)<input id="w" inputmode="decimal"></label>
    <label>Yaş<input id="age" inputmode="decimal"></label>
    <label>Cinsiyet<select id="sex"><option value="M">Erkek</option><option value="F">Kadın</option></select></label>
    <label>Kalp hızı (/dk)<input id="hr" inputmode="decimal"></label>
    <label>Hb (g/dL)<input id="hb" inputmode="decimal"></label>
    <label>VO₂ yöntemi<select id="vo2m"><option value="std">Varsayılan 125 mL/dk/m²</option><option value="lf">LaFarge (yaş, cins, KH)</option><option value="meas">Ölçülen</option></select></label>
    <label>Ölçülen VO₂ (mL/dk)<input id="vo2" inputmode="decimal" placeholder="ops."></label>
    <label>TD debisi (L/dk)<input id="tdco" inputmode="decimal" placeholder="ops."></label>
    <label>Hesapta debi<select id="cosrc"><option value="fick">Fick</option><option value="td">Termodilüsyon</option></select></label>
    <label>SEP (sn/atım)<input id="sep" inputmode="decimal" placeholder="AS için"></label>
    <label>DFP (sn/atım)<input id="dfp" inputmode="decimal" placeholder="MS için"></label>
    <label>Protokol / not<input id="note" placeholder="ops."></label>
    <div class="calc">VKA <b id="o_bsa">—</b> m²<br>VO₂ <b id="o_vo2">—</b> mL/dk</div>
  </div>
</div>

<div class="card" id="heartCard">
<div id="stageWrap"><div id="stage">
<svg id="heart" viewBox="0 0 980 790" aria-label="Kalp şeması üzerinde hemodinami girişi">
<defs>
  <radialGradient id="shade" cx="35%" cy="30%" r="75%"><stop offset="0" stop-color="#fff" stop-opacity=".38"/><stop offset=".55" stop-color="#fff" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".28"/></radialGradient>
  <filter id="glow" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  <filter id="soft" x="-10%" y="-10%" width="120%" height="120%"><feDropShadow dx="0" dy="6" stdDeviation="8" flood-opacity=".22"/></filter>
  <marker id="arw" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#fff"/></marker>
  <marker id="arwS" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="4" markerHeight="4" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#ffd24a"/></marker>
  <path id="fR1" d="M200,30 L200,250 C205,320 250,360 290,420 C320,480 300,560 350,560 C395,560 405,500 405,440 L405,175 C405,140 392,128 360,128 L222,128"/>
  <path id="fR2" d="M134,745 L134,390 C134,345 170,335 240,330 C300,335 320,400 300,460 C285,520 330,590 380,560 C402,540 405,490 405,440 L405,175 C405,142 420,132 452,132 L688,132"/>
  <path id="fL1" d="M880,240 L735,240 C650,245 610,300 610,390 C610,480 600,580 545,560 C510,545 503,490 503,440 L503,140 C503,62 560,52 640,52 C730,52 795,72 795,165 L795,745"/>
  <path id="fL2" d="M880,330 L735,330 C670,335 640,360 630,410 C620,500 610,600 540,580 C505,560 503,500 503,440 L503,140 C503,62 560,52 640,52 C730,52 795,72 795,165 L795,745"/>
  <path id="fASD" d="M600,352 C520,346 470,346 300,352"/>
  <path id="fASDr" d="M300,300 C470,308 520,308 600,300"/>
  <path id="fVSD" d="M610,612 C520,606 400,606 340,612"/>
  <path id="fPDA" d="M620,62 L620,128"/>
</defs>
<g id="beat" filter="url(#soft)">
  <!-- inen aorta (arka plan) -->
  <path d="M795,160 L795,745" stroke="#7a1f27" stroke-width="56" stroke-linecap="round" fill="none"/>
  <path id="v_aoD" d="M795,160 L795,745" stroke="#c83a3f" stroke-width="48" stroke-linecap="round" fill="none"/>
  <!-- PA dalları ve gövde -->
  <path d="M405,420 L405,175 C405,140 392,128 360,128 L222,128 M405,175 C405,142 420,132 452,132 L688,132" stroke="#2b2f55" stroke-width="48" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
  <path id="v_pa" d="M405,420 L405,175 C405,140 392,128 360,128 L222,128 M405,175 C405,142 420,132 452,132 L688,132" stroke="#6a5aa8" stroke-width="40" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
  <!-- PDA bağlantısı -->
  <path class="shunt" id="pdaTube" d="M620,72 L620,126" stroke="#ffd24a" stroke-width="16" stroke-linecap="round" fill="none" opacity=".9"/>
  <!-- boşluklar -->
  <path id="c_ra" class="chm na" d="M195,192 C150,195 140,232 142,282 C144,342 150,396 205,398 L398,398 L400,232 C400,206 382,192 356,192 Z"/>
  <path d="M195,192 C150,195 140,232 142,282 C144,342 150,396 205,398 L398,398 L400,232 C400,206 382,192 356,192 Z" fill="url(#shade)" pointer-events="none"/>
  <path id="c_la" class="chm na" d="M470,194 L700,194 C726,194 736,214 736,240 L736,352 C736,382 716,398 690,398 L470,398 Z"/>
  <path d="M470,194 L700,194 C726,194 736,214 736,240 L736,352 C736,382 716,398 690,398 L470,398 Z" fill="url(#shade)" pointer-events="none"/>
  <path id="c_rv" class="chm na" d="M170,410 L444,410 L446,702 C410,716 300,668 222,592 C176,548 160,482 170,410 Z"/>
  <path d="M170,410 L444,410 L446,702 C410,716 300,668 222,592 C176,548 160,482 170,410 Z" fill="url(#shade)" pointer-events="none"/>
  <path id="c_lv" class="chm na" d="M458,410 L740,410 C754,472 750,566 700,634 C640,704 540,738 458,736 Z"/>
  <path d="M458,410 L740,410 C754,472 750,566 700,634 C640,704 540,738 458,736 Z" fill="url(#shade)" pointer-events="none"/>
  <!-- pulmoner venler -->
  <path d="M880,240 L728,240 M880,330 L728,330" stroke="#7a1f27" stroke-width="36" stroke-linecap="round" fill="none"/>
  <path id="v_pv" d="M880,240 L728,240 M880,330 L728,330" stroke="#d8323b" stroke-width="29" stroke-linecap="round" fill="none"/>
  <!-- vena kavalar -->
  <path d="M200,26 L200,205" stroke="#232744" stroke-width="50" stroke-linecap="round" fill="none"/>
  <path id="v_svc" d="M200,26 L200,205" stroke="#55509a" stroke-width="42" stroke-linecap="round" fill="none"/>
  <path d="M134,745 L134,390 C134,352 150,340 172,338" stroke="#232744" stroke-width="50" stroke-linecap="round" fill="none"/>
  <path id="v_ivc" d="M134,745 L134,390 C134,352 150,340 172,338" stroke="#55509a" stroke-width="42" stroke-linecap="round" fill="none"/>
  <!-- çıkan aorta + arkus (önde) -->
  <path d="M503,420 L503,140 C503,62 560,52 640,52 C730,52 795,72 795,165" stroke="#7a1f27" stroke-width="56" stroke-linecap="round" fill="none"/>
  <path id="v_ao" d="M503,420 L503,140 C503,62 560,52 640,52 C730,52 795,72 795,165" stroke="#c83a3f" stroke-width="48" stroke-linecap="round" fill="none"/>
  <!-- kapaklar -->
  <g stroke="#fff" stroke-width="5" stroke-linecap="round" opacity=".85" fill="none">
    <path d="M205,404 Q262,420 300,404 Q340,420 392,404"/>
    <path d="M480,404 Q560,422 600,404 Q650,422 728,404"/>
    <path d="M385,416 Q405,428 425,416"/>
    <path d="M481,416 Q503,430 525,416"/>
  </g>
  <!-- şant okları -->
  <g id="shG" fill="none" stroke-linecap="round">
    <path class="shunt" id="asdArrow" d="M548,352 L330,352" stroke="#ffd24a" stroke-width="7" stroke-dasharray="10 8" marker-end="url(#arwS)"/>
    <path class="shunt" id="vsdArrow" d="M580,612 L360,612" stroke="#ffd24a" stroke-width="7" stroke-dasharray="10 8" marker-end="url(#arwS)"/>
  </g>
  <!-- etiketler -->
  <text class="lbl" x="232" y="385">RA</text><text class="lbl" x="250" y="660">RV</text>
  <text class="lbl" x="620" y="385">LA</text><text class="lbl" x="580" y="690">LV</text>
  <text class="vlbl" x="214" y="222" transform="rotate(-90 214 222)">SVC</text>
  <text class="vlbl" x="120" y="700">IVC</text>
  <text class="vlbl" x="236" y="168">RPA</text><text class="vlbl" x="640" y="168">LPA</text>
  <text class="vlbl" x="808" y="720">Desc. Ao</text>
  <text class="vlbl" x="828" y="372">Pulm. venler</text>
    <g id="particles"></g>
  <g id="shLbl" class="shunt"><rect x="380" y="310" width="158" height="26" rx="13" fill="#ffd24a"/><text id="shTxt" x="440" y="276" text-anchor="middle" font-size="14" font-weight="700" fill="#3a2a00">Şant</text></g>
</g>
</svg>

<!-- giriş çipleri (kalp üzerinde) -->
<div class="chip" data-c="svc" style="left:12px;top:38px;width:160px"><div class="ct"><span>SVC</span><small>süp. vena kava</small></div><div class="fs"><label class="f">SO₂ %<input id="svc_s" class="sat" inputmode="decimal"></label></div></div>
<div class="chip" data-c="ivc" style="left:4px;top:590px;width:108px"><div class="ct"><span>IVC</span></div><div class="fs"><label class="f">SO₂ %<input id="ivc_s" class="sat" inputmode="decimal"></label></div></div>
<div class="chip" data-c="ra" style="left:158px;top:206px;width:222px"><div class="ct"><span>RA</span><small>sağ atriyum · mmHg</small></div><div class="fs"><label class="f">a<input id="ra_a" inputmode="decimal"></label><label class="f">v<input id="ra_v" inputmode="decimal"></label><label class="f">ort<input id="ra_m" inputmode="decimal"></label><label class="f">SO₂ %<input id="ra_s" class="sat" inputmode="decimal"></label></div><div class="out" id="out_ra"></div></div>
<div class="chip" data-c="rv" style="left:188px;top:438px;width:196px"><div class="ct"><span>RV</span><small>sağ ventrikül</small></div><div class="fs"><label class="f">sist<input id="rv_sys" inputmode="decimal"></label><label class="f">EDP<input id="rv_edp" inputmode="decimal"></label><label class="f">SO₂ %<input id="rv_s" class="sat" inputmode="decimal"></label></div><div class="out" id="out_rv"></div></div>
<div class="chip" data-c="pa" style="left:232px;top:6px;width:236px"><div class="ct"><span>PA</span><small>pulmoner arter · mmHg</small></div><div class="fs"><label class="f">sist<input id="pa_sys" inputmode="decimal"></label><label class="f">diyast<input id="pa_dia" inputmode="decimal"></label><label class="f">ort<input id="pa_m" inputmode="decimal"></label><label class="f">SO₂ %<input id="pa_s" class="sat" inputmode="decimal"></label></div></div>
<div class="chip" data-c="la" style="left:540px;top:212px;width:184px"><div class="ct"><span>PCWP / LA</span><small>mmHg</small></div><div class="fs"><label class="f">a<input id="pw_a" inputmode="decimal"></label><label class="f">v<input id="pw_v" inputmode="decimal"></label><label class="f">ort<input id="pw_m" inputmode="decimal"></label></div><div class="out" id="out_la"></div></div>
<div class="chip" data-c="lv" style="left:536px;top:456px;width:170px"><div class="ct"><span>LV</span><small>sol ventrikül</small></div><div class="fs"><label class="f">sist<input id="lv_sys" inputmode="decimal"></label><label class="f">EDP<input id="lv_edp" inputmode="decimal"></label></div><div class="out" id="out_lv"></div></div>
<div class="chip" data-c="ao" style="left:832px;top:40px;width:142px"><div class="ct"><span>Aorta</span></div><div class="fs"><label class="f">sist<input id="ao_sys" inputmode="decimal"></label><label class="f">diyast<input id="ao_dia" inputmode="decimal"></label><label class="f">ort<input id="ao_m" inputmode="decimal"></label><label class="f">SO₂ %<input id="ao_s" class="sat" inputmode="decimal"></label></div><div class="out" id="out_ao"></div></div>
<div class="chip" data-c="pv" style="left:828px;top:262px;width:146px"><div class="ct"><span>PV</span><small>pulm. ven</small></div><div class="fs"><label class="f">SO₂ %<input id="pv_s" class="sat" inputmode="decimal" placeholder="vars."></label></div></div>
<div class="chip" data-c="av" style="left:436px;top:372px;width:140px"><div class="ct"><span>Aort kapak</span></div><div class="fs"><label class="f">ort. grad<input id="av_mg" inputmode="decimal"></label></div><div class="out" id="out_av"></div></div>
<div class="chip" data-c="mv" style="left:592px;top:372px;width:140px"><div class="ct"><span>Mitral kapak</span></div><div class="fs"><label class="f">ort. grad<input id="mv_mg" inputmode="decimal"></label></div><div class="out" id="out_mv"></div></div>
</div></div>
<div id="chipGrid"></div>
<div class="legend"><span><span class="satbar"></span> SO₂ %40 → %100 (boşluk rengi)</span><span><i style="background:var(--ok)"></i>normal</span><span><i style="background:var(--wa)"></i>sınırda/artmış</span><span><i style="background:var(--ba)"></i>belirgin anormal</span><span><i style="background:#ffd24a"></i>şant</span><span>Boş bırakılan ortalama PA/Ao basıncı (S+2D)/3 ile tahmin edilir.</span></div>
</div>

<div id="headline" class="headline"><small>Hemodinamik profil</small><b id="hl_t">Değer girin veya örnek vaka seçin</b><div class="chips" id="hl_c"></div></div>

<div class="card"><h2>Hesaplanan değerler</h2><div class="tiles" id="tiles"></div></div>

<div class="g2">
  <div class="card viz"><h2>Forrester / hemodinamik profil</h2><svg id="forr" viewBox="0 0 340 260"></svg><div class="note">X: PCWP (mmHg), Y: kardiyak indeks (L/dk/m²). Eşikler: PCWP 18, CI 2.2.</div></div>
  <div class="card viz"><h2>Pulmoner hipertansiyon sınıflaması</h2><svg id="phtree" viewBox="0 0 440 260"></svg><div class="note">ESC/ERS 2022 hemodinamik tanımları.</div></div>
</div>

<div class="card viz"><h2>Oksimetri koşusu (saturasyon basamağı)</h2><svg id="oxy" viewBox="0 0 700 230"></svg><div class="note" id="oxyNote">Tek örnek eşikleri: atriyal ≥%11 (SVC→RA), ventriküler ≥%10 (RA→RV), büyük arter ≥%5 (RV→PA).</div></div>

<div class="card"><h2>Yorum</h2><ul class="fd" id="find"></ul></div>

<div class="card" id="riskCard" style="display:none"><h2>PAH risk değerlendirmesi – hemodinamik parametreler (ESC/ERS 2022)</h2>
<table><thead><tr><th>Parametre</th><th>Değer</th><th>Düşük</th><th>Orta</th><th>Yüksek</th><th>Sınıf</th></tr></thead><tbody id="riskBody"></tbody></table>
<div class="note">Tam risk değerlendirmesi WHO-FC, 6DYT, BNP/NT-proBNP ve görüntüleme ile birlikte yapılmalıdır.</div></div>

<div class="card noprint"><details><summary>Metin raporu</summary><textarea id="report" readonly></textarea></details>
<details><summary>Formüller ve normal değerler</summary>
<table>
<tr><th>Parametre</th><th>Formül</th><th>Normal</th></tr>
<tr><td>VKA</td><td>√(boy × kilo / 3600) (Mosteller)</td><td>—</td></tr>
<tr><td>VO₂</td><td>125 mL/dk/m² × VKA · LaFarge: E 138,1 − 11,49·ln(yaş) + 0,378·KH; K 138,1 − 17,04·ln(yaş) + 0,378·KH</td><td>—</td></tr>
<tr><td>Fick debi (Qs)</td><td>VO₂ / [1,36 × Hb × 10 × (SaO₂ − SvO₂)]</td><td>4–8 L/dk · CI 2,5–4,0</td></tr>
<tr><td>Qp</td><td>VO₂ / [1,36 × Hb × 10 × (SpvO₂ − SpaO₂)]</td><td>Qp/Qs ≈ 1,0</td></tr>
<tr><td>Karışık venöz</td><td>Basamak yoksa PA; atriyal şantta Flamm (3·SVC + IVC)/4; ventriküler şantta RA; büyük arter düzeyinde RV</td><td>SvO₂ %65–80</td></tr>
<tr><td>PVR</td><td>(mPAP − PCWP) / Qp</td><td>≤2 WU</td></tr>
<tr><td>SVR</td><td>(OAB − RAP) / Qs × 80</td><td>800–1200 dyn·s·cm⁻⁵</td></tr>
<tr><td>TPG / DPG</td><td>mPAP − PCWP / dPAP − PCWP</td><td>≤12 / &lt;7 mmHg</td></tr>
<tr><td>PA kompliyansı</td><td>SV / (sPAP − dPAP)</td><td>&gt;2,3 mL/mmHg</td></tr>
<tr><td>PAPi</td><td>(sPAP − dPAP) / RAP</td><td>&gt;0,9 (AMİ), &gt;1,85 (KY)</td></tr>
<tr><td>CPO</td><td>OAB × CO / 451</td><td>≥0,6 W</td></tr>
<tr><td>Gorlin AVA</td><td>CO(mL/dk) / (KH × SEP × 44,3 × √ort. gradyan)</td><td>Ciddi &lt;1,0 cm² (AVAi &lt;0,6)</td></tr>
<tr><td>Gorlin MVA</td><td>CO(mL/dk) / (KH × DFP × 37,7 × √ort. gradyan)</td><td>Anlamlı ≤1,5 cm²</td></tr>
<tr><td>Hakki</td><td>CO(L/dk) / √gradyan (AS: tepe-tepe; MS: ortalama)</td><td>SEP/DFP yoksa yaklaşık</td></tr>
</table></details>
<p class="foot">Karar destek ve eğitim amaçlıdır. Sonuçlar ölçüm kalitesi (sıfırlama, wedge doğrulaması, solunum sonu okuma, eş zamanlı örnekleme) ve klinik bağlamla birlikte yorumlanmalıdır. Kaynaklar: ESC/ERS 2022 PH, ESC/EACTS 2025 kapak hastalığı, ESC 2020 erişkin doğumsal kalp hastalığı kılavuzları.</p></div>

</div>
<script>
const $=id=>document.getElementById(id);
const IDS=['h','w','age','sex','hr','hb','vo2m','vo2','tdco','cosrc','sep','dfp','note','svc_s','ivc_s','ra_a','ra_v','ra_m','ra_s','rv_sys','rv_edp','rv_s','pa_sys','pa_dia','pa_m','pa_s','pw_a','pw_v','pw_m','pv_s','lv_sys','lv_edp','ao_sys','ao_dia','ao_m','ao_s','av_mg','mv_mg'];
function n(id){const e=$(id);if(!e)return null;const s=String(e.value).trim().replace(',','.');if(s==='')return null;const x=parseFloat(s);return isFinite(x)?x:null}
const has=(...a)=>a.every(x=>x!==null&&x!==undefined&&isFinite(x));
function f(x,d=1){return has(x)?x.toFixed(d).replace('.',','):'—'}
// saturasyon → renk
function satColor(s){if(!has(s))return null;const t=Math.max(0,Math.min(1,(s-40)/60));const st=[[60,79,168],[123,90,166],[216,50,59]];const k=t<.55?0:1;const u=k?(t-.55)/.45:t/.55;const a=st[k],b=st[k+1];return`rgb(${a.map((v,i)=>Math.round(v+(b[i]-v)*u)).join(',')})`}
function dark(c,k=.55){const m=c.match(/\d+/g).map(Number);return`rgb(${m.map(v=>Math.round(v*k)).join(',')})`}

const PRESETS={
normal:{h:172,w:72,age:45,sex:'M',hr:70,hb:14,svc_s:74,ivc_s:79,ra_a:6,ra_v:5,ra_m:4,ra_s:75,rv_sys:25,rv_edp:4,rv_s:75,pa_sys:24,pa_dia:10,pa_m:15,pa_s:75,pw_a:10,pw_v:12,pw_m:9,lv_sys:118,lv_edp:9,ao_sys:118,ao_dia:72,ao_m:86,ao_s:97},
pah:{h:165,w:62,age:38,sex:'F',hr:92,hb:13,svc_s:58,ivc_s:62,ra_a:17,ra_v:15,ra_m:14,ra_s:59,rv_sys:86,rv_edp:14,rv_s:59,pa_sys:85,pa_dia:35,pa_m:52,pa_s:58,pw_a:9,pw_v:10,pw_m:9,lv_sys:104,lv_edp:9,ao_sys:105,ao_dia:68,ao_m:80,ao_s:95},
cpc:{h:160,w:84,age:71,sex:'F',hr:78,hb:12.5,svc_s:62,ivc_s:66,ra_a:14,ra_v:13,ra_m:12,ra_s:63,rv_sys:66,rv_edp:12,rv_s:63,pa_sys:65,pa_dia:30,pa_m:42,pa_s:63,pw_a:22,pw_v:30,pw_m:24,lv_sys:142,lv_edp:24,ao_sys:140,ao_dia:78,ao_m:99,ao_s:95},
ipc:{h:175,w:88,age:66,sex:'M',hr:74,hb:13.5,svc_s:66,ivc_s:70,ra_a:11,ra_v:10,ra_m:9,ra_s:67,rv_sys:42,rv_edp:9,rv_s:67,pa_sys:42,pa_dia:22,pa_m:29,pa_s:67,pw_a:20,pw_v:26,pw_m:22,lv_sys:130,lv_edp:21,ao_sys:130,ao_dia:75,ao_m:93,ao_s:96},
asd:{h:168,w:64,age:34,sex:'F',hr:76,hb:13.4,svc_s:70,ivc_s:74,ra_a:8,ra_v:7,ra_m:6,ra_s:84,rv_sys:38,rv_edp:6,rv_s:85,pa_sys:36,pa_dia:14,pa_m:22,pa_s:85,pw_a:9,pw_v:10,pw_m:8,lv_sys:115,lv_edp:8,ao_sys:115,ao_dia:70,ao_m:85,ao_s:97,pv_s:98},
vsd:{h:170,w:66,age:24,sex:'M',hr:80,hb:14.5,svc_s:72,ivc_s:76,ra_a:7,ra_v:6,ra_m:5,ra_s:73,rv_sys:48,rv_edp:7,rv_s:85,pa_sys:46,pa_dia:18,pa_m:28,pa_s:86,pw_a:11,pw_v:13,pw_m:10,lv_sys:118,lv_edp:10,ao_sys:118,ao_dia:68,ao_m:84,ao_s:97,pv_s:98},
as:{h:162,w:72,age:77,sex:'F',hr:72,hb:12.8,sep:0.33,svc_s:65,ivc_s:69,ra_a:10,ra_v:9,ra_m:8,ra_s:66,rv_sys:46,rv_edp:8,rv_s:66,pa_sys:42,pa_dia:19,pa_m:28,pa_s:66,pw_a:24,pw_v:22,pw_m:20,lv_sys:192,lv_edp:22,ao_sys:122,ao_dia:68,ao_m:88,ao_s:96,av_mg:50},
ms:{h:160,w:58,age:44,sex:'F',hr:78,hb:12.6,dfp:0.44,svc_s:61,ivc_s:65,ra_a:12,ra_v:14,ra_m:11,ra_s:62,rv_sys:62,rv_edp:10,rv_s:62,pa_sys:60,pa_dia:30,pa_m:41,pa_s:62,pw_a:'',pw_v:34,pw_m:25,lv_sys:108,lv_edp:6,ao_sys:108,ao_dia:68,ao_m:82,ao_s:95,mv_mg:11},
shock:{h:174,w:82,age:62,sex:'M',hr:112,hb:12,svc_s:44,ivc_s:49,ra_a:17,ra_v:18,ra_m:16,ra_s:45,rv_sys:42,rv_edp:16,rv_s:45,pa_sys:42,pa_dia:26,pa_m:32,pa_s:45,pw_a:26,pw_v:38,pw_m:28,lv_sys:84,lv_edp:28,ao_sys:82,ao_dia:55,ao_m:64,ao_s:95},
cp:{h:176,w:74,age:58,sex:'M',hr:88,hb:13.6,svc_s:63,ivc_s:67,ra_a:19,ra_v:18,ra_m:18,ra_s:64,rv_sys:36,rv_edp:18,rv_s:64,pa_sys:36,pa_dia:19,pa_m:25,pa_s:64,pw_a:20,pw_v:21,pw_m:19,lv_sys:104,lv_edp:20,ao_sys:105,ao_dia:68,ao_m:80,ao_s:96}
};

// ---------- sahne ölçekleme ----------
const wrapEl=$('stageWrap'),stage=$('stage'),chips=[...document.querySelectorAll('.chip')],grid=$('chipGrid');
let compact=null;
function fit(){const W=wrapEl.clientWidth;const s=W/980;const c=W<640;
 if(c!==compact){compact=c;document.body.classList.toggle('compact',c);chips.forEach(ch=>(c?grid:stage).appendChild(ch))}
 stage.style.transform=`scale(${s})`;wrapEl.style.height=(790*s)+'px'}
new ResizeObserver(fit).observe(wrapEl);fit();

// ---------- parçacık akışı ----------
const NS='http://www.w3.org/2000/svg',PG=$('particles');
const FLOWS=[{id:'fR1',n:7,side:'R'},{id:'fR2',n:9,side:'R'},{id:'fL1',n:9,side:'L'},{id:'fL2',n:8,side:'L'},{id:'fASD',n:5,side:'S',sh:'asd'},{id:'fVSD',n:5,side:'S',sh:'vsd'},{id:'fPDA',n:3,side:'S',sh:'pda'}];
FLOWS.forEach(F=>{F.p=$(F.id);F.len=F.p.getTotalLength();F.dots=[];for(let i=0;i<F.n;i++){const c=document.createElementNS(NS,'circle');c.setAttribute('r',F.side==='S'?5:4.2);c.setAttribute('stroke','#fff');c.setAttribute('stroke-width','1.2');c.setAttribute('opacity','.9');PG.appendChild(c);F.dots.push({el:c,u:i/F.n})}});
let HR=70,colR='#6a5aa8',colL='#d8323b',shState={asd:false,vsd:false,pda:false,rev:false},lastT=null;
function loop(t){if(lastT===null)lastT=t;const dt=Math.min(.05,(t-lastT)/1000);lastT=t;
 const sp=.14*(HR/70);
 FLOWS.forEach(F=>{const on=F.side!=='S'||shState[F.sh];F.dots.forEach(d=>{if(!on){d.el.setAttribute('opacity',0);return}
   d.u=(d.u+dt*sp*(F.side==='S'?1.6:1)*(700/Math.max(F.len,300)))%1;
   const p=F.p.getPointAtLength((F.side==='S'&&shState.rev&&F.sh!=='pda'?1-d.u:d.u)*F.len);d.el.setAttribute('cx',p.x);d.el.setAttribute('cy',p.y);
   const fade=Math.min(1,d.u*12,(1-d.u)*12);d.el.setAttribute('opacity',(.92*fade).toFixed(2));
   d.el.setAttribute('fill',F.side==='R'?colR:F.side==='L'?colL:(shState.rev?colR:colL))})});
 requestAnimationFrame(loop)}
if(!matchMedia('(prefers-reduced-motion: reduce)').matches)requestAnimationFrame(loop);

// ---------- yardımcılar ----------
function setCls(el,c){el.classList.remove('ok','warn','bad','na');el.classList.add(c)}
function lvl(x,warnHi,badHi){if(!has(x))return'na';return x>badHi?'bad':x>warnHi?'warn':'ok'}

// ---------- ana hesap ----------
function calc(){
 const g={};IDS.forEach(k=>{if(!['sex','vo2m','cosrc','note'].includes(k))g[k]=n(k)});
 const sex=$('sex').value,vo2m=$('vo2m').value,cosrc=$('cosrc').value;
 const R={};
 R.bsa=has(g.h,g.w)?Math.sqrt(g.h*g.w/3600):null;
 if(vo2m==='meas')R.vo2=g.vo2;
 else if(vo2m==='lf')R.vo2=has(g.age,g.hr,R.bsa)?((sex==='M'?138.1-11.49*Math.log(g.age):138.1-17.04*Math.log(g.age))+0.378*g.hr)*R.bsa:null;
 else R.vo2=has(R.bsa)?125*R.bsa:null;
 const cap=has(g.hb)?13.6*g.hb:null;
 // ortalamalar
 R.paM=g.pa_m??(has(g.pa_sys,g.pa_dia)?(g.pa_sys+2*g.pa_dia)/3:null);R.paMauto=g.pa_m===null&&has(R.paM);
 R.aoM=g.ao_m??(has(g.ao_sys,g.ao_dia)?(g.ao_sys+2*g.ao_dia)/3:null);R.aoMauto=g.ao_m===null&&has(R.aoM);
 $('pa_m').placeholder=R.paMauto?'≈'+Math.round(R.paM):'';$('ao_m').placeholder=R.aoMauto?'≈'+Math.round(R.aoM):'';
 // saturasyonlar
 const sa=g.ao_s;R.pvAssumed=g.pv_s===null&&has(sa);R.pv=g.pv_s??(has(sa)?(sa>=95?sa:98):null);
 $('pv_s').placeholder=R.pvAssumed?'≈'+R.pv:'vars.';
 R.flamm=has(g.svc_s,g.ivc_s)?(3*g.svc_s+g.ivc_s)/4:null;
 R.step=null;R.stepVal=null;
 if(has(g.ra_s,g.svc_s)&&g.ra_s-g.svc_s>=11){R.step='atriyal';R.stepVal=g.ra_s-g.svc_s}
 else if(has(g.rv_s,g.ra_s)&&g.rv_s-g.ra_s>=10){R.step='ventriküler';R.stepVal=g.rv_s-g.ra_s}
 else if(has(g.pa_s,g.rv_s)&&g.pa_s-g.rv_s>=5){R.step='büyük arter';R.stepVal=g.pa_s-g.rv_s}
 R.mv=R.step==='atriyal'?(R.flamm??g.svc_s):R.step==='ventriküler'?g.ra_s:R.step==='büyük arter'?g.rv_s:(g.pa_s??R.flamm);
 R.mvSrc=R.step==='atriyal'?(R.flamm!==null?'Flamm (3·SVC+IVC)/4':'SVC'):R.step==='ventriküler'?'RA':R.step==='büyük arter'?'RV':(g.pa_s!==null?'PA':'Flamm');
 R.qs=has(R.vo2,cap,sa,R.mv)&&sa>R.mv?R.vo2/(cap*(sa-R.mv)/100):null;
 R.qp=has(R.vo2,cap,R.pv,g.pa_s)&&R.pv>g.pa_s?R.vo2/(cap*(R.pv-g.pa_s)/100):null;
 R.qpqs=has(R.qp,R.qs)?R.qp/R.qs:null;
 R.shunt=R.step!==null||(has(R.qpqs)&&(R.qpqs>=1.2||R.qpqs<0.85));
 R.co=(cosrc==='td'&&has(g.tdco))?g.tdco:(R.qs??g.tdco);R.coSrc=(cosrc==='td'&&has(g.tdco))||(!has(R.qs)&&has(g.tdco))?'TD':'Fick';
 R.ci=has(R.co,R.bsa)?R.co/R.bsa:null;
 R.sv=has(R.co,g.hr)?R.co*1000/g.hr:null;R.svi=has(R.sv,R.bsa)?R.sv/R.bsa:null;
 R.tpg=has(R.paM,g.pw_m)?R.paM-g.pw_m:null;R.dpg=has(g.pa_dia,g.pw_m)?g.pa_dia-g.pw_m:null;
 R.qpUse=R.shunt&&has(R.qp)?R.qp:R.co;R.qsUse=R.shunt&&has(R.qs)?R.qs:R.co;
 R.pvr=has(R.tpg,R.qpUse)&&R.qpUse>0?R.tpg/R.qpUse:null;R.pvri=has(R.pvr,R.bsa)?R.pvr*R.bsa:null;
 R.svr=has(R.aoM,g.ra_m,R.qsUse)&&R.qsUse>0?(R.aoM-g.ra_m)/R.qsUse:null;R.svrD=has(R.svr)?R.svr*80:null;
 R.rprs=has(R.pvr,R.svr)&&R.svr>0?R.pvr/R.svr:null;
 R.pp=has(g.pa_sys,g.pa_dia)?g.pa_sys-g.pa_dia:null;R.pac=has(R.sv,R.pp)&&R.pp>0?R.sv/R.pp:null;
 R.papi=has(R.pp,g.ra_m)&&g.ra_m>0?R.pp/g.ra_m:null;R.rapw=has(g.ra_m,g.pw_m)&&g.pw_m>0?g.ra_m/g.pw_m:null;
 R.cpo=has(R.aoM,R.co)?R.aoM*R.co/451:null;
 R.avpp=has(g.lv_sys,g.ao_sys)?g.lv_sys-g.ao_sys:null;
 R.ava=null;R.avaM='';
 if(has(R.co,g.hr,g.sep,g.av_mg)&&g.av_mg>0){R.ava=R.co*1000/(g.hr*g.sep*44.3*Math.sqrt(g.av_mg));R.avaM='Gorlin'}
 else if(has(R.co,R.avpp)&&R.avpp>=10){R.ava=R.co/Math.sqrt(R.avpp);R.avaM='Hakki'}
 else if(has(R.co,g.av_mg)&&g.av_mg>0){R.ava=R.co/Math.sqrt(g.av_mg);R.avaM='Hakki (ort.)'}
 R.avai=has(R.ava,R.bsa)?R.ava/R.bsa:null;
 R.mva=null;R.mvaM='';
 if(has(R.co,g.hr,g.dfp,g.mv_mg)&&g.mv_mg>0){R.mva=R.co*1000/(g.hr*g.dfp*37.7*Math.sqrt(g.mv_mg));R.mvaM='Gorlin'}
 else if(has(R.co,g.mv_mg)&&g.mv_mg>0){R.mva=R.co/Math.sqrt(g.mv_mg);R.mvaM='Hakki'}
 R.rvpa=has(g.rv_sys,g.pa_sys)?g.rv_sys-g.pa_sys:null;
 R.svo2=R.step===null?g.pa_s:R.mv;
 // PH sınıfı
 R.ph=null;
 if(has(R.paM)){if(R.paM<=20)R.ph='yok';else if(!has(g.pw_m))R.ph='?';else if(g.pw_m<=15)R.ph=has(R.pvr)?(R.pvr>2?'pre':'unc'):'pre?';else R.ph=has(R.pvr)?(R.pvr>2?'cpc':'ipc'):'post?'}
 HR=has(g.hr)?g.hr:70;$('beat').style.animationDuration=(60/HR).toFixed(3)+'s';
 paint(g,R);tiles(g,R);forrester(g,R);phTree(g,R);oxy(g,R);const F=findings(g,R);risk(g,R);report(g,R,F);
}

// ---------- kalp boyama ----------
function paint(g,R){
 const def={svc:68,ivc:72,ra:70,rv:70,pa:70,la:97,lv:97,ao:97,pv:98};
 const sat={svc:g.svc_s,ivc:g.ivc_s,ra:g.ra_s,rv:g.rv_s,pa:g.pa_s,pv:R.pv,la:R.pv,lv:g.ao_s,ao:g.ao_s};
 const col=k=>satColor(sat[k]??def[k]);
 [['c_ra','ra'],['c_rv','rv'],['c_la','la'],['c_lv','lv']].forEach(([id,k])=>{$(id).style.fill=col(k)});
 [['v_svc','svc'],['v_ivc','ivc'],['v_pa','pa'],['v_pv','pv'],['v_ao','ao'],['v_aoD','ao']].forEach(([id,k])=>{$(id).style.stroke=col(k)});
 colR=col('pa');colL=col('ao');
 // basınç durumu
 const st={};
 st.ra=has(g.ra_m)?(g.ra_m>14?'bad':g.ra_m>=8?'warn':'ok'):'na';
 st.rv=has(g.rv_sys)||has(g.rv_edp)?(Math.max(lvl(g.rv_sys,30,50)==='bad'?2:lvl(g.rv_sys,30,50)==='warn'?1:0,lvl(g.rv_edp,8,14)==='bad'?2:lvl(g.rv_edp,8,14)==='warn'?1:0)):'na';
 if(st.rv!=='na')st.rv=['ok','warn','bad'][st.rv];
 st.pa=has(R.paM)?(R.paM>35?'bad':R.paM>20?'warn':'ok'):'na';
 st.la=has(g.pw_m)?(g.pw_m>20?'bad':g.pw_m>15?'warn':'ok'):'na';
 const lvA=has(g.lv_edp)?(g.lv_edp>18?2:g.lv_edp>12?1:0):-1,lvB=has(R.avpp)?(R.avpp>=40?2:R.avpp>=10?1:0):-1;
 st.lv=Math.max(lvA,lvB)<0?'na':['ok','warn','bad'][Math.max(lvA,lvB)];
 st.ao=has(R.aoM)?(R.aoM<65?'bad':(has(g.ao_sys)&&g.ao_sys>=140)?'warn':'ok'):'na';
 const sSat=x=>has(x)?(x<60?'bad':x<65?'warn':'ok'):'na';
 st.svc=sSat(g.svc_s);st.ivc=sSat(g.ivc_s);st.pv=has(R.pv)?(R.pv<95?'warn':'ok'):'na';
 st.av=has(R.ava)?(R.ava<1?'bad':R.ava<=1.5?'warn':'ok'):'na';st.mv=has(R.mva)?(R.mva<=1.5?'bad':R.mva<=2?'warn':'ok'):'na';
 ['ra','rv','la','lv'].forEach(k=>setCls($('c_'+k),st[k]));
 chips.forEach(ch=>{const k=ch.dataset.c;ch.classList.remove('ok','warn','bad');if(st[k]&&st[k]!=='na')ch.classList.add(st[k])});
 // çip altı çıktılar
 $('out_ra').innerHTML=has(R.papi)?`PAPi <b>${f(R.papi,2)}</b> · RAP/PCWP <b>${f(R.rapw,2)}</b>`:'';
 $('out_rv').innerHTML=has(R.rvpa)?`RV–PA sist. farkı <b>${f(R.rvpa,0)}</b> mmHg`:'';
 $('out_la').innerHTML=has(R.tpg)?`TPG <b>${f(R.tpg,0)}</b> · PVR <b>${f(R.pvr,1)}</b> WU`:'';
 $('out_lv').innerHTML=has(R.avpp)?`LV–Ao tepe-tepe <b>${f(R.avpp,0)}</b> mmHg`:'';
 $('out_ao').innerHTML=has(R.cpo)?`CPO <b>${f(R.cpo,2)}</b> W`:'';
 $('out_av').innerHTML=has(R.ava)?`AVA <b>${f(R.ava,2)}</b> cm² <span class="note">${R.avaM}</span>`:'';
 $('out_mv').innerHTML=has(R.mva)?`MVA <b>${f(R.mva,2)}</b> cm² <span class="note">${R.mvaM}</span>`:'';
 // şant görseli
 const sig=has(R.qpqs)&&R.qpqs>=1.2,rev=has(R.qpqs)&&R.qpqs<0.85;
 shState={asd:(R.step==='atriyal'&&sig)||(rev&&!R.step),vsd:R.step==='ventriküler'&&sig,pda:R.step==='büyük arter'&&sig,rev:rev};
 $('asdArrow').classList.toggle('on',shState.asd);$('vsdArrow').classList.toggle('on',shState.vsd);$('pdaTube').classList.toggle('on',shState.pda);
 $('asdArrow').setAttribute('d',rev?'M330,352 L548,352':'M548,352 L330,352');
 const lbl=$('shLbl');lbl.classList.toggle('on',shState.asd||shState.vsd||shState.pda);
 if(shState.asd||shState.vsd||shState.pda){const y=shState.vsd?568:shState.pda?178:310;lbl.querySelector('rect').setAttribute('y',y);$('shTxt').setAttribute('y',y+18);
  lbl.querySelector('rect').setAttribute('x',shState.pda?540:shState.vsd?390:380);$('shTxt').setAttribute('x',shState.pda?625:shState.vsd?469:465);
  $('shTxt').textContent=(rev?'Sağ→sol ':'Sol→sağ ')+'Qp/Qs '+f(R.qpqs,2)}
}

// ---------- karolar ----------
function tiles(g,R){
 const T=[
 ['Kardiyak debi ('+R.coSrc+')',R.co,'L/dk',2,'4–8',x=>x<4?'warn':x>8?'warn':'ok'],
 ['Kardiyak indeks',R.ci,'L/dk/m²',2,'2,5–4,0',x=>x<2.2?'bad':x<2.5?'warn':x>4.2?'warn':'ok'],
 ['Atım hacmi / SVİ',R.svi,'mL/m²',0,'33–47',x=>x<31?'bad':x<35?'warn':'ok',has(R.sv)?`SV ${f(R.sv,0)} mL`:''],
 ['Ortalama PAB',R.paM,'mmHg',0,'≤20',x=>x>35?'bad':x>20?'warn':'ok',R.paMauto?'(S+2D)/3 ile':''],
 ['PCWP',g.pw_m,'mmHg',0,'≤15',x=>x>20?'bad':x>15?'warn':'ok'],
 ['TPG',R.tpg,'mmHg',0,'≤12',x=>x>12?'warn':'ok'],
 ['DPG',R.dpg,'mmHg',0,'<7',x=>x>=7?'warn':'ok'],
 ['PVR',R.pvr,'WU',2,'≤2',x=>x>5?'bad':x>2?'warn':'ok',has(R.pvr)?`${f(R.pvr*80,0)} dyn · PVRİ ${f(R.pvri,1)}`:''],
 ['SVR',R.svrD,'dyn·s·cm⁻⁵',0,'800–1200',x=>x>1600||x<600?'bad':x>1200||x<800?'warn':'ok',has(R.svr)?`${f(R.svr,1)} WU`:''],
 ['Qp/Qs',R.qpqs,'',2,'≈1,0',x=>x>=1.5||x<0.85?'bad':x>=1.2?'warn':'ok',has(R.qp)?`Qp ${f(R.qp,2)} · Qs ${f(R.qs,2)} L/dk`:''],
 ['Rp/Rs',R.rprs,'',2,'<0,25',x=>x>=0.5?'bad':x>=0.25?'warn':'ok'],
 ['Kardiyak güç (CPO)',R.cpo,'W',2,'≥0,6',x=>x<0.6?'bad':x<0.8?'warn':'ok'],
 ['PAPi',R.papi,'',2,'>0,9 (>1,85 KY)',x=>x<0.9?'bad':x<1.85?'warn':'ok'],
 ['RAP/PCWP',R.rapw,'',2,'<0,63',x=>x>0.63?'warn':'ok'],
 ['PA kompliyansı',R.pac,'mL/mmHg',2,'>2,3',x=>x<2.3?'warn':'ok'],
 ['Karışık venöz SO₂',R.svo2,'%',0,'65–80',x=>x<60?'bad':x<65?'warn':'ok',R.step?R.mvSrc:''],
 ['Arteriyel SO₂',g.ao_s,'%',0,'≥95',x=>x<90?'bad':x<95?'warn':'ok'],
 ['AVA ('+(R.avaM||'—')+')',R.ava,'cm²',2,'ciddi <1,0',x=>x<1?'bad':x<=1.5?'warn':'ok',has(R.avai)?`AVAi ${f(R.avai,2)} cm²/m²`:''],
 ['MVA ('+(R.mvaM||'—')+')',R.mva,'cm²',2,'anlamlı ≤1,5',x=>x<=1.5?'bad':x<=2?'warn':'ok'],
 ];
 $('tiles').innerHTML=T.map(([t,x,u,d,nr,fn,ex])=>{const c=has(x)?fn(x):'na';return`<div class="tile ${c}"><small>${t}</small><b>${f(x,d)}</b> <span>${u}</span><em>${ex?ex+' · ':''}N: ${nr}</em></div>`}).join('');
 $('o_bsa').textContent=f(R.bsa,2);$('o_vo2').textContent=f(R.vo2,0);
}

// ---------- Forrester ----------
function forrester(g,R){
 const X=p=>40+p/40*285,Y=c=>225-c/5*210;const x18=X(18),y22=Y(2.2);
 let s=`<rect x="40" y="15" width="${x18-40}" height="${y22-15}" fill="#1f9d6b" opacity=".12"/><rect x="${x18}" y="15" width="${325-x18}" height="${y22-15}" fill="#d99a00" opacity=".13"/>
 <rect x="40" y="${y22}" width="${x18-40}" height="${225-y22}" fill="#2f6fd1" opacity=".12"/><rect x="${x18}" y="${y22}" width="${325-x18}" height="${225-y22}" fill="#d6363e" opacity=".14"/>
 <g font-size="11.5" font-weight="700" fill="currentColor" opacity=".75"><text x="48" y="32">I · Sıcak–kuru</text><text x="${x18+8}" y="32">II · Sıcak–ıslak</text><text x="48" y="216">III · Soğuk–kuru</text><text x="${x18+8}" y="216">IV · Soğuk–ıslak</text></g>
 <line x1="${x18}" y1="15" x2="${x18}" y2="225" stroke="currentColor" stroke-dasharray="4 3" opacity=".5"/><line x1="40" y1="${y22}" x2="325" y2="${y22}" stroke="currentColor" stroke-dasharray="4 3" opacity=".5"/>
 <line x1="40" y1="225" x2="325" y2="225" stroke="currentColor" opacity=".5"/><line x1="40" y1="15" x2="40" y2="225" stroke="currentColor" opacity=".5"/>`;
 for(let p=0;p<=40;p+=10)s+=`<text x="${X(p)}" y="240" font-size="10" text-anchor="middle" fill="currentColor" opacity=".7">${p}</text>`;
 for(let c=0;c<=5;c++)s+=`<text x="33" y="${Y(c)+4}" font-size="10" text-anchor="end" fill="currentColor" opacity=".7">${c}</text>`;
 s+=`<text x="182" y="256" font-size="11" text-anchor="middle" fill="currentColor" opacity=".8">PCWP (mmHg)</text><text x="12" y="120" font-size="11" text-anchor="middle" fill="currentColor" opacity=".8" transform="rotate(-90 12 120)">CI (L/dk/m²)</text>`;
 if(has(g.pw_m,R.ci)){const px=X(Math.min(40,Math.max(0,g.pw_m))),py=Y(Math.min(5,Math.max(0,R.ci)));
  s+=`<circle cx="${px}" cy="${py}" r="9" fill="none" stroke="#c0392b" stroke-width="2"><animate attributeName="r" values="7;16;7" dur="1.8s" repeatCount="indefinite"/><animate attributeName="opacity" values="1;0;1" dur="1.8s" repeatCount="indefinite"/></circle><circle cx="${px}" cy="${py}" r="6.5" fill="#c0392b" stroke="#fff" stroke-width="2"/>`}
 $('forr').innerHTML=`<g style="color:var(--tx)">${s}</g>`;
}

// ---------- PH ağacı ----------
function phTree(g,R){
 const on=R.ph,A='#c0392b';
 const node=(x,y,w,t,act,leaf)=>`<rect x="${x-w/2}" y="${y-16}" width="${w}" height="32" rx="${leaf?16:8}" fill="${act?A:'var(--sh)'}" stroke="${act?A:'var(--bd)'}"/><text x="${x}" y="${y+4.5}" text-anchor="middle" font-size="12" font-weight="${act?700:500}" fill="${act?'#fff':'var(--tx)'}">${t}</text>`;
 const edge=(x1,y1,x2,y2,t,act)=>`<path d="M${x1},${y1} C${x1},${(y1+y2)/2} ${x2},${(y1+y2)/2} ${x2},${y2}" fill="none" stroke="${act?A:'var(--bd)'}" stroke-width="${act?3:1.5}"/><text x="${(x1+x2)/2+(x2>x1?8:-8)}" y="${(y1+y2)/2}" font-size="10.5" text-anchor="${x2>x1?'start':'end'}" fill="var(--mu)">${t}</text>`;
 const ph=on&&on!=='yok',pre=['pre','unc','pre?'].includes(on),post=['cpc','ipc','post?'].includes(on);
 let s='';
 s+=edge(220,40,70,105,'≤20',on==='yok')+edge(220,40,290,105,'>20',ph);
 s+=edge(290,105,160,170,'≤15',pre)+edge(290,105,360,170,'>15',post);
 s+=edge(160,170,90,232,'>2 WU',on==='pre')+edge(160,170,215,232,'≤2 WU',on==='unc');
 s+=edge(360,170,300,232,'≤2 WU',on==='ipc')+edge(360,170,395,232,'>2 WU',on==='cpc');
 s+=node(220,24,150,'mPAP >20 mmHg?',!!on)+node(70,105,96,'PH yok',on==='yok',1)+node(290,105,120,'PCWP >15?',ph);
 s+=node(160,170,96,'PVR >2?',pre)+node(360,170,96,'PVR >2?',post);
 s+=node(90,238,112,'Prekapiller',on==='pre',1)+node(215,238,110,'Sınıflanamayan',on==='unc',1)+node(300,238,70,'IpcPH',on==='ipc',1)+node(395,238,72,'CpcPH',on==='cpc',1);
 $('phtree').innerHTML=s;
}

// ---------- oksimetri ----------
function oxy(g,R){
 const items=[['SVC',g.svc_s],['IVC',g.ivc_s],['RA',g.ra_s],['RV',g.rv_s],['PA',g.pa_s],['PV',R.pv,R.pvAssumed],['Ao',g.ao_s]];
 const bw=70,gap=22,x0=48,Y=s=>200-(s-30)/70*170;let s='';
 for(let v=40;v<=100;v+=20)s+=`<line x1="40" x2="690" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--bd)"/><text x="34" y="${Y(v)+4}" font-size="10" text-anchor="end" fill="var(--mu)">${v}</text>`;
 const stepIdx=R.step==='atriyal'?2:R.step==='ventriküler'?3:R.step==='büyük arter'?4:-1;
 items.forEach(([k,v,ass],i)=>{const x=x0+i*(bw+gap);
  if(has(v)){const c=satColor(v);s+=`<rect x="${x}" y="${Y(v)}" width="${bw}" height="${200-Y(v)}" rx="8" fill="${c}" ${ass?'opacity=".55" stroke-dasharray="4 3" stroke="var(--mu)"':''}/><text x="${x+bw/2}" y="${Y(v)-6}" font-size="13" font-weight="700" text-anchor="middle" fill="var(--tx)">${f(v,0)}%</text>`}
  else s+=`<rect x="${x}" y="40" width="${bw}" height="160" rx="8" fill="none" stroke="var(--bd)" stroke-dasharray="4 4"/>`;
  s+=`<text x="${x+bw/2}" y="218" font-size="12" text-anchor="middle" fill="var(--mu)">${k}${ass?' (vars.)':''}</text>`;
  if(i===stepIdx){s+=`<rect x="${x-6}" y="20" width="${bw+12}" height="186" rx="11" fill="none" stroke="#ffb400" stroke-width="3"/><text x="${x+bw/2}" y="16" font-size="12" font-weight="700" text-anchor="middle" fill="#d08a00">▲ +${f(R.stepVal,0)}%</text>`}
 });
 if(has(R.flamm)){const y=Y(R.flamm);s+=`<line x1="${x0}" x2="${x0+2*bw+gap}" y1="${y}" y2="${y}" stroke="var(--tx)" stroke-dasharray="5 4" opacity=".6"/><text x="${x0+2*bw+gap-6}" y="${y+15}" font-size="10.5" text-anchor="end" fill="#fff" font-weight="700">Flamm ${f(R.flamm,0)}%</text>`}
 $('oxy').innerHTML=s;
 $('oxyNote').innerHTML=(R.step?`<b>Basamak: ${R.step} düzey (+${f(R.stepVal,0)}%).</b> Karışık venöz: ${R.mvSrc} = ${f(R.mv,0)}%. `:'Anlamlı basamak yok. ')+'Tek örnek eşikleri: atriyal ≥%11 (SVC→RA), ventriküler ≥%10 (RA→RV), büyük arter ≥%5 (RV→PA).'+(R.pvAssumed?` PV ölçülmedi: ${R.pv>=95&&R.pv===g.ao_s?'SaO₂ ≥%95 olduğundan PV = SaO₂ kabul edildi':'SaO₂ <%95 olduğundan PV %98 kabul edildi (sağ→sol şant olasılığı)'}.`:'');
}

// ---------- yorum ----------
function findings(g,R){
 const F=[];const add=(l,t,d,p=0)=>F.push({l,t,d,p});
 // PH
 const pvrT=has(R.pvr)?`PVR ${f(R.pvr,1)} WU`:'';
 if(R.ph==='yok')add('ok','Pulmoner hipertansiyon yok',`mPAP ${f(R.paM,0)} mmHg (≤20).`);
 else if(R.ph==='?')add('warn','PH mevcut (mPAP >20) – sınıflama için PCWP gerekli',`mPAP ${f(R.paM,0)} mmHg.`);
 else if(R.ph==='pre')add('bad','Prekapiller pulmoner hipertansiyon',`mPAP ${f(R.paM,0)} mmHg, PCWP ${f(g.pw_m,0)} mmHg (≤15), ${pvrT} (>2). Grup 1 (PAH), 3, 4 ve 5 ayırıcı tanısı; vazoreaktivite testi IPAH/HPAH/ilaç ilişkili PAH'ta değerlendirilmeli.`+(g.pw_m>=13?' PCWP 13–15 aralığında: HFpEF risk profili varsa sıvı yüklemesi/egzersiz ile postkapiller komponent dışlanmalı.':''),8);
 else if(R.ph==='unc')add('warn','Sınıflandırılamayan PH',`mPAP ${f(R.paM,0)} >20 fakat PCWP ≤15 ve ${pvrT} (≤2). Yüksek pulmoner akım (şant, anemi, hipertiroidi) veya erken hastalık; egzersiz hemodinamisi düşünülebilir.`,4);
 else if(R.ph==='pre?')add('warn','PH; PCWP ≤15 – PVR için debi gerekli','Fick için Hb, VO₂/VKA ve saturasyonları ya da TD debisini girin.');
 else if(R.ph==='ipc')add('warn','İzole postkapiller PH (IpcPH)',`PCWP ${f(g.pw_m,0)} >15, ${pvrT} (≤2). Sol kalp hastalığına bağlı PH; volüm durumu/sol kalp tedavisi optimize edilmeli.`,6);
 else if(R.ph==='cpc')add('bad','Kombine pre- ve postkapiller PH (CpcPH)',`PCWP ${f(g.pw_m,0)} >15, ${pvrT} (>2).`+(R.pvr>5?' PVR >5 WU: ciddi prekapiller komponent – kötü prognoz; ileri merkez değerlendirmesi önerilir.':''),8);
 else if(R.ph==='post?')add('warn','Postkapiller PH (PVR hesaplanamadı)','IpcPH/CpcPH ayrımı için debi gerekli.');
 if(has(R.dpg)&&R.ph&&R.ph!=='yok'&&R.dpg>=7)add('info',`DPG ${f(R.dpg,0)} mmHg (≥7)`,'Prekapiller komponenti destekler (yardımcı parametre; sınıflama PVR ile yapılır).');
 if(has(R.pac)&&R.ph&&R.ph!=='yok'&&R.pac<2.3)add('warn',`PA kompliyansı düşük (${f(R.pac,2)} mL/mmHg)`,'<2,3 mL/mmHg PH’de kötü prognozla ilişkilidir.');
 // debi ve şok
 if(has(R.ci)){if(R.ci<2.2)add('bad',`Düşük kardiyak indeks (${f(R.ci,2)} L/dk/m²)`,`Debi kaynağı: ${R.coSrc}.`);
  else if(R.ci<2.5)add('warn',`Sınırda kardiyak indeks (${f(R.ci,2)})`,'');
  else if(R.ci>4.2&&!R.shunt)add('info',`Yüksek debi (CI ${f(R.ci,2)})`,'Anemi, sepsis, AV fistül, tirotoksikoz, beriberi gibi yüksek debili durumlar düşünülebilir.')}
 if(has(R.ci,g.pw_m)){const w=g.pw_m>18,c=R.ci<2.2;add(c&&w?'bad':c||w?'warn':'ok',`Forrester ${c?(w?'IV · Soğuk–ıslak':'III · Soğuk–kuru'):(w?'II · Sıcak–ıslak':'I · Sıcak–kuru')}`,c&&w?'Konjesyon + hipoperfüzyon: inotrop/vazopresör ve mekanik destek ihtiyacı açısından değerlendirin.':c?'Hipoperfüzyon, konjesyon yok: volüm yanıtı değerlendirilebilir.':w?'Konjesyon, perfüzyon korunmuş: diüretik/vazodilatör.':'Kompanse hemodinami.')}
 const hypo=(has(g.ao_sys)&&g.ao_sys<90)||(has(R.aoM)&&R.aoM<65);
 if(hypo&&has(R.ci)&&R.ci<2.2&&has(g.pw_m)&&g.pw_m>15)add('bad','Kardiyojenik şok ile uyumlu hemodinami',`SAB ${f(g.ao_sys,0)}, OAB ${f(R.aoM,0)} mmHg, CI ${f(R.ci,2)}, PCWP ${f(g.pw_m,0)}. SCAI evrelemesi laktat ve klinikle birlikte yapılmalı.`,10);
 else if(hypo)add('bad','Hipotansiyon',`OAB ${f(R.aoM,0)} mmHg.`);
 if(has(R.cpo)&&R.cpo<0.6)add('bad',`Kardiyak güç düşük (CPO ${f(R.cpo,2)} W)`,'Kardiyojenik şokta <0,6 W mortalitenin güçlü belirleyicisidir.');
 // RV
 if(has(g.ra_m)&&g.ra_m>14)add('bad',`RAP belirgin yüksek (${f(g.ra_m,0)} mmHg)`,'Sağ kalp yetmezliği/volüm yükü; PAH risk tablosunda yüksek risk kriteri.');
 else if(has(g.ra_m)&&g.ra_m>=8)add('warn',`RAP artmış (${f(g.ra_m,0)} mmHg)`,'');
 if(has(R.papi)&&R.papi<0.9)add('bad',`PAPi düşük (${f(R.papi,2)})`,'AMİ ilişkili şokta <0,9 ciddi RV disfonksiyonu ve RV destek ihtiyacı ile ilişkili.');
 else if(has(R.papi)&&R.papi<1.85)add('warn',`PAPi ${f(R.papi,2)}`,'İleri KY/LVAD adaylarında <1,85 RV yetmezliği riskini gösterir.');
 if(has(R.rapw)&&R.rapw>0.63)add('warn',`RAP/PCWP ${f(R.rapw,2)} (>0,63)`,'Sol kalbe göre orantısız sağ kalp dolum basıncı – RV yetmezliği lehine.');
 // LV / atriyum dalgaları
 if(has(g.lv_edp)&&g.lv_edp>18)add('bad',`LVEDP belirgin yüksek (${f(g.lv_edp,0)} mmHg)`,'');else if(has(g.lv_edp)&&g.lv_edp>12)add('warn',`LVEDP artmış (${f(g.lv_edp,0)} mmHg)`,'Normal ≤12 mmHg.');
 if(has(g.pw_v,g.pw_m)&&g.pw_v-g.pw_m>=10)add('warn',`Belirgin PCWP v dalgası (v ${f(g.pw_v,0)}, ort ${f(g.pw_m,0)})`,'Ciddi MY veya non-kompliyan LA düşündürür; v dalgası belirginse PCWP a dalgası sonunda/diyastol sonunda okunmalıdır.');
 if(has(g.ra_v,g.ra_m)&&g.ra_v-g.ra_m>=5&&g.ra_v>=1.5*g.ra_m)add('warn','Belirgin RA v dalgası','Triküspit yetmezliği lehine.');
 if(has(g.ra_a,g.ra_v)&&g.ra_a-g.ra_v>=5)add('info','Belirgin RA a dalgası','RV kompliyans azalması, triküspit darlık veya AV dissosiyasyon (cannon a) düşünülebilir.');
 // kapaklar
 if(has(R.ava)){const lf=has(R.svi)&&R.svi<=35;
  if(R.ava<1)add('bad',`Ciddi aort darlığı (AVA ${f(R.ava,2)} cm²${has(R.avai)?', AVAi '+f(R.avai,2):''})`,`${R.avaM}. `+(has(g.av_mg)?(g.av_mg>=40?`Ortalama gradyan ${f(g.av_mg,0)} ≥40 mmHg: yüksek gradyanlı ciddi AS.`:lf?`Ortalama gradyan <40 ve SVİ ≤35 mL/m²: düşük akım–düşük gradyan AS; EF düşükse dobutamin stres, korunmuşsa kalsiyum skoru ile doğrulayın.`:`Ortalama gradyan <40, akım normal: ölçüm hatası/uyumsuz ciddiyet açısından tekrar değerlendirin.`):'Ortalama gradyanı girin.'),9);
  else if(R.ava<=1.5)add('warn',`Orta aort darlığı (AVA ${f(R.ava,2)} cm²)`,R.avaM);
  else add('ok',`AVA ${f(R.ava,2)} cm²`,'Hemodinamik olarak anlamlı AS yok.')}
 else if(has(R.avpp)&&R.avpp>=10)add('warn',`LV–Ao sistolik gradyan ${f(R.avpp,0)} mmHg`,'AVA için debi gerekli. Subvalvüler/HOKMP ayrımı için geri çekme eğrisi değerlendirilmeli.');
 if(has(R.mva)){if(R.mva<=1)add('bad',`Çok ciddi mitral darlık (MVA ${f(R.mva,2)} cm²)`,`${R.mvaM}. Uygun anatomide PMBV/cerrahi değerlendirmesi.`,9);
  else if(R.mva<=1.5)add('bad',`Klinik olarak anlamlı (ciddi) mitral darlık (MVA ${f(R.mva,2)} cm²)`,`${R.mvaM}. Belirgin MY varsa Gorlin MVA’yı olduğundan küçük hesaplar.`,9);
  else if(R.mva<=2)add('warn',`Orta mitral darlık (MVA ${f(R.mva,2)} cm²)`,R.mvaM);else add('ok',`MVA ${f(R.mva,2)} cm²`,'')}
 if(has(R.rvpa)&&R.rvpa>10)add('warn',`RV–PA sistolik gradyan ${f(R.rvpa,0)} mmHg`,'Pulmoner kapak/RVOT darlığı açısından geri çekme eğrisi ile değerlendirin.');
 // konstriksiyon
 if(has(g.lv_edp,g.rv_edp,g.rv_sys)){const eq=Math.abs(g.lv_edp-g.rv_edp)<=5,rt=g.rv_edp/g.rv_sys>1/3,lo=g.rv_sys<55;
  if(eq&&rt&&lo&&g.rv_edp>=12)add('warn','Konstriktif fizyoloji ile uyumlu basınçlar',`LVEDP–RVEDP farkı ${f(Math.abs(g.lv_edp-g.rv_edp),0)} (≤5), RVEDP/RVSP ${f(g.rv_edp/g.rv_sys,2)} (>1/3), RVSP ${f(g.rv_sys,0)} (<55). Restriktif KMP’den ayrım için en güvenilir bulgu solunumla ventriküler etkileşim (sistolik alan indeksi >1,1); dip-plato ve Kussmaul bulgusunu da değerlendirin.`,7)}
 // şant ve oksijenasyon
 if(R.step)add('info',`Oksimetrik basamak: ${R.step} düzey (+${f(R.stepVal,0)}%)`,R.step==='atriyal'?'ASD, PAPVD, sinüs venozus, LV–RA şantı veya rüptüre sinüs Valsalva.':R.step==='ventriküler'?'VSD, PDA + PY, primum ASD + yarık.':'PDA, aortopulmoner pencere, anormal koroner köken.');
 if(has(R.qpqs)){if(R.qpqs>=1.5)add('bad',`Hemodinamik olarak anlamlı sol→sağ şant (Qp/Qs ${f(R.qpqs,2)})`,`Qp ${f(R.qp,2)}, Qs ${f(R.qs,2)} L/dk.`,8);
  else if(R.qpqs>=1.2)add('warn',`Küçük–orta sol→sağ şant (Qp/Qs ${f(R.qpqs,2)})`,'');
  else if(R.qpqs<0.85)add('bad',`Net sağ→sol şant (Qp/Qs ${f(R.qpqs,2)})`,'Eisenmenger fizyolojisi veya sağ→sol şantlı lezyonlar açısından değerlendirin.',8)
  if(R.qpqs>=1.2&&has(R.pvr)&&R.step!=='büyük arter'){if(R.pvr<3)add('ok',`Şant kapatılabilirliği: PVR ${f(R.pvr,1)} WU (<3)`,'RV volüm yükü varsa semptomdan bağımsız kapatma önerilir (ESC 2020 ACHD).');
   else if(R.pvr<5)add('warn',`Şant kapatılabilirliği: PVR ${f(R.pvr,1)} WU (3–5)`,'Anlamlı sol→sağ şant (Qp/Qs >1,5) varsa kapatma düşünülmeli; deneyimli merkezde bireysel karar.');
   else add('bad',`Şant kapatılabilirliği: PVR ${f(R.pvr,1)} WU (≥5)`,'Kapatma ancak hedefe yönelik PAH tedavisi sonrası PVR <5 WU ve Qp/Qs >1,5 ise (fenestre) düşünülebilir; Eisenmenger’de kontrendike.')}}
 if(has(g.ao_s)&&g.ao_s<90)add('bad',`Arteriyel desatürasyon (SaO₂ %${f(g.ao_s,0)})`,'Sağ→sol şant, akciğer hastalığı veya hipoventilasyon.');else if(has(g.ao_s)&&g.ao_s<95)add('warn',`Hafif arteriyel desatürasyon (SaO₂ %${f(g.ao_s,0)})`,'');
 if(has(R.svo2)&&!R.step){if(R.svo2<60)add('bad',`Düşük karışık venöz SO₂ (%${f(R.svo2,0)})`,'Doku O₂ ekstraksiyonu artmış – düşük debi/anemi/hipoksemi.');else if(R.svo2<65)add('warn',`Sınırda karışık venöz SO₂ (%${f(R.svo2,0)})`,'');else if(R.svo2>80)add('info',`Yüksek karışık venöz SO₂ (%${f(R.svo2,0)})`,'Sol→sağ şant, yüksek debi veya sepsis; örnekleme yerini kontrol edin.')}
 if(has(R.svrD)){if(R.svrD>1200)add('warn',`SVR artmış (${f(R.svrD,0)} dyn·s·cm⁻⁵)`,'Vazokonstriksiyon – düşük debili durumlarda kompansatuvar; afterload azaltımı düşünülebilir.');else if(R.svrD<800)add('warn',`SVR azalmış (${f(R.svrD,0)} dyn·s·cm⁻⁵)`,'Vazodilatasyon – sepsis, anafilaksi, AV fistül, siroz.')}
 if(R.coSrc==='TD'&&R.shunt)add('info','Termodilüsyon ve şant','İntrakardiyak şant veya ciddi TY varlığında TD debisi güvenilir değildir; Fick tercih edilmeli.');
 if(R.coSrc==='Fick'&&$('vo2m').value!=='meas'&&has(R.co))add('info','Varsayılan VO₂ kullanıldı','Tahmini Fick; özellikle yaşlı, obez veya kritik hastalarda %25’e varan hata olabilir. Mümkünse ölçülen VO₂ veya TD ile doğrulayın.');
 const ord={bad:0,warn:1,info:2,ok:3};F.sort((a,b)=>ord[a.l]-ord[b.l]);
 const ic={bad:'!',warn:'!',info:'i',ok:'✓'};
 $('find').innerHTML=F.length?F.map(x=>`<li class="${x.l}"><div class="ic">${ic[x.l]}</div><div><b>${x.t}</b><span>${x.d}</span></div></li>`).join(''):'<li class="info"><div class="ic">i</div><div><b>Henüz yorum yok</b><span>Basınç ve saturasyon değerlerini girin.</span></div></li>';
 // başlık
 const hl=$('headline');let t='Değer girin veya örnek vaka seçin',c='';
 const cand=F.filter(x=>x.l==='bad'||x.l==='warn');const top=cand.filter(x=>x.p>0).sort((a,b)=>b.p-a.p)[0]||cand.find(x=>x.l==='bad')||cand[0];
 if(F.length){if(top){t=top.t;c=top.l}else{t='Normal hemodinami';c='ok'}}
 hl.className='headline '+c;$('hl_t').textContent=t;
 const chipsT=[['CI',R.ci,2,'L/dk/m²'],['mPAP',R.paM,0,'mmHg'],['PCWP',g.pw_m,0,'mmHg'],['PVR',R.pvr,1,'WU'],['Qp/Qs',R.qpqs,2,''],['CPO',R.cpo,2,'W']].filter(x=>has(x[1]));
 $('hl_c').innerHTML=chipsT.map(x=>`<span>${x[0]} ${f(x[1],x[2])} ${x[3]}</span>`).join('')+F.filter(x=>x!==top&&(x.l==='bad')).slice(0,3).map(x=>`<span>⚠ ${x.t}</span>`).join('');
 return F;
}

// ---------- PAH risk ----------
function risk(g,R){
 const show=R.ph==='pre';$('riskCard').style.display=show?'':'none';if(!show)return;
 const rows=[['RAP (mmHg)',g.ra_m,0,'<8','8–14','>14',x=>x<8?'l':x<=14?'i':'h'],['CI (L/dk/m²)',R.ci,2,'≥2,5','2,0–2,4','<2,0',x=>x>=2.5?'l':x>=2?'i':'h'],['SVİ (mL/m²)',R.svi,0,'>38','31–38','<31',x=>x>38?'l':x>=31?'i':'h'],['SvO₂ (%)',R.svo2,0,'>65','60–65','<60',x=>x>65?'l':x>=60?'i':'h']];
 const nm={l:'Düşük',i:'Orta',h:'Yüksek'};
 $('riskBody').innerHTML=rows.map(([t,x,d,a,b,c,fn])=>`<tr><td>${t}</td><td><b>${f(x,d)}</b></td><td>${a}</td><td>${b}</td><td>${c}</td><td>${has(x)?`<span class="rk ${fn(x)}">${nm[fn(x)]}</span>`:'—'}</td></tr>`).join('');
}

// ---------- rapor ----------
function report(g,R,F){
 const L=[];const p=(a,b)=>L.push(a.padEnd(26,' ')+b);
 L.push('KALP KATETERİZASYONU – HEMODİNAMİ RAPORU');if($('note').value)L.push('Not: '+$('note').value);L.push('Tarih: '+new Date().toLocaleDateString('tr-TR'));L.push('');
 p('Boy/Kilo/VKA',`${f(g.h,0)} cm / ${f(g.w,0)} kg / ${f(R.bsa,2)} m²`);p('KH / Hb',`${f(g.hr,0)} /dk / ${f(g.hb,1)} g/dL`);p('VO₂',`${f(R.vo2,0)} mL/dk (${$('vo2m').selectedOptions[0].text})`);L.push('');
 L.push('BASINÇLAR (mmHg)');
 p('RA a/v/ort',`${f(g.ra_a,0)}/${f(g.ra_v,0)}/${f(g.ra_m,0)}`);p('RV sist/EDP',`${f(g.rv_sys,0)}/${f(g.rv_edp,0)}`);p('PA sist/diyast/ort',`${f(g.pa_sys,0)}/${f(g.pa_dia,0)}/${f(R.paM,0)}${R.paMauto?' (hesap)':''}`);
 p('PCWP a/v/ort',`${f(g.pw_a,0)}/${f(g.pw_v,0)}/${f(g.pw_m,0)}`);p('LV sist/EDP',`${f(g.lv_sys,0)}/${f(g.lv_edp,0)}`);p('Ao sist/diyast/ort',`${f(g.ao_sys,0)}/${f(g.ao_dia,0)}/${f(R.aoM,0)}${R.aoMauto?' (hesap)':''}`);
 if(has(g.av_mg))p('Aort kapak ort. gradyan',f(g.av_mg,0));if(has(g.mv_mg))p('Mitral kapak ort. gradyan',f(g.mv_mg,0));L.push('');
 L.push('OKSİMETRİ (%)');p('SVC/IVC/RA/RV/PA',[g.svc_s,g.ivc_s,g.ra_s,g.rv_s,g.pa_s].map(x=>f(x,0)).join('/'));p('PV/Ao',`${f(R.pv,0)}${R.pvAssumed?' (vars.)':''}/${f(g.ao_s,0)}`);L.push('');
 L.push('HESAPLANAN');p('Debi / CI',`${f(R.co,2)} L/dk (${R.coSrc}) / ${f(R.ci,2)} L/dk/m²`);p('SV / SVİ',`${f(R.sv,0)} mL / ${f(R.svi,0)} mL/m²`);p('TPG / DPG',`${f(R.tpg,0)} / ${f(R.dpg,0)} mmHg`);
 p('PVR / PVRİ',`${f(R.pvr,2)} WU / ${f(R.pvri,1)} WU·m²`);p('SVR',`${f(R.svrD,0)} dyn·s·cm⁻⁵ (${f(R.svr,1)} WU)`);p('Qp / Qs / Qp:Qs',`${f(R.qp,2)} / ${f(R.qs,2)} / ${f(R.qpqs,2)}`);
 p('CPO / PAPi / RAP:PCWP',`${f(R.cpo,2)} W / ${f(R.papi,2)} / ${f(R.rapw,2)}`);p('PA kompliyansı',`${f(R.pac,2)} mL/mmHg`);
 if(has(R.ava))p('AVA',`${f(R.ava,2)} cm² (${R.avaM})${has(R.avai)?' · AVAi '+f(R.avai,2):''}`);if(has(R.mva))p('MVA',`${f(R.mva,2)} cm² (${R.mvaM})`);
 L.push('');L.push('YORUM');F.forEach(x=>L.push('• '+x.t+(x.d?' – '+x.d:'')));
 $('report').value=L.join('\n');
}

// ---------- olaylar ----------
document.querySelectorAll('input,select').forEach(e=>{if(e.id!=='preset'){e.addEventListener('input',calc);e.addEventListener('change',calc)}});
$('preset').addEventListener('change',e=>{const P=PRESETS[e.target.value];if(!P)return;IDS.forEach(k=>{const el=$(k);if(!el||k==='note')return;if(el.tagName==='SELECT'){if(k==='sex')el.value=P.sex||'M';else if(k==='vo2m')el.value='std';else if(k==='cosrc')el.value='fick'}else el.value=(P[k]??'')});calc()});
$('clear').onclick=()=>{IDS.forEach(k=>{const el=$(k);if(el&&el.tagName!=='SELECT')el.value=''});$('preset').value='';calc()};
$('copy').onclick=async()=>{const t=$('report').value;let ok=false;try{await navigator.clipboard.writeText(t);ok=true}catch(e){const ta=$('report');ta.parentElement.open=true;ta.select();try{ok=document.execCommand('copy')}catch(_){}}
 $('copy').textContent=ok?'✓ Kopyalandı':'Metni seçip kopyalayın';setTimeout(()=>$('copy').textContent='📋 Raporu kopyala',1800)};
$('print').onclick=()=>window.print();
chips.forEach(ch=>{const k=ch.dataset.c,el=$('c_'+k);if(!el)return;ch.addEventListener('focusin',()=>el.style.strokeWidth=7);ch.addEventListener('focusout',()=>el.style.strokeWidth='')});
calc();
</script></body></html>
"""


# ===================== TRANSSEPTAL PONKSİYON SİMÜLASYONU (HTML) =====================
_TS_SIM_HTML = r"""<!DOCTYPE html>
<html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Transseptal Ponksiyon Simülasyonu</title>
<style>
:root{--bg:#f4f6f9;--card:#fff;--tx:#1b2430;--mu:#5d6b7c;--bd:#dde2e8;--sh:#eef1f5;--ac:#c0392b;--ok:#1e8e5a;--wa:#b86e00;--er:#c0392b;--bl:#2463b0}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0f141a;--card:#18202a;--tx:#e6ebf1;--mu:#9aa7b6;--bd:#2a3542;--sh:#212b37;--ok:#3cc488;--wa:#e8a33c;--er:#ef6a5d;--bl:#6aa6ec;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#0f141a;--card:#18202a;--tx:#e6ebf1;--mu:#9aa7b6;--bd:#2a3542;--sh:#212b37;--ok:#3cc488;--wa:#e8a33c;--er:#ef6a5d;--bl:#6aa6ec;color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1240px;margin:0 auto;padding:14px}
h1{font-size:21px;margin:2px 0}.sub{color:var(--mu);margin:0 0 10px}
h3{font-size:14px;margin:0 0 6px;display:flex;justify-content:space-between;align-items:center;gap:6px;flex-wrap:wrap}
.bar{display:flex;flex-wrap:wrap;gap:10px 16px;align-items:center;margin-bottom:10px}
select{font:inherit;padding:5px 8px;border-radius:8px;border:1px solid var(--bd);background:var(--card);color:var(--tx);max-width:100%}
button{font:inherit;font-size:13px;padding:5px 11px;margin:0 4px 4px 0;border-radius:16px;border:1px solid var(--bd);background:var(--card);color:var(--tx);cursor:pointer}
button:hover{border-color:var(--mu)}
button.on{background:var(--ac);border-color:var(--ac);color:#fff}
button:disabled{opacity:.4;cursor:not-allowed}
button.dim{opacity:.45}
button.pri{background:var(--bl);border-color:var(--bl);color:#fff}
button.dan{border-color:var(--er);color:var(--er)}
button.retract{background:var(--er);border-color:var(--er);color:#fff;animation:pl 1.2s ease-in-out infinite}
@keyframes pl{50%{box-shadow:0 0 0 5px rgba(192,57,43,.25)}}
@media (prefers-reduced-motion:reduce){button.retract{animation:none}}
.lock{display:none;font-size:12.5px;border-radius:8px;padding:6px 9px;margin:4px 0;background:rgba(192,57,43,.12);border:1px solid var(--er)}
.lock.on{display:block}.lock.okk{background:rgba(30,142,90,.12);border-color:var(--ok)}
.card{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:10px 12px;margin-bottom:12px}
.g2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.g3{display:grid;grid-template-columns:300px 1fr 1fr;gap:12px}
@media(max-width:1020px){.g3{grid-template-columns:1fr 1fr}.g3>.card:first-child{grid-column:1/-1}}
@media(max-width:760px){.g2,.g3{grid-template-columns:1fr}}
canvas{display:block;width:100%;height:auto;border-radius:8px;touch-action:none}
.btnrow{display:flex;flex-wrap:wrap;align-items:center}
.small{font-size:12px;color:var(--mu)}
.ctl{margin:8px 0}
.ctl label{display:flex;justify-content:space-between;font-size:12px;color:var(--mu);margin-bottom:2px}
.ctl input[type=range]{width:100%}
.dialrow{display:grid;grid-template-columns:150px 1fr;gap:10px;align-items:center}
.kv{display:grid;grid-template-columns:auto 1fr;gap:3px 10px;font-size:13px}
.kv span:nth-child(odd){color:var(--mu)}
.kv b{font-variant-numeric:tabular-nums}
.hint{background:var(--sh);border-radius:8px;padding:7px 10px;margin-top:8px;font-size:13px}
.hint.ok{border-left:4px solid var(--ok)}.hint.wa{border-left:4px solid var(--wa)}.hint.er{border-left:4px solid var(--er);}
.alert{border-radius:8px;padding:8px 10px;margin:8px 0;font-size:13px;display:none}
.alert.er{display:block;background:rgba(192,57,43,.12);border:1px solid var(--er)}
.alert.ok{display:block;background:rgba(30,142,90,.12);border:1px solid var(--ok)}
.alert.wa{display:block;background:rgba(184,110,0,.12);border:1px solid var(--wa)}
ol.steps{margin:0;padding-left:0;list-style:none;counter-reset:s}
ol.steps li{counter-increment:s;padding:5px 8px 5px 34px;position:relative;border-radius:8px;margin-bottom:3px;font-size:13px}
ol.steps li::before{content:counter(s);position:absolute;left:6px;top:5px;width:20px;height:20px;border-radius:50%;background:var(--sh);border:1px solid var(--bd);text-align:center;font-size:11px;line-height:19px}
ol.steps li.done{color:var(--mu)}ol.steps li.done::before{content:"✓";background:var(--ok);border-color:var(--ok);color:#fff}
ol.steps li.cur{background:var(--sh)}ol.steps li.cur::before{background:var(--bl);border-color:var(--bl);color:#fff}
ol.steps li .d{display:none;color:var(--mu);font-size:12px;margin-top:2px}ol.steps li.cur .d{display:block}
.chk{display:inline-flex;align-items:center;gap:4px;font-size:12px;color:var(--mu);margin-right:10px}
details{margin:4px 0}summary{cursor:pointer;font-weight:600;padding:3px 0}
details ul{margin:4px 0 8px;padding-left:20px}details li{margin:2px 0}
.tag{display:inline-block;font-size:11px;padding:1px 7px;border-radius:10px;background:var(--sh);border:1px solid var(--bd);color:var(--mu)}
.score{font-size:26px;font-weight:700;font-variant-numeric:tabular-nums}
kbd{font:11px ui-monospace,monospace;border:1px solid var(--bd);border-bottom-width:2px;border-radius:4px;padding:0 4px;background:var(--sh)}
.keys{display:flex;flex-wrap:wrap;gap:4px 14px;align-items:center;background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:7px 12px;margin-bottom:10px;font-size:12.5px;color:var(--mu)}.keys b{color:var(--tx)}.keys span{white-space:nowrap}
.foot{color:var(--mu);font-size:11.5px;margin-top:6px}
</style></head><body><div class="wrap">

<h1>Transseptal Ponksiyon Simülasyonu</h1>
<p class="sub">Floroskopi ve TEE eş zamanlı. Kılıfı/dilatörü SVK'dan geri çekin, iğne göstergesini çevirin, TEE ile hedefi doğrulayıp septumu çadırlandırın ve ponksiyonu yapın.</p>
<div class="keys"><b>Klavye kısayolları</b> <span>(çalışması için önce simülasyona bir kez tıklayın)</span>
 <span><kbd>↑</kbd><kbd>↓</kbd> ilerlet / geri çek</span>
 <span><kbd>←</kbd><kbd>→</kbd> saat yönü tersi (anterior) / saat yönü (posterior)</span>
 <span><kbd>+</kbd><kbd>−</kbd> septuma baskı</span>
 <span><kbd>N</kbd> iğne ilerlet / geri çek</span>
 <span><kbd>K</kbd> kontrast</span>
 <span><kbd>D</kbd> dilatör + kılıf</span>
 <span><kbd>T</kbd> tel</span>
 <span><kbd>1</kbd>–<kbd>4</kbd> C-kol (AP, RAO 30, RAO 45, LAO 45)</span>
 <span><kbd>Q</kbd><kbd>W</kbd><kbd>E</kbd><kbd>R</kbd> TEE (X-plane, bikaval, kısa aks, 4 boşluk)</span>
</div>

<div class="bar">
  <label>Prosedür <select id="proc"></select></label>
  <span id="procTag" class="tag"></span>
  <span class="chk"><input type="checkbox" id="guided" checked> Rehberli adımlar</span>
  <button id="reset" class="dan">↺ Baştan başla</button>
</div>

<div class="g2">
  <div class="card">
    <h3><span>Floroskopi</span><span class="btnrow" id="carmBtns"></span></h3>
    <canvas id="fl" width="560" height="440"></canvas>
    <div class="btnrow" style="margin-top:6px">
      <span class="chk"><input type="checkbox" id="fFossa" checked> Fossa / hedef katmanı (eğitim)</span>
      <span class="chk"><input type="checkbox" id="fLbl" checked> Etiketler</span>
      <span class="chk"><input type="checkbox" id="fCS"> KS kateteri (EP)</span>
      <span class="chk"><input type="checkbox" id="fPig" checked> Pigtail (NCC)</span>
    </div>
  </div>
  <div class="card">
    <h3><span>Transözofageal Eko</span><span class="btnrow" id="teeBtns"></span></h3>
    <canvas id="te" width="560" height="440"></canvas>
    <div class="btnrow" style="margin-top:6px">
      <span class="chk"><input type="checkbox" id="tLbl" checked> Anatomik etiketler</span>
      <span class="small" id="teeHint"></span>
    </div>
  </div>
</div>

<div class="g3">
  <div class="card">
    <h3>Kateter kontrolü</h3>
    <div class="dialrow">
      <canvas id="dial" width="150" height="150" title="Kadrana tıklayarak da çevirebilirsiniz"></canvas>
      <div>
        <div class="small">İğne göstergesi (ayak ucundan bakış)</div>
        <div style="font-size:22px;font-weight:700" id="rotTxt">12:00</div>
        <button id="ccw" title="Klavye: ←">↺ Saat yönü tersi<br><span class="small">→ anterior</span></button>
        <button id="cw" title="Klavye: →">↻ Saat yönü<br><span class="small">→ posterior</span></button>
      </div>
    </div>
    <div class="ctl">
      <label><span>Kılıf pozisyonu: <b id="hTxt"></b></span><span>↓ geri çek · ↑ ilerlet</span></label>
      <div class="btnrow"><button id="dn" title="Klavye: ↓">⬇ Geri çek</button><button id="up" title="Klavye: ↑">⬆ İlerlet</button></div>
      <input type="range" id="hS" min="-4.5" max="7" step="0.05" value="5.5">
      <div class="small" style="display:flex;justify-content:space-between"><span>İVK</span><span>fossa</span><span>SVK</span></div>
    </div>
    <div class="ctl">
      <label><span>Septuma ileri baskı (çadırlanma)</span><b id="pTxt">0%</b></label>
      <input type="range" id="pS" min="0" max="100" step="1" value="0">
    </div>
    <div class="btnrow">
      <button id="needle" class="pri" title="Klavye: N">🪡 İğneyi ilerlet</button>
      <button id="contrast" title="Klavye: K">💉 Kontrast / SF</button>
    </div>
    <div class="btnrow">
      <button id="dil" disabled>Dilatör + kılıfı LA'ya ilerlet</button>
      <button id="wire" disabled>Teli sol üst PV'ye</button>
    </div>
    <div class="lock" id="lockNote"></div>
    <div class="small" id="postNote">Bu iki adım, iğne fossadan LA'ya geçtikten sonra açılır.</div>
  </div>

  <div class="card">
    <h3><span>Fossa haritası</span><span class="small">RA tarafından en-face (RAO ile aynı yön)</span></h3>
    <canvas id="map" width="360" height="330"></canvas>
    <div class="btnrow" style="margin-top:4px"><span class="chk"><input type="checkbox" id="mTgt" checked> Hedef bölgeyi göster</span><span class="chk"><input type="checkbox" id="mIso" checked> Yükseklik eğrileri</span></div>
  </div>

  <div class="card">
    <h3>Canlı değerlendirme</h3>
    <div class="kv" id="kv"></div>
    <div class="hint" id="hint"></div>
    <div class="alert" id="alert"></div>
    <div style="margin-top:8px"><div class="small" id="prLbl">İğne ucu basıncı</div><canvas id="pr" width="360" height="96"></canvas></div>
  </div>
</div>

<div class="g2">
  <div class="card" id="stepCard">
    <h3>Rehberli adımlar</h3>
    <ol class="steps" id="steps"></ol>
  </div>
  <div class="card">
    <h3>Sonuç</h3>
    <div id="result" class="small">Henüz ponksiyon yapılmadı.</div>
  </div>
</div>

<div class="card" id="info"></div>

<div class="card">
  <h3>Temel bilgiler</h3>
  <details open><summary>Septum anatomisi: gerçek septum neresi?</summary><ul>
    <li><b>Gerçek interatriyal septum, büyük ölçüde fossa ovalis tabanıdır (septum primum).</b> İnce ve esnektir; çadırlanma burada belirgindir.</li>
    <li>Fossayı çevreleyen kalın <b>limbus</b> (septum sekundum) aslında atriyal duvarın içe katlanmasıdır (interatriyal oluk / Waterston oluğu). Süperior ve posterior kenardan geçiş <b>ekstrakardiyak / perikardiyal</b> olabilir.</li>
    <li>Anterosüperiorda <b>aort kökü (non-koroner kusp)</b>, posterosüperiorda SVK, posteroinferiorda İVK, anteroinferiorda koroner sinüs ağzı ve triküspit anülüsü bulunur.</li>
    <li>Fossa dört bölgeye ayrılır: süperior-anterior, süperior-posterior, inferior-anterior, inferior-posterior. Her işlemin ideal kadranı farklıdır.</li>
  </ul></details>
  <details><summary>Floroskopi ipuçları</summary><ul>
    <li><b>Saat kadranı (ayak ucundan bakış):</b> 12 anterior, 3 hastanın solu, 6 posterior, 9 hastanın sağı. Standart iğne yönü <b>saat 4–5</b>. Saat yönünde çevirmek ucu <b>posteriora</b>, tersine çevirmek <b>anteriora</b> götürür.</li>
    <li><b>LAO 40–50°:</b> septum kenardan (edge-on) görünür. Uç sağa (hastanın soluna, LA'ya) bakmalı. Geri çekerken iki sıçrama izlenir: <b>1.</b> SVK'dan RA'ya geçiş, <b>2.</b> limbusun altından fossaya düşüş.</li>
    <li><b>RAO 30–45°:</b> septum en-face görünür ve anterior–posterior ayrımı yapılır. Uç, aortik pigtail'in (NCC) <b>posterior-inferiorunda</b>, omurga tarafında olmalı.</li>
    <li>AP'de fossa çoğunlukla omurganın sağ kenarına yakın izdüşer. Dev LA'da (örn. ciddi MS) septum yataylaşır, fossa daha inferior ve posteriora kayar ve klasik işaretler yanıltıcı olabilir.</li>
  </ul></details>
  <details><summary>TEE ipuçları</summary><ul>
    <li><b>ME bikaval (≈90–110°):</b> SVK ekranın sağında, İVK solunda yer alır. Çadırlanmanın <b>süperior–inferior</b> konumu buradan değerlendirilir.</li>
    <li><b>ME aort kapak kısa aks (≈30–60°):</b> aorta ekranın sağında (anterior), posterior septum solda kalır. Çadırlanmanın <b>anterior–posterior</b> konumu buradan değerlendirilir. Aortaya yakın çadırlanma tehlikelidir.</li>
    <li><b>ME 4 boşluk (≈0°):</b> çadırlanma noktası ile mitral anülüs (koaptasyon) düzlemi arasındaki <b>yükseklik</b> ölçülür. M-TEER ve transseptal TMVR için kritiktir.</li>
    <li><b>X-plane:</b> bikaval ve kısa aks eş zamanlı görüntülenir, süperior-posterior hedef tek bakışta doğrulanır.</li>
    <li>Ponksiyon doğrulaması: LA basınç trasesi, LA'da kontrast ve TEE'de LA'da SF köpüğü. <b>Aortik basınç veya köpük görülürse iğneyi geri çekin, dilatörü asla ilerletmeyin.</b></li>
  </ul></details>
  <details><summary>Zor durumlar</summary><ul>
    <li><b>Anevrizmal septum:</b> büyük ve sarkık çadır oluşur, iğne geçmeden LA serbest duvarına yaklaşabilir. RF iğne veya kılavuz tel tekniği düşünülür.</li>
    <li><b>Kalın / lipomatöz septum, önceki cerrahi veya yama:</b> artmış direnç vardır. RF iğne veya dilatörle kontrollü ilerleme düşünülür, zorlamaktan kaçınılır.</li>
    <li><b>PFO:</b> PFO tünelinden geçiş anterosüperior çıkar, M-TEER ve LAAO için genellikle uygunsuz koaksiyalite sağlar. Hedefe yönelik ayrı ponksiyon tercih edilir.</li>
    <li><b>Önceki ASD/PFO kapatma cihazı:</b> cihazın genellikle posteroinferiorundaki doğal septumdan ponksiyon yapılır.</li>
  </ul></details>
  <p class="foot">Eğitim amaçlı şematik bir modeldir. Geometri, yükseklik ve basınç değerleri yaklaşık olup gerçek hasta anatomisinin yerini tutmaz. Hedefler: ESC/EACVI pratik önerileri ve yapısal kalp hastalığı girişim rehberleri (M-TEER: süperior-posterior, primer MY'de ≥4 cm, sekonder MY'de ≈3,5 cm; LAAO: inferior-posterior; kriyobalon PVİ: inferior-anterior).</p>
</div>
</div>

<script>
(function(){
"use strict";
const $=id=>document.getElementById(id);
const D2R=Math.PI/180, TAU=Math.PI*2;
const clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
const sstep=(e0,e1,x)=>{const t=clamp((x-e0)/(e1-e0),0,1);return t*t*(3-2*t)};
// ---------- 3B geometri ----------
// Hasta koordinatları: X = hastanın solu (+), Y = anterior (+), Z = süperior (+), cm
// Septal koordinatlar: a = RA→LA derinliği, u = septum düzleminde anterior, v = süperior
const N=[Math.SQRT1_2,-Math.SQRT1_2,0], UA=[Math.SQRT1_2,Math.SQRT1_2,0], ZV=[0,0,1];
const add=(a,b)=>[a[0]+b[0],a[1]+b[1],a[2]+b[2]], mul=(a,s)=>[a[0]*s,a[1]*s,a[2]*s];
const dot=(a,b)=>a[0]*b[0]+a[1]*b[1]+a[2]*b[2];
const norm=a=>{const l=Math.hypot(a[0],a[1],a[2])||1;return [a[0]/l,a[1]/l,a[2]/l]};
const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
function P(a,u,v){return [N[0]*a+UA[0]*u, N[1]*a+UA[1]*u, v]}
const FA=0.9, FB=1.1, SA=2.3, SB=2.7;          // fossa ve septum yarı-eksenleri
const AO={u:2.0,v:1.3,r:1.0};                   // aort kökü (NCC) septal izdüşümü
const SVC_U=-0.4, IVC_U=-0.8, RA_A=-1.8;
const heightAt=(u,v)=>3.7+0.9*v-0.35*u;          // mitral anülüs düzlemine yükseklik (cm)

const PROCS={
 teer_dmr:{ad:"M-TEER – primer (dejeneratif) MY",kisa:"Süperior-posterior · yükseklik ≥ 4,0–4,5 cm",t:{u:-0.45,v:0.62,ru:0.42,rv:0.4},h:[4.0,5.0],la:"mr",
  not:["Hedef: fossanın <b>süperior-posterior</b> kadranı. Posterior yön, klips sisteminin mitral düzleme dik inmesi için yer açar.",
   "Yükseklik <b>prolapsus/flail segmentinin</b> üzerinden düşünülmeli. Lezyon anülüsün üzerinde olduğundan primer MY'de daha yüksek ponksiyon (≥4–4,5 cm) gerekir.",
   "Çok süperior veya anterior ponksiyon kılavuzu aortaya yaklaştırır ve sistem mitral düzleme göre anterior kalır. Çok inferior ponksiyonda klipsi manevra ettirecek yükseklik kalmaz.",
   "Medial (A3/P3) lezyonlarda biraz daha yüksek ve posterior, lateral (A1/P1) lezyonlarda daha düşük yükseklik tolere edilebilir."]},
 teer_fmr:{ad:"M-TEER – sekonder (fonksiyonel) MY",kisa:"Posterior, orta-süperior · yükseklik ≈ 3,5–4,0 cm",t:{u:-0.45,v:0.12,ru:0.42,rv:0.42},h:[3.5,4.2],la:"mr",
  not:["Hedef yine <b>posterior</b>. Koaptasyon anülüsün altına (apikale) çekildiği için daha düşük bir yükseklik (≈3,5–4 cm) yeterlidir.",
   "Aşırı yüksek ponksiyon, tethering'li ve derin koaptasyon noktasına inerken sistemin LV'ye fazla girmesine ve kontrolün zorlaşmasına neden olabilir.",
   "Yükseklik ME 4 boşlukta (≈0°) çadırlanma noktasından koaptasyon düzlemine ölçülür."]},
 pmbv:{ad:"Perkütan mitral balon valvüloplasti (Inoue)",kisa:"Orta / hafif inferior-posterior fossa",t:{u:-0.22,v:-0.25,ru:0.55,rv:0.5},h:null,la:"ms",
  not:["Hedef: fossanın <b>orta–inferior ve hafif posterior</b> kısmı. Balonun LA içinde dönüp mitral kapağa yönlenmesine izin verir.",
   "Çok süperior veya anterior ponksiyon aortik kök riskini artırır ve balonun MV'ye yönlendirilmesini zorlaştırır.",
   "Ciddi MS'de dev LA septumu sağa ve aşağıya iter. Fossa daha inferior-posteriorda olabilir, TEE rehberliği bu nedenle değerlidir.",
   "Ponksiyon sonrası LA basıncı yüksektir (büyük a dalgası, yüksek ortalama basınç). Transmitral gradiyent ölçümüyle birlikte değerlendirilir."]},
 laao:{ad:"Sol atriyal apendiks kapatma (LAAO)",kisa:"İnferior-posterior",t:{u:-0.45,v:-0.6,ru:0.42,rv:0.42},h:null,la:"n",
  not:["Hedef: fossanın <b>inferior-posterior</b> kadranı. LAA anterior-süperior-lateraldedir, inferior-posterior giriş kılıfın LAA boynuyla <b>koaksiyel</b> hizalanmasını sağlar.",
   "Süperior veya anterior ponksiyonda kılıf LAA'nın tavanına veya posterior duvarına yönelir, cihazın eksen dışı yerleşme riski artar.",
   "Anatomiye göre uyarlanır: örneğin anterior yönelimli LAA'da hafif daha anterior bir ponksiyon tercih edilebilir. Gerekirse yönlendirilebilir kılıf kullanılır."]},
 af_cryo:{ad:"AF ablasyonu – kriyobalon PVİ",kisa:"İnferior-anterior",t:{u:0.38,v:-0.6,ru:0.42,rv:0.42},h:null,la:"n",
  not:["Hedef: fossanın <b>inferior-anterior</b> kısmı. Balonun sağ inferior PV'ye (RIPV) dönmesi için LA içinde yer açar.",
   "Çok posterior ponksiyon sağ PV'lere fazla yakın kalır, balon geri kıvrılamaz ve RIPV oklüzyonu zorlaşır.",
   "Anterior gidilirken aort köküne yakınlık her zaman kontrol edilmelidir."]},
 af_rf:{ad:"AF ablasyonu – RF (nokta nokta)",kisa:"Orta-inferior fossa (esnek)",t:{u:0.1,v:-0.35,ru:0.6,rv:0.55},h:null,la:"n",
  not:["RF kateterleri yönlendirilebilir kılıflarla geniş bir manevra alanına sahiptir. Fossanın orta–inferior kısmı genellikle yeterlidir.",
   "İnferior ponksiyon sağ inferior PV ve posterior duvar ulaşımını kolaylaştırır. Çift ponksiyonda iki giriş arasında mesafe bırakılır.",
   "EP laboratuvarında KS kateteri (anteroinferior) ve His bölgesi ek floroskopik işaret olarak kullanılabilir."]},
 tmvr:{ad:"Transseptal TMVR (valve-in-valve / ring)",kisa:"İnferior-posterior · yükseklik ≈ 3,5–4,0 cm",t:{u:-0.5,v:-0.3,ru:0.42,rv:0.42},h:[3.3,4.2],la:"mr",
  not:["Hedef: <b>inferior-posterior</b> ve orta yükseklik. Uzun ve sert kapak sisteminin LA içinde kıvrılıp mitral düzleme koaksiyel inmesi için alan sağlar.",
   "Çok yüksek ponksiyonda sistem LA tavanından dik açıyla iner ve koaksiyalite bozulur.",
   "Ponksiyon sonrası septostomi balonu ile genişletme gerekebilir."]},
 free:{ad:"Serbest pratik (hedef yok)",kisa:"Hedef gösterilmez",t:null,h:null,la:"n",
  not:["Serbest modda hedef bölge tanımlı değildir. Rotasyon ve geri çekmenin floroskopi ve TEE'deki karşılığını keşfedin.",
   "Deneyin: saat 3'e çevirip aort köküne doğru çadırlanma oluşturun, ardından saat 6'ya çevirip posterior kenarı görün."]}
};

const REG={fossa:"Fossa ovalis",sup:"Süperior limbus (septum sekundum)",inf:"İnferior limbus",ant:"Anterior limbus – aort köküne yakın",post:"Posterior kenar (posterior katlantı)",
 aorta:"Aort kökü (NCC) komşuluğu",wsup:"SVK–RA bileşkesi / RA tavanı",winf:"İVK – KS ağzı bölgesi",want:"Anterior RA duvarı (triküspit / RAA yönü)",wpost:"Posterior RA serbest duvarı",
 svc:"SVK içinde",ivc:"İVK girişi",free:"RA boşluğunda – septuma bakmıyor"};

// ---------- durum ----------
let S;
function initState(keepProc){
 const proc=keepProc&&S?S.proc:'teer_dmr';
 S={proc,h:5.5,rot:12,push:0,needleOut:false,crossed:false,outcome:null,sheathLA:false,wire:false,
  carm:45,tee:S?S.tee:'xp',fx:[],bub:[],mark:null,attempts:0,comp:0,result:null,alert:null,
  done:{},visited:{},startedSVC:true,prevRegion:'svc',jumps:0,lastMsgT:0};
}
initState(false);

function tipState(){
 const h=S.h, phi=S.rot*30*D2R, d=[Math.sin(phi),Math.cos(phi),0];
 const dn=dot(d,N), du=dot(d,UA);
 const uSh=-0.15+0.03*h;
 const r={d,dn,du,v:h,contact:false,region:'free',a:RA_A,u:uSh,tent:0,inSVC:false};
 if(h>2.6){ r.inSVC=true; r.region='svc'; r.a=RA_A+0.22*dn; r.u=SVC_U+0.22*du; }
 else if(h<-3.3){ r.region='ivc'; r.a=RA_A+0.3*dn; r.u=IVC_U+0.3*du; }
 else if(dn>0.3){
  let u=clamp(uSh+1.4*du/dn,-3.2,3.4); r.u=u; r.contact=true;
  const e=(u/FA)**2+(h/FB)**2, dA=Math.hypot(u-AO.u,h-AO.v), e2=(u/SA)**2+(h/SB)**2;
  let reg;
  if(e<=1) reg='fossa';
  else if(dA<AO.r) reg='aorta';
  else if(e2<=1){const qu=u/FA,qv=h/FB; reg=Math.abs(qv)>=Math.abs(qu)?(qv>0?'sup':'inf'):(qu>0?'ant':'post');}
  else {const qu=u/SA,qv=h/SB; reg=Math.abs(qv)>=Math.abs(qu)?(qv>0?'wsup':'winf'):(qu>0?'want':'wpost');}
  r.region=reg;
  r.a=-0.5*(1-sstep(1.08,0.92,e));
  if(reg==='aorta') r.a=-0.4;
  if(reg[0]==='w') r.a=-0.7-0.5*clamp((Math.sqrt(e2)-1)*2,0,1);
  const k=reg==='fossa'?1.15:(reg==='aorta'?0.28:(reg[0]==='w'?0.1:0.22));
  r.tent=S.crossed?0:S.push*k;
 } else { r.a=RA_A+0.9*Math.max(dn,-0.4); r.u=uSh+0.9*du; }
 r.height=heightAt(r.u,r.v);
 r.dA=Math.hypot(r.u-AO.u,r.v-AO.v)-AO.r;
 return r;
}
function quadName(u,v){
 const sv=v>0.3?'süperior':(v<-0.3?'inferior':'orta'); const su=u>0.25?'anterior':(u<-0.25?'posterior':'orta');
 if(sv==='orta'&&su==='orta') return 'merkez';
 if(sv==='orta') return 'orta-'+su; if(su==='orta') return sv+' (orta AP)';
 return sv+'-'+su;
}
const clockTxt=r=>{let x=((r%12)+12)%12; let hh=Math.floor(x), mm=Math.round((x-hh)*60); if(mm===60){hh++;mm=0} if(hh===0)hh=12; return hh+':'+String(mm).padStart(2,'0')};

// ---------- yardımcılar ----------
function catmull(pts,n){n=n||8;const out=[],L=pts[0].length;for(let i=0;i<pts.length-1;i++){const p0=pts[Math.max(0,i-1)],p1=pts[i],p2=pts[i+1],p3=pts[Math.min(pts.length-1,i+2)];
 for(let j=0;j<n;j++){const t=j/n,t2=t*t,t3=t2*t,q=[];for(let k=0;k<L;k++)q.push(0.5*(2*p1[k]+(-p0[k]+p2[k])*t+(2*p0[k]-5*p1[k]+4*p2[k]-p3[k])*t2+(-p0[k]+3*p1[k]-3*p2[k]+p3[k])*t3));out.push(q)}}
 out.push(pts[pts.length-1]);return out}
function bez3(a,c,b,n){const o=[];for(let i=0;i<=n;i++){const t=i/n,m=1-t;o.push([0,1,2].map(k=>m*m*a[k]+2*m*t*c[k]+t*t*b[k]))}return o}
function splitFromEnd(pts,L){let acc=0;for(let i=pts.length-1;i>0;i--){const a=pts[i],b=pts[i-1];const s=Math.hypot(a[0]-b[0],a[1]-b[1],a[2]-b[2]);
 if(acc+s>=L){const f=(L-acc)/s;const m=[a[0]+(b[0]-a[0])*f,a[1]+(b[1]-a[1])*f,a[2]+(b[2]-a[2])*f];return {prox:pts.slice(0,i).concat([m]),dist:[m].concat(pts.slice(i))}}acc+=s}
 return {prox:[pts[0]],dist:pts}}
function setupCanvas(cv){const dpr=Math.min(3,window.devicePixelRatio||1);
 // mantıksal boyut yalnızca ilk seferde HTML özniteliğinden okunur; sonraki yeniden boyutlandırmalarda büyümez
 if(!cv.dataset.w){cv.dataset.w=cv.getAttribute('width');cv.dataset.h=cv.getAttribute('height')}
 const w=+cv.dataset.w,h=+cv.dataset.h;cv.style.aspectRatio=w+' / '+h;cv._w=w;cv._h=h;cv.width=w*dpr;cv.height=h*dpr;const c=cv.getContext('2d');c.setTransform(dpr,0,0,dpr,0,0);return c}

// gürültü dokuları
function noiseCanvas(n,alpha){const c=document.createElement('canvas');c.width=c.height=n;const x=c.getContext('2d');const id=x.createImageData(n,n);
 for(let i=0;i<id.data.length;i+=4){const g=Math.random()*255;id.data[i]=id.data[i+1]=id.data[i+2]=g;id.data[i+3]=alpha*255*Math.random()}x.putImageData(id,0,0);return c}
const NOISE=[0,1,2].map(()=>noiseCanvas(140,0.55));
function speckleCanvas(n){const c=document.createElement('canvas');c.width=c.height=n;const x=c.getContext('2d');
 for(let i=0;i<n*n/5;i++){const g=120+Math.random()*135;x.fillStyle=`rgba(${g},${g},${g},${Math.random()*0.5})`;const w=1+Math.random()*2.5;x.fillRect(Math.random()*n,Math.random()*n,w,1+Math.random()*1.2)}return c}
const SPK=[speckleCanvas(200),speckleCanvas(200)];

const fl=$('fl'),te=$('te'),mp=$('map'),dl=$('dial'),pr=$('pr');
let fctx,tctx,mctx,dctx,pctx;
function setupAll(){fctx=setupCanvas(fl);tctx=setupCanvas(te);mctx=setupCanvas(mp);dctx=setupCanvas(dl);pctx=setupCanvas(pr)}
setupAll(); window.addEventListener('resize',()=>{setupAll()});

// ---------- sabit yapılar ----------
const PIG_PATH=catmull([[2.4,-4.6,-14],[2.4,-4.6,4.2],[2.1,-3.5,7.3],[1.3,-1.1,8.4],[0.9,1.1,7.4],[1.35,1.6,4.6],[1.7,1.35,2.6],P(0.45,1.55,1.35)],6);
const PIG_LOOP=(()=>{const c=P(0.45,1.55,0.85),o=[];const ax1=ZV,ax2=norm(UA);for(let i=0;i<=24;i++){const t=Math.PI/2+i/24*TAU*0.92;o.push(add(c,add(mul(ax1,0.5*Math.sin(t)),mul(ax2,0.5*Math.cos(t)))))}return o})();
const AO_PATH=catmull([P(0.6,2.0,0.6),[1.7,1.35,2.6],[1.35,1.6,4.6],[0.9,1.1,7.4],[1.3,-1.1,8.4],[2.1,-3.5,7.3],[2.4,-4.6,4.2]],6);
const LSPV=[P(3.7,-0.6,1.6),P(4.9,-0.3,2.3),P(5.7,0.1,2.6)];
const CS_PATH=(()=>{const CM=[2.6,-0.7,-2.9],m=norm([0.62,0.45,-0.64]),e1=norm(cross(m,ZV)),e2=cross(m,e1),R=2.15;
 const pt=t=>add(CM,add(mul(e1,R*Math.cos(t)),mul(e2,R*Math.sin(t))));
 let best=0,by=1e9;for(let i=0;i<72;i++){const t=i/72*TAU,y=pt(t)[1];if(y<by){by=y;best=t}}
 let arc=[];for(let i=0;i<=20;i++)arc.push(pt(best-1.7+3.4*i/20));
 if(arc[0][0]>arc[arc.length-1][0])arc.reverse();
 const os=arc[0];
 return {pre:catmull([P(RA_A,SVC_U,15),P(RA_A,SVC_U,3),P(-1.5,0.2,0.2),P(-1.0,0.7,-2.0),os],6),arc}})();

// ---------- kılıf yolu ----------
function sheathGeom(r){
 const base=P(RA_A,IVC_U,-14), ivcTop=P(RA_A,IVC_U,-3.5);
 const tip=P(r.a+r.tent,r.u,r.v);
 let pts,dir;
 if(r.inSVC){
  dir=norm(add(ZV,mul(r.d,0.25)));
  pts=catmull([base,ivcTop,P(RA_A,-0.5,0),P(RA_A,SVC_U,2.4),P(RA_A,SVC_U,Math.max(2.6,r.v-0.8)),tip],6);
 } else if(r.v<-3.3){
  dir=norm(add(ZV,mul(r.d,0.4)));
  pts=catmull([base,P(RA_A,IVC_U,r.v-2.5),tip],6);
 } else {
  dir=norm(add(mul(r.d,0.8),mul(ZV,0.55)));
  const kv=Math.max(r.v-2.4,-3.6);
  const K=P(RA_A-0.1,-0.45,kv), C=add(tip,mul(dir,-1.5));
  const lower=kv>-3.4?[base,ivcTop,K]:[base,K];
  pts=catmull(lower,6).concat(bez3(K,C,tip,10).slice(1));
 }
 return {pts,tip,dir};
}

// ---------- FLOROSKOPİ ----------
const FX0=262,FY0=205,KF=19;
let WOB=[0,0,0];
function drawFluoro(t,r){
 const c=fctx,W=560,H=440,al=S.carm*D2R,ca=Math.cos(al),sa=Math.sin(al);
 const ww=p=>clamp((p[2]+7)/3,0,1)*clamp((6.5-p[2])/3,0,1);
 const pr=(p,wob)=>{let x=p[0],y=p[1],z=p[2];if(wob!==false){const w=ww(p);x+=WOB[0]*w;y+=WOB[1]*w;z+=WOB[2]*w}return [FX0+KF*(x*ca-y*sa),FY0-KF*z]};
 const line=(pts,w,col,wob)=>{c.beginPath();pts.forEach((p,i)=>{const q=pr(p,wob);i?c.lineTo(q[0],q[1]):c.moveTo(q[0],q[1])});c.lineWidth=w;c.strokeStyle=col;c.lineCap='round';c.lineJoin='round';c.stroke()};
 const ellipsoid=(ctr,axes,fill,blur)=>{const rx=[ca,-sa,0],ry=[0,0,1];let sxx=0,syy=0,sxy=0;axes.forEach(a=>{const ax=dot(rx,a),ay=dot(ry,a);sxx+=ax*ax;syy+=ay*ay;sxy+=ax*ay});
  const tr=sxx+syy,det=sxx*syy-sxy*sxy,q=Math.sqrt(Math.max(0,tr*tr/4-det)),l1=tr/2+q,l2=Math.max(0.01,tr/2-q),th=0.5*Math.atan2(2*sxy,sxx-syy);
  const p=pr(ctr);c.save();if(blur)c.filter=`blur(${blur}px)`;c.beginPath();c.ellipse(p[0],p[1],KF*Math.sqrt(l1),KF*Math.sqrt(l2),-th,0,TAU);c.fillStyle=fill;c.fill();c.restore()};
 c.save();c.globalCompositeOperation='source-over';c.filter='none';
 const g=c.createRadialGradient(W/2,H/2,40,W/2,H/2,380);g.addColorStop(0,'#d9d9d6');g.addColorStop(1,'#8f8f8c');c.fillStyle=g;c.fillRect(0,0,W,H);
 c.globalCompositeOperation='multiply';
 // akciğer/mediasten
 const spx=pr([0,-6.5,0],false)[0];
 c.save();c.filter='blur(18px)';c.fillStyle='rgba(120,120,118,0.35)';c.fillRect(spx-KF*2.6,0,KF*5.2,H);c.restore();
 // diyafram
 c.save();c.filter='blur(10px)';c.fillStyle='rgba(80,80,78,0.45)';c.beginPath();c.moveTo(0,H);c.lineTo(0,FY0+KF*8.4);
 c.quadraticCurveTo(FX0-KF*5,FY0+KF*5.6,FX0+KF*0.5,FY0+KF*7.4);c.quadraticCurveTo(FX0+KF*6,FY0+KF*5.8,W,FY0+KF*8.8);c.lineTo(W,H);c.closePath();c.fill();c.restore();
 // omurga
 const vw=KF*(4.0*Math.abs(ca)+3.6*Math.abs(sa));
 for(let z=-13;z<13;z+=2.55){const p=pr([0,-6.5,z],false);c.fillStyle='rgba(60,60,58,0.22)';rr(c,p[0]-vw/2,p[1]-KF*1.0,vw,KF*2.0,6);c.fill();
  if(Math.abs(ca)>0.8){c.fillStyle='rgba(50,50,50,0.14)';c.beginPath();c.ellipse(p[0]-vw*0.32,p[1],5,7,0,0,TAU);c.ellipse(p[0]+vw*0.32,p[1],5,7,0,0,TAU);c.fill()}
  else{const sp=pr([0,-9.2,z],false);c.fillStyle='rgba(50,50,50,0.12)';c.beginPath();c.ellipse(sp[0],sp[1]+4,KF*0.9,KF*0.55,0,0,TAU);c.fill()}}
 // kalp gölgesi
 const la=norm([0.68,0.45,-0.58]),lb=norm(cross(la,ZV)),lc=cross(la,lb);
 ellipsoid([2.7,0.4,-2.9],[mul(la,6.2),mul(lb,4.6),mul(lc,4.2)],'rgba(70,70,68,0.33)',12);
 ellipsoid(P(-2.3,-0.2,-0.8),[mul(N,2.4),mul(UA,2.6),mul(ZV,2.8)],'rgba(70,70,68,0.22)',10);
 ellipsoid([1.4,-1.0,6.3],[[1.3,0,0],[0,1.3,0],[0,0,1.6]],'rgba(70,70,68,0.16)',8); // aortik topuz
 // kontrast efektleri
 const now=t;
 S.fx=S.fx.filter(f=>now-f.t0<f.dur);
 S.fx.forEach(f=>{const age=(now-f.t0)/f.dur,fi=Math.min(1,(now-f.t0)/0.25),fade=fi*(1-age)**1.3;
  if(f.type==='la'){const col=`rgba(20,20,20,${0.42*fade})`;ellipsoid(P(2.3,-0.3,0.3),[mul(N,2.0),mul(UA,2.4),mul(ZV,1.9)],col,3);
   ellipsoid(P(2.7,1.9,0.9),[mul(N,0.7),mul(UA,1.0),mul(ZV,0.6)],col,2);
   [[3.9,-0.6,1.5],[3.9,-0.6,-0.6],[2.0,-2.6,1.4],[2.0,-2.6,-0.7]].forEach(q=>ellipsoid(P(...q),[mul(N,0.9),mul(UA,0.5),mul(ZV,0.45)],col,2))}
  if(f.type==='ao'){const k=Math.min(1,(now-f.t0)/0.6);line(AO_PATH.slice(0,Math.max(2,Math.floor(AO_PATH.length*k))),KF*2.4,`rgba(25,25,25,${0.45*(1-age)})`)}
  if(f.type==='stain'){const p=f.p;ellipsoid(p,[mul(N,0.25),mul(UA,0.55),mul(ZV,0.7)],`rgba(15,15,15,${0.55*(1-age)})`,2)}
  if(f.type==='ra'){const p=f.p;ellipsoid(p,[mul(N,0.6+age*2),mul(UA,0.6+age*2),mul(ZV,0.8+age*2.5)],`rgba(30,30,30,${0.35*(1-age)})`,6)}
  if(f.type==='peri'){c.save();c.lineWidth=7;c.strokeStyle=`rgba(20,20,20,${0.3*(1-age)})`;c.filter='blur(3px)';const p=pr([2.7,0.4,-2.9]);c.beginPath();c.ellipse(p[0],p[1],KF*6.4,KF*4.7,-0.5,0,TAU);c.stroke();c.restore()}
 });
 // TEE probu
 line([P(4.0,-1.2,15),P(4.0,-1.2,1.8)],KF*0.85,'rgba(40,40,40,0.38)',false);
 line([P(4.0,-1.2,1.8),P(4.0,-1.2,-0.5)],KF*1.25,'rgba(25,25,25,0.6)',false);
 // pigtail
 if($('fPig').checked){line(PIG_PATH,3.2,'rgba(15,15,15,0.75)');line(PIG_LOOP,3.2,'rgba(15,15,15,0.75)')}
 // KS kateteri
 if($('fCS').checked){line(CS_PATH.pre,3.4,'rgba(15,15,15,0.75)');line(CS_PATH.arc,3.4,'rgba(15,15,15,0.75)');
  CS_PATH.arc.forEach((p,i)=>{if(i%2===0){const q=pr(p);c.fillStyle='rgba(0,0,0,0.85)';c.fillRect(q[0]-3,q[1]-3,6,6)}})}
 // eğitim katmanı: fossa izdüşümü
 if($('fFossa').checked){c.globalCompositeOperation='source-over';
  const ring=(cu,cv,ra,rb,col,dash,wd)=>{c.beginPath();for(let i=0;i<=40;i++){const th=i/40*TAU;const q=pr(P(0,cu+ra*Math.cos(th),cv+rb*Math.sin(th)));i?c.lineTo(q[0],q[1]):c.moveTo(q[0],q[1])}c.setLineDash(dash||[]);c.lineWidth=wd||1.5;c.strokeStyle=col;c.stroke();c.setLineDash([])};
  ring(0,0,SA,SB,'rgba(30,80,160,0.35)',[3,4],1.2);ring(0,0,FA,FB,'rgba(30,90,200,0.85)',[5,3],1.6);
  const pp=PROCS[S.proc];if(pp.t&&$('mTgt').checked)ring(pp.t.u,pp.t.v,pp.t.ru,pp.t.rv,'rgba(20,150,80,0.9)',[],2);
  c.globalCompositeOperation='multiply'}
 // kılıf / dilatör / iğne
 const G=sheathGeom(r);let pts=G.pts.slice();
 if(S.sheathLA){pts=pts.concat([add(G.tip,mul(G.dir,0.8)),add(G.tip,mul(G.dir,1.7))])}
 const sp=splitFromEnd(pts,S.sheathLA?0.9:1.4);
 const ndl=S.needleOut&&!S.sheathLA?pts.concat([add(G.tip,mul(G.dir,0.65))]):splitFromEnd(pts,0.6).prox;
 if(!S.wire||!S.sheathLA) line(ndl,1.8,'rgba(0,0,0,0.75)');
 line(sp.prox,KF*0.3,'rgba(30,30,30,0.5)');
 line(sp.dist,KF*0.2,'rgba(40,40,40,0.42)');
 const mk=pr(sp.prox[sp.prox.length-1]);c.fillStyle='rgba(0,0,0,0.85)';c.beginPath();c.arc(mk[0],mk[1],3.4,0,TAU);c.fill();
 if(S.wire){const st=pts[pts.length-1];line(catmull([st,P(2.0,-0.3,0.7)].concat(LSPV),6),1.6,'rgba(0,0,0,0.8)')}
 // gürültü
 c.globalCompositeOperation='overlay';c.globalAlpha=0.5;const nz=NOISE[(Math.random()*3)|0];const ox=Math.random()*140,oy=Math.random()*140;
 for(let x=-ox;x<W;x+=140)for(let y=-oy;y<H;y+=140)c.drawImage(nz,x,y);
 c.globalAlpha=1;c.globalCompositeOperation='source-over';
 const vg=c.createRadialGradient(W/2,H/2,H*0.42,W/2,H/2,H*0.85);vg.addColorStop(0,'rgba(0,0,0,0)');vg.addColorStop(1,'rgba(0,0,0,0.45)');c.fillStyle=vg;c.fillRect(0,0,W,H);
 c.restore();
 // etiketler
 c.save();c.font='600 12px system-ui,sans-serif';
 const lab=(p,txt,dx,dy,wob)=>{const q=pr(p,wob);halo(c,txt,q[0]+(dx||0),q[1]+(dy||0),'#111')};
 const cname=S.carm===0?'AP':(S.carm>0?'LAO '+S.carm+'°':'RAO '+(-S.carm)+'°');
 c.font='700 15px system-ui,sans-serif';halo(c,cname,12,22,'#111');
 c.font='12px system-ui,sans-serif';
 const ori=S.carm===0?'Hastanın sağı ◀  ▶ Hastanın solu':(S.carm>0?'◀ Anterior   ·   Posterior (omurga) ▶':'◀ Posterior (omurga)   ·   Anterior ▶');
 halo(c,ori,W/2-c.measureText(ori).width/2,H-10,'#222');
 if($('fLbl').checked){c.font='600 11.5px system-ui,sans-serif';
  if($('fPig').checked)lab(P(0.45,1.55,0.85),'Pigtail (NCC)',18,-26);
  lab(P(4.0,-1.2,-0.8),'TEE probu',14,14,false);
  lab([0,-6.5,-9.5],'Omurga',vw/2+4,0,false);
  lab(P(RA_A,IVC_U,-6),'SL kılıf',10,0);
  if($('fCS').checked)lab(CS_PATH.arc[12],'KS',8,10);
  const tq=pr(G.tip);if(S.crossed)halo(c,'→ LA',tq[0]+10,tq[1]-6,'#0a3a8a');else halo(c,'Dilatör ucu',tq[0]-78,tq[1]+4,'#0a3a8a');
  if($('fFossa').checked){const fq=pr(P(0,-FA,-FB-0.2));halo(c,'fossa (şematik)',fq[0]-30,fq[1]+14,'#1d4fa0')}}
 c.restore();
}
function rr(c,x,y,w,h,r){c.beginPath();c.moveTo(x+r,y);c.arcTo(x+w,y,x+w,y+h,r);c.arcTo(x+w,y+h,x,y+h,r);c.arcTo(x,y+h,x,y,r);c.arcTo(x,y,x+w,y,r);c.closePath()}
function halo(c,txt,x,y,col){c.lineWidth=3;c.strokeStyle='rgba(255,255,255,0.75)';c.strokeText(txt,x,y);c.fillStyle=col;c.fillText(txt,x,y)}

// ---------- TEE ----------
function teeFrame(x0,y0,w,h,depth,half){half=(half||45)*D2R;const apx=x0+w/2,apy=y0+18;const R=Math.min(h-30,(w/2-6)/Math.sin(half));const k=R/depth;
 return {x0,y0,w,h,apx,apy,R,k,half,depth,T:(lx,d)=>[apx+lx*k,apy+d*k]}}
function sectorPath(c,F){c.beginPath();c.moveTo(F.apx,F.apy);c.arc(F.apx,F.apy,F.R,Math.PI/2-F.half,Math.PI/2+F.half);c.closePath()}
function polyCm(c,F,pts){c.beginPath();pts.forEach((p,i)=>{const q=F.T(p[0],p[1]);i?c.lineTo(q[0],q[1]):c.moveTo(q[0],q[1])});c.closePath()}
function lineCm(c,F,pts,w,col){c.beginPath();pts.forEach((p,i)=>{const q=F.T(p[0],p[1]);i?c.lineTo(q[0],q[1]):c.moveTo(q[0],q[1])});c.lineWidth=w;c.strokeStyle=col;c.lineCap='round';c.lineJoin='round';c.stroke()}
function ellCm(c,F,cx,cy,rx,ry){const q=F.T(cx,cy);c.beginPath();c.ellipse(q[0],q[1],rx*F.k,ry*F.k,0,0,TAU)}
function cavity(c,F,fn){c.save();c.filter='blur(2px)';c.fillStyle='#060606';fn();c.fill();c.restore()}
function tissueBase(c,F,t){c.fillStyle='#4b4b4b';sectorPath(c,F);c.fill();c.save();sectorPath(c,F);c.clip();c.globalAlpha=0.7;const s=SPK[(t*12|0)%2];
 for(let x=F.x0;x<F.x0+F.w;x+=200)for(let y=F.y0;y<F.y0+F.h;y+=200)c.drawImage(s,x,y);c.restore()}
function teeFinish(c,F,t,title,angle){
 c.save();sectorPath(c,F);c.clip();
 c.globalCompositeOperation='overlay';c.globalAlpha=0.35;const s=SPK[((t*12|0)+1)%2];for(let x=F.x0-50;x<F.x0+F.w;x+=200)for(let y=F.y0;y<F.y0+F.h;y+=200)c.drawImage(s,x,y);
 c.globalCompositeOperation='source-over';c.globalAlpha=1;
 const g=c.createRadialGradient(F.apx,F.apy,0,F.apx,F.apy,F.R);g.addColorStop(0,'rgba(255,255,255,0.18)');g.addColorStop(0.07,'rgba(0,0,0,0)');g.addColorStop(0.55,'rgba(0,0,0,0)');g.addColorStop(1,'rgba(0,0,0,0.55)');c.fillStyle=g;c.fillRect(F.x0,F.y0,F.w,F.h);
 c.restore();
 c.strokeStyle='rgba(200,200,200,0.35)';c.lineWidth=1;sectorPath(c,F);c.stroke();
 c.fillStyle='rgba(220,220,220,0.8)';for(let d=2;d<F.depth;d+=2){const a=Math.PI/2-F.half;const x=F.apx+Math.cos(a)*d*F.k,y=F.apy+Math.sin(a)*d*F.k;c.fillRect(x+3,y,4,1.2)}
 c.font='600 12px system-ui,sans-serif';c.fillStyle='#9fe3ff';c.fillText(title,F.x0+8,F.y0+16);c.font='11px system-ui,sans-serif';c.fillStyle='#ccc';c.fillText(angle,F.x0+8,F.y0+31);
 // açı göstergesi
 const cx=F.x0+F.w-24,cy=F.y0+22,ang=parseFloat(angle)||0;c.strokeStyle='#888';c.beginPath();c.arc(cx,cy,12,0,TAU);c.stroke();c.strokeStyle='#9fe3ff';c.beginPath();c.moveTo(cx,cy);c.lineTo(cx+12*Math.cos(Math.PI-ang*D2R),cy-12*Math.sin(Math.PI-ang*D2R));c.stroke();
}
function tlab(c,F,txt,lx,d,col){if(!$('tLbl').checked)return;const q=F.T(lx,d);c.font='600 11px system-ui,sans-serif';c.fillStyle=col||'rgba(255,230,140,0.95)';c.fillText(txt,q[0]-c.measureText(txt).width/2,q[1]+4)}
function tbottom(c,F,txt){c.font='11px system-ui,sans-serif';c.fillStyle='#bbb';c.fillText(txt,F.x0+F.w/2-c.measureText(txt).width/2,F.y0+F.h-6)}
function catheterCm(c,F,pts,w){
 // akustik gölge
 c.save();c.fillStyle='rgba(0,0,0,0.5)';c.filter='blur(2px)';
 for(let i=0;i<pts.length-1;i++){const a=F.T(...pts[i]),b=F.T(...pts[i+1]);const ext=p=>{const dx=p[0]-F.apx,dy=p[1]-F.apy,l=Math.hypot(dx,dy)||1;return [p[0]+dx/l*F.R,p[1]+dy/l*F.R]};const ea=ext(a),eb=ext(b);
  c.beginPath();c.moveTo(a[0],a[1]);c.lineTo(b[0],b[1]);c.lineTo(eb[0],eb[1]);c.lineTo(ea[0],ea[1]);c.closePath();c.fill()}
 c.restore();
 lineCm(c,F,pts.map(p=>[p[0],p[1]+0.32]),1.2,'rgba(230,230,230,0.25)');
 lineCm(c,F,pts,w||3,'rgba(245,245,245,0.95)');
}
function bubbles(c,F,where,t,shape){
 S.bub.forEach(b=>{if(b.where!==where)return;const age=t-b.t0;if(age<0||age>b.dur)return;const a=1-age/b.dur;
  b.ps.forEach(p=>{const x=p[0]+Math.sin(t*3+p[2])*0.12+p[3]*age,y=p[1]+Math.cos(t*2.5+p[2])*0.1;const q=shape(x,y);if(!q)return;const s=F.T(q[0],q[1]);c.fillStyle=`rgba(255,255,255,${0.9*a})`;c.fillRect(s[0],s[1],2.2,2.2)})})
}
function addBubbles(where,t){const ps=[];for(let i=0;i<70;i++)ps.push([Math.random()*2-1,Math.random()*2-1,Math.random()*6,(Math.random()-0.5)*0.2]);S.bub=S.bub.filter(b=>t-b.t0<b.dur);S.bub.push({where,t0:t,dur:3.5,ps})}

// --- bikaval ---
function viewBic(c,F,r,t){
 tissueBase(c,F,t);c.save();sectorPath(c,F);c.clip();
 const contact=r.contact&&r.region[0]!=='w'&&r.region!=='aorta';
 const vt=r.v, FBe=FB*Math.sqrt(Math.max(0,1-(r.u/FA)**2));
 const tentAt=lx=>contact?r.tent*Math.pow(Math.max(0,1-Math.abs(lx-vt)/0.95),1.5):0;
 const th=lx=>{const ins=1-sstep(FBe-0.12,FBe+0.12,Math.abs(lx));return 0.1*ins+(lx>0?0.55:0.45)*(1-ins)};
 const beat=0.04*Math.sin(t*TAU*1.2);
 // boşluklar
 cavity(c,F,()=>{c.beginPath();for(let i=0;i<=30;i++){const a=Math.PI+i/30*Math.PI;const q=F.T(3.6*Math.cos(a),2.3+1.25*Math.sin(a)+beat);i?c.lineTo(q[0],q[1]):c.moveTo(q[0],q[1])}const q1=F.T(3.6,3.6),q2=F.T(-3.6,3.6);c.lineTo(q1[0],q1[1]);c.lineTo(q2[0],q2[1]);c.closePath()});
 cavity(c,F,()=>polyCm(c,F,[[-3.0,3.4],[3.0,3.4],[3.6,4.4],[3.6,6.6],[2.0,7.6],[-1.8,7.8],[-3.4,6.9],[-3.4,4.6]]));
 cavity(c,F,()=>polyCm(c,F,[[2.4,3.75],[7.5,3.2],[7.5,5.4],[3.0,6.3]]));
 cavity(c,F,()=>polyCm(c,F,[[-2.6,4.7],[-7.5,5.0],[-7.5,7.3],[-2.5,7.5]]));
 // septum
 const top=[],bot=[];for(let i=0;i<=80;i++){const lx=-3.4+6.8*i/80,tn=tentAt(lx);top.push([lx,3.55-tn+beat*0.5]);bot.push([lx,3.55+th(lx)-tn*(th(lx)<0.2?1:0.85)+beat*0.5])}
 c.fillStyle='rgba(190,190,190,0.88)';polyCm(c,F,top.concat(bot.reverse()));c.fill();
 lineCm(c,F,[[3.4,3.55],[7.5,3.05]],3,'rgba(200,200,200,0.8)');lineCm(c,F,[[-3.4,3.6],[-7.5,4.7]],3,'rgba(200,200,200,0.7)');
 lineCm(c,F,[[-2.5,7.4],[-2.0,7.0+0.1*Math.sin(t*5)],[-1.5,6.6]],1.6,'rgba(220,220,220,0.8)'); // östaki valvi
 // kateter
 const tipD=3.55+th(vt)-tentAt(vt)*(th(vt)<0.2?1:0.85)+0.08;
 let path;
 if(r.inSVC){const sd=lx=>5.0-0.155*(lx-2.8);path=[[-7.5,6.3],[-2.6,6.15],[0.6,5.7],[2.8,5.0],[vt,sd(vt)]]}
 else if(r.region==='ivc'){path=[[-7.5,6.3],[Math.max(vt-1.5,-7.4),6.2],[vt,5.8]]}
 else if(contact){path=catmull([[-7.5,6.3],[-2.6,6.2],[vt-1.5,5.2],[vt-0.3,tipD+0.35],[vt,tipD]],5)}
 else {const tx=vt+0.4,td=r.region[0]==='w'?4.1:4.9;path=catmull([[-7.5,6.3],[-2.6,6.2],[vt-1.2,5.6],[tx,td]],5)}
 catheterCm(c,F,path,3.2);
 const tp=path[path.length-1];
 if(S.needleOut&&S.outcome==='la'){lineCm(c,F,[tp,[tp[0]+0.15,tp[1]-1.1]],1.6,'rgba(255,255,255,0.9)')}
 if(S.needleOut&&S.outcome==='peri'){lineCm(c,F,[tp,[tp[0]+0.4,tp[1]-0.9]],1.6,'rgba(255,255,255,0.9)')}
 if(S.sheathLA){lineCm(c,F,[tp,[tp[0]+0.5,2.4]],4,'rgba(245,245,245,0.95)')}
 if(S.wire){lineCm(c,F,catmull([[tp[0]+0.5,2.4],[tp[0]+1.4,1.6],[3.2,1.4]],5),1.4,'rgba(255,255,255,0.9)')}
 bubbles(c,F,'la',t,(x,y)=>[x*3.0,2.3+y*0.9]);
 bubbles(c,F,'ra',t,(x,y)=>[vt+x*1.4,5.0+y*1.2]);
 c.restore();
 tlab(c,F,'LA',0,2.2);tlab(c,F,'RA',0.3,6.4);tlab(c,F,'SVK',2.9,5.0);tlab(c,F,'İVK',-3.3,6.3);
 if(contact&&r.tent>0.15)tlab(c,F,'çadırlanma',vt+1.5,3.1-r.tent*0.5,'#ffd27a');
 tbottom(c,F,'◀ İnferior (İVK)    ·    Süperior (SVK) ▶');
}
// --- kısa aks ---
function viewSax(c,F,r,t){
 tissueBase(c,F,t);c.save();sectorPath(c,F);c.clip();
 const sU=u=>3.7+0.32*u, nv=[0.305,-0.952];
 const contactSep=r.contact&&r.u<=1.1&&r.region[0]!=='w';
 const vEff=clamp(r.v,-FB*0.99,FB*0.99), FAe=FA*Math.sqrt(Math.max(0,1-(vEff/FB)**2));
 const ut=r.u;
 const tentAt=u=>contactSep?r.tent*Math.pow(Math.max(0,1-Math.abs(u-ut)/0.95),1.5):0;
 const th=u=>{const ins=1-sstep(FAe-0.12,FAe+0.12,Math.abs(u));const fossaHere=Math.abs(r.v)<FB;return fossaHere?0.1*ins+(u>0?0.5:0.45)*(1-ins):(u>0?0.5:0.48)};
 const beat=0.04*Math.sin(t*TAU*1.2);
 cavity(c,F,()=>polyCm(c,F,[[-3.4,sU(-3.4)],[-3.0,1.6],[-2,1.05],[0,0.95+beat],[2,1.15],[3.3,1.8],[3.7,2.7],[3.2,3.15],[2.4,3.28],[1.5,3.5],[1.1,sU(1.1)-0.05]]));
 cavity(c,F,()=>polyCm(c,F,[[-3.4,sU(-3.4)+0.3],[1.0,sU(1.0)+0.3],[1.1,5.3],[0.75,6.15],[-0.6,6.9],[-2.4,7.0],[-3.6,6.0],[-3.9,4.2]]));
 cavity(c,F,()=>polyCm(c,F,[[1.0,7.0],[1.6,6.35],[2.5,6.2],[3.5,5.95],[4.3,5.1],[4.9,4.0],[5.6,4.6],[5.3,6.6],[4.2,8.6],[1.8,8.9],[0.6,8.0]]));
 const ac=[2.45,4.75],arad=1.2;
 cavity(c,F,()=>ellCm(c,F,ac[0],ac[1],arad,arad));
 // aort duvarı ve kuspler
 c.strokeStyle='rgba(225,225,225,0.9)';c.lineWidth=3;ellCm(c,F,ac[0],ac[1],arad+0.05,arad+0.05);c.stroke();
 const sys=(Math.sin(t*TAU*1.2)+1)/2>0.62;
 [260,25,145].forEach(a=>{const q=F.T(ac[0]+arad*Math.cos(a*D2R),ac[1]+arad*Math.sin(a*D2R));const m=F.T(ac[0]+(sys?0.55:0)*Math.cos(a*D2R),ac[1]+(sys?0.55:0)*Math.sin(a*D2R));c.lineWidth=1.8;c.strokeStyle='rgba(235,235,235,0.9)';c.beginPath();c.moveTo(q[0],q[1]);c.lineTo(m[0],m[1]);c.stroke()});
 // septum
 const top=[],bot=[];for(let i=0;i<=80;i++){const u=-3.4+4.5*i/80,tn=tentAt(u),d=sU(u),w=th(u),tr=tn*(w<0.2?1:0.85);top.push([u+nv[0]*tn,d+nv[1]*tn+beat*0.4]);bot.push([u+nv[0]*tr,d+w+nv[1]*tr+beat*0.4])}
 c.fillStyle='rgba(185,185,185,0.85)';polyCm(c,F,top.concat(bot.reverse()));c.fill();
 // triküspit
 const tv=(Math.sin(t*TAU*1.2)+1)/2>0.62?0:0.5;
 lineCm(c,F,[[0.75,6.2],[1.2+tv*0.2,6.9+tv]],1.8,'rgba(225,225,225,0.85)');lineCm(c,F,[[0.45,7.6],[1.0,7.2+tv*0.4]],1.8,'rgba(225,225,225,0.85)');
 // kateter
 let tip;
 if(contactSep){const tr=tentAt(ut)*(th(ut)<0.2?1:0.85);tip=[ut+nv[0]*tr,sU(ut)+th(ut)+nv[1]*tr+0.08]}
 else if(r.contact&&r.u>1.1){const a=(205+clamp((r.u-1.1)/2.3,0,1)*45)*D2R;tip=[ac[0]+(arad+0.18)*Math.cos(a)-0.06*r.tent,ac[1]+(arad+0.18)*Math.sin(a)+0.25-r.tent*0.4]}
 else if(r.inSVC) tip=null;
 else tip=[ut-0.4,sU(ut)+1.4];
 if(tip){catheterCm(c,F,[[tip[0]-0.35,tip[1]+1.0],tip],3.4);c.fillStyle='#fff';const q=F.T(tip[0],tip[1]);c.beginPath();c.arc(q[0],q[1],2.6,0,TAU);c.fill();
  if(S.needleOut&&S.outcome==='la')lineCm(c,F,[tip,[tip[0]+0.35,tip[1]-1.1]],1.6,'rgba(255,255,255,0.9)');
  if(S.needleOut&&S.outcome==='ao')lineCm(c,F,[tip,[ac[0]-0.4,ac[1]-0.2]],1.6,'rgba(255,255,255,0.9)');
  if(S.sheathLA)lineCm(c,F,[tip,[tip[0]+0.5,tip[1]-1.4]],4,'rgba(245,245,245,0.95)');}
 bubbles(c,F,'la',t,(x,y)=>[-0.4+x*2.4,2.1+y*0.75]);
 bubbles(c,F,'ao',t,(x,y)=>{const rr2=Math.hypot(x,y);return rr2<1?[ac[0]+x*1.05,ac[1]+y*1.05]:null});
 bubbles(c,F,'ra',t,(x,y)=>[-1.5+x*1.8,5.2+y*1.0]);
 c.restore();
 tlab(c,F,'LA',-0.6,1.9);tlab(c,F,'RA',-1.9,5.6);tlab(c,F,'Ao',ac[0],ac[1]+0.1);tlab(c,F,'RVOT',3.3,7.5);tlab(c,F,'NCC',ac[0]-0.95,ac[1]-0.15,'rgba(255,230,140,0.75)');
 if(contactSep&&r.tent>0.15)tlab(c,F,'çadırlanma',ut-1.3,sU(ut)-r.tent*0.6-0.2,'#ffd27a');
 if(r.inSVC)tlab(c,F,'(kateter SVK\'da – bu kesitte yok)',-1.2,7.6,'#bbb');
 tbottom(c,F,'◀ Posterior    ·    Anterior (aorta) ▶');
}
// --- 4 boşluk ---
function view4c(c,F,r,t){
 tissueBase(c,F,t);c.save();sectorPath(c,F);c.clip();
 const open=(Math.sin(t*TAU*1.2)+1)/2<0.62;
 const contact=r.contact&&r.region[0]!=='w'&&r.region!=='aorta';
 const yT=clamp(7.0-r.height,2.2,6.6);
 const tentAt=y=>contact?r.tent*Math.pow(Math.max(0,1-Math.abs(y-yT)/0.95),1.5):0;
 const iasX=y=>-0.75+0.2*(y-2.0)/4.8;
 cavity(c,F,()=>polyCm(c,F,[[-0.7,2.2],[0.2,1.55],[1.6,1.6],[2.8,2.4],[3.35,4.2],[3.25,6.55],[-0.45,6.95]]));
 cavity(c,F,()=>polyCm(c,F,[[-0.9,2.6],[-2.4,2.7],[-3.9,4.0],[-4.0,6.0],[-3.6,6.85],[-0.9,7.0]]));
 cavity(c,F,()=>polyCm(c,F,[[-0.3,7.2],[3.3,6.8],[3.9,9.0],[3.2,11.4],[1.6,12.4],[0.3,11.6],[-0.25,9.5]]));
 cavity(c,F,()=>polyCm(c,F,[[-0.85,7.3],[-3.6,7.0],[-4.3,9.0],[-3.0,11.0],[-1.2,11.4],[-0.75,9.5]]));
 // IAS
 const L=[],R=[];for(let i=0;i<=60;i++){const y=2.0+4.95*i/60,x=iasX(y),tn=tentAt(y);L.push([x-0.12+tn,y]);R.push([x+0.05+tn,y])}
 c.fillStyle='rgba(215,215,215,0.95)';polyCm(c,F,L.concat(R.reverse()));c.fill();
 // kapaklar
 const aml=open?[0.5,9.1]:[1.35,7.55],pml=open?[2.7,8.7]:[1.45,7.6];
 lineCm(c,F,[[-0.4,7.05],aml],2.2,'rgba(235,235,235,0.9)');lineCm(c,F,[[3.25,6.65],pml],2.2,'rgba(235,235,235,0.9)');
 lineCm(c,F,[[-0.9,7.1],open?[-1.6,8.7]:[-2.2,7.5]],2,'rgba(225,225,225,0.85)');lineCm(c,F,[[-3.6,6.9],open?[-3.2,8.5]:[-2.3,7.5]],2,'rgba(225,225,225,0.85)');
 // kateter
 if(contact){const tip=[iasX(yT)-0.15+tentAt(yT),yT];catheterCm(c,F,catmull([[-3.8,7.6],[-2.6,6.4],[-1.4,yT+0.5],tip],5),3.2);
  // ölçüm
  const pp=PROCS[S.proc];const ok=!pp.h||(r.height>=pp.h[0]&&r.height<=pp.h[1]);
  c.setLineDash([5,4]);lineCm(c,F,[[-1.4,7.06],[4.0,6.6]],1.2,'rgba(255,220,120,0.8)');c.setLineDash([]);
  const mx=tip[0],my=6.98-0.085*(tip[0]+0.45);
  lineCm(c,F,[tip,[mx,my]],1.6,ok?'#5df08f':'#ffb347');
  const q=F.T(mx+0.25,(tip[1]+my)/2);c.font='700 13px system-ui,sans-serif';c.fillStyle=ok?'#5df08f':'#ffb347';c.fillText(r.height.toFixed(1).replace('.',',')+' cm',q[0],q[1]);
  if(S.needleOut&&S.outcome==='la')lineCm(c,F,[tip,[tip[0]+1.0,tip[1]-0.1]],1.6,'rgba(255,255,255,0.9)');
  if(S.sheathLA)lineCm(c,F,[tip,[tip[0]+1.4,tip[1]+0.2]],4,'rgba(245,245,245,0.95)');
 } else if(!r.inSVC){catheterCm(c,F,[[-3.8,7.6],[-2.4,5.4]],3)}
 bubbles(c,F,'la',t,(x,y)=>[1.3+x*1.6,4.0+y*1.6]);
 bubbles(c,F,'ra',t,(x,y)=>[-2.4+x*1.1,4.8+y*1.3]);
 c.restore();
 tlab(c,F,'LA',1.5,3.4);tlab(c,F,'RA',-2.5,4.6);tlab(c,F,'LV',1.8,10.4);tlab(c,F,'RV',-2.4,9.6);tlab(c,F,'MV',3.9,6.4);
 tbottom(c,F,contact?'Yükseklik: çadırlanma → mitral anülüs (koaptasyon) düzlemi':'Çadırlanma yok – septuma temas sağlayın');
}
function drawTEE(t,r){
 const c=tctx,W=560,H=440;c.save();c.fillStyle='#000';c.fillRect(0,0,W,H);
 if(S.tee==='xp'){const hh=Math.min(H,(W/4-6)/Math.sin(33*D2R)+52),yo=(H-hh)/2;const F1=teeFrame(0,yo,W/2,hh,8.6,33),F2=teeFrame(W/2,yo,W/2,hh,9.2,33);viewBic(c,F1,r,t);teeFinish(c,F1,t,'Bikaval','100°');viewSax(c,F2,r,t);teeFinish(c,F2,t,'Kısa aks (AV)','45°');
  c.strokeStyle='#333';c.beginPath();c.moveTo(W/2,0);c.lineTo(W/2,H);c.stroke();c.font='600 11px system-ui';c.fillStyle='#9fe3ff';c.fillText('X-plane (eş zamanlı iki düzlem)',W/2-80,H-8)}
 else if(S.tee==='bic'){const F=teeFrame(0,0,W,H,10,45);viewBic(c,F,r,t);teeFinish(c,F,t,'ME bikaval','100°')}
 else if(S.tee==='sax'){const F=teeFrame(0,0,W,H,9.5,45);viewSax(c,F,r,t);teeFinish(c,F,t,'ME aort kapak kısa aks','45°')}
 else {const F=teeFrame(0,0,W,H,13,45);view4c(c,F,r,t);teeFinish(c,F,t,'ME 4 boşluk','0°')}
 c.restore();
}

// ---------- fossa haritası ----------
function drawMap(r){
 const c=mctx,W=360,H=330,cx=W/2,cy=H/2+4,k=38;const T=(u,v)=>[cx+u*k,cy-v*k];
 const css=getComputedStyle(document.documentElement);const tx=css.getPropertyValue('--tx').trim(),mu=css.getPropertyValue('--mu').trim(),card=css.getPropertyValue('--card').trim();
 const th=document.documentElement.dataset.theme;const dark=th?th==='dark':matchMedia('(prefers-color-scheme:dark)').matches;
 c.fillStyle=card;c.fillRect(0,0,W,H);
 c.fillStyle=dark?'#2a2530':'#f2e9e4';c.fillRect(6,6,W-12,H-12);
 const E=(u,v,a,b)=>{const q=T(u,v);c.beginPath();c.ellipse(q[0],q[1],a*k,b*k,0,0,TAU)};
 // komşu yapılar
 c.fillStyle=dark?'rgba(120,120,130,0.35)':'rgba(90,90,100,0.18)';E(SVC_U,3.75,1.0,0.75);c.fill();E(IVC_U,-3.9,1.25,0.8);c.fill();
 c.fillStyle='rgba(192,57,43,0.25)';E(AO.u,AO.v,AO.r,AO.r);c.fill();c.strokeStyle='rgba(192,57,43,0.7)';c.lineWidth=1.5;c.stroke();
 c.fillStyle=dark?'rgba(120,120,130,0.45)':'rgba(90,90,100,0.28)';E(1.25,-2.95,0.42,0.3);c.fill();
 c.strokeStyle=dark?'rgba(200,200,210,0.5)':'rgba(80,80,90,0.5)';c.lineWidth=2;c.beginPath();const tq=T(3.4,-1.0);c.arc(tq[0],tq[1],2.4*k,Math.PI*0.62,Math.PI*1.02);c.stroke();
 // septum
 c.fillStyle=dark?'#6b5640':'#e3c9a0';E(0,0,SA,SB);c.fill();c.strokeStyle=dark?'#9c8060':'#b8956a';c.lineWidth=1;c.stroke();
 c.fillStyle=dark?'#8a7a68':'#f8efe2';E(0,0,FA,FB);c.fill();c.strokeStyle=dark?'#c8b090':'#9c7b50';c.lineWidth=1.6;c.setLineDash([4,3]);c.stroke();c.setLineDash([]);
 c.strokeStyle=dark?'rgba(255,255,255,0.25)':'rgba(0,0,0,0.2)';c.lineWidth=1;c.beginPath();let a=T(-FA,0),b=T(FA,0);c.moveTo(a[0],a[1]);c.lineTo(b[0],b[1]);a=T(0,-FB);b=T(0,FB);c.moveTo(a[0],a[1]);c.lineTo(b[0],b[1]);c.stroke();
 c.font='10px system-ui';c.fillStyle=mu;[['SP',-0.45,0.55],['SA',0.45,0.55],['İP',-0.45,-0.55],['İA',0.45,-0.55]].forEach(([s,u,v])=>{const q=T(u,v);c.fillText(s,q[0]-6,q[1]+4)});
 // yükseklik eğrileri
 if($('mIso').checked){c.save();E(0,0,SA,SB);c.clip();[3.0,3.5,4.0,4.5,5.0].forEach(Hh=>{c.beginPath();for(let i=0;i<=20;i++){const u=-2.4+4.8*i/20,v=(Hh-3.7+0.35*u)/0.9;const q=T(u,v);i?c.lineTo(q[0],q[1]):c.moveTo(q[0],q[1])}
  c.strokeStyle=dark?'rgba(140,190,255,0.45)':'rgba(30,90,180,0.35)';c.lineWidth=1;c.setLineDash([2,3]);c.stroke();c.setLineDash([]);const q=T(-2.0,(Hh-3.7-0.7)/0.9);c.font='9.5px system-ui';c.fillStyle=dark?'#9cc4ff':'#2a5ca8';c.fillText(Hh.toFixed(1).replace('.',',')+' cm',q[0]-4,q[1]-2)});c.restore()}
 // hedef
 const pp=PROCS[S.proc];
 if(pp.t&&$('mTgt').checked){c.fillStyle='rgba(30,160,90,0.28)';E(pp.t.u,pp.t.v,pp.t.ru,pp.t.rv);c.fill();c.strokeStyle='rgba(30,160,90,0.95)';c.lineWidth=2;c.stroke();
  const q=T(pp.t.u,pp.t.v+pp.t.rv);c.font='600 10.5px system-ui';c.fillStyle=dark?'#5fe39b':'#137a45';c.fillText('hedef',q[0]-14,q[1]-3)}
 // etiketler
 c.font='600 11px system-ui';c.fillStyle=tx;
 const L=(s,u,v)=>{const q=T(u,v);c.fillText(s,q[0]-c.measureText(s).width/2,q[1]+4)};
 L('SVK',SVC_U,3.75);L('İVK',IVC_U,-3.9);c.fillStyle=dark?'#ff8a7d':'#a5281b';L('Aort kökü',AO.u+0.15,AO.v+0.15);c.font='10px system-ui';L('(NCC)',AO.u+0.15,AO.v-0.2);c.fillStyle=tx;L('KS',1.25,-2.95);c.fillStyle=mu;L('triküspit',3.15,-2.3);L('limbus',-1.55,1.85);
 c.font='600 11px system-ui';c.fillStyle=mu;c.fillText('Süperior ▲',W-84,22);c.fillText('▼ İnferior',W-84,H-12);c.save();c.translate(16,cy+40);c.rotate(-Math.PI/2);c.fillText('◀ Posterior',0,0);c.restore();c.save();c.translate(W-10,cy-40);c.rotate(Math.PI/2);c.fillText('Anterior ▶',0,0);c.restore();
 // işaret
 if(S.mark){const q=T(S.mark.u,S.mark.v);c.strokeStyle=S.mark.col;c.lineWidth=3;c.beginPath();c.moveTo(q[0]-6,q[1]-6);c.lineTo(q[0]+6,q[1]+6);c.moveTo(q[0]+6,q[1]-6);c.lineTo(q[0]-6,q[1]+6);c.stroke()}
 // uç
 if(r.inSVC){c.font='600 11px system-ui';c.fillStyle=dark?'#8ab8ff':'#2463b0';c.fillText('uç SVK içinde ▲',cx-44,40)}
 else if(r.region==='ivc'){c.font='600 11px system-ui';c.fillStyle=dark?'#8ab8ff':'#2463b0';c.fillText('uç İVK girişinde ▼',cx-48,H-24)}
 else{const vv=clamp(r.v,-4.1,4.1),uu=clamp(r.u,-4.4,4.4);const q=T(uu,vv);
  const col=!r.contact?'#888':(r.region==='fossa'?'#2463b0':(r.region==='aorta'||r.region==='ant'?'#c0392b':'#d08000'));
  if(r.contact&&S.push>0.02){c.strokeStyle=col;c.lineWidth=1.5;c.beginPath();c.arc(q[0],q[1],7+S.push*14,0,TAU);c.stroke()}
  c.fillStyle=r.contact?col:'transparent';c.strokeStyle=col;c.lineWidth=2;c.beginPath();c.arc(q[0],q[1],6,0,TAU);r.contact?c.fill():c.stroke();
  if(!r.contact){c.font='10px system-ui';c.fillStyle=mu;c.fillText('temas yok',q[0]+9,q[1]+4)}
  if(r.contact&&!S.crossed){c.strokeStyle=dark?'rgba(255,255,255,0.5)':'rgba(0,0,0,0.4)';c.lineWidth=1.2;c.beginPath();c.moveTo(q[0]-10,q[1]+14);c.lineTo(q[0]-26,q[1]+14);c.stroke();c.font='9.5px system-ui';c.fillStyle=mu;c.fillText('↻',q[0]-36,q[1]+18)}}
}
// ---------- kadran ----------
function drawDial(){
 const c=dctx,W=150,cx=75,cy=75,R=58;const css=getComputedStyle(document.documentElement);const tx=css.getPropertyValue('--tx').trim(),mu=css.getPropertyValue('--mu').trim(),sh=css.getPropertyValue('--sh').trim(),bd=css.getPropertyValue('--bd').trim();
 c.clearRect(0,0,W,W);c.fillStyle=sh;c.beginPath();c.arc(cx,cy,R+8,0,TAU);c.fill();c.strokeStyle=bd;c.stroke();
 const arc=(h1,h2,col,w)=>{c.strokeStyle=col;c.lineWidth=w;c.beginPath();c.arc(cx,cy,R,(h1*30-90)*D2R,(h2*30-90)*D2R);c.stroke()};
 arc(2.6,6.7,'rgba(36,99,176,0.25)',8);arc(4,5,'rgba(30,142,90,0.75)',8);
 c.font='600 10px system-ui';c.fillStyle=mu;for(let i=1;i<=12;i++){const a=(i*30-90)*D2R;const s=String(i);c.fillText(s,cx+(R-14)*Math.cos(a)-c.measureText(s).width/2,cy+(R-14)*Math.sin(a)+4)}
 c.font='700 9.5px system-ui';c.fillStyle=tx;c.fillText('ANT',cx-9,10);c.fillText('POST',cx-12,W-2);c.fillText('SOL',W-19,cy+3);c.fillText('SAĞ',0,cy+3);
 const a=(S.rot*30-90)*D2R;c.strokeStyle='#c0392b';c.lineWidth=4;c.lineCap='round';c.beginPath();c.moveTo(cx,cy);c.lineTo(cx+(R-4)*Math.cos(a),cy+(R-4)*Math.sin(a));c.stroke();
 c.fillStyle='#c0392b';c.beginPath();c.arc(cx,cy,5,0,TAU);c.fill();
}
// ---------- basınç ----------
const PBUF=[];let lastPS=0;
const gk=(ph,c0,w)=>{let d=Math.abs(ph-c0);d=Math.min(d,1-d);return Math.exp(-((d/w)**2))};
function pressureNow(t){
 const ph=(t*1.2)%1;let src='ra';
 if(S.needleOut&&S.outcome==='la'||S.sheathLA)src='la';else if(S.needleOut&&S.outcome==='ao')src='ao';else if(S.needleOut&&S.outcome==='peri')src='peri';
 let p;
 if(src==='ra')p=6+3.5*gk(ph,0.08,0.05)+2.5*gk(ph,0.48,0.07)-1.5*gk(ph,0.3,0.06);
 else if(src==='la'){const m=PROCS[S.proc].la;if(m==='mr')p=13+4*gk(ph,0.1,0.05)+20*gk(ph,0.43,0.09);else if(m==='ms')p=24+7*gk(ph,0.08,0.05)+6*gk(ph,0.47,0.08);else p=10+4*gk(ph,0.1,0.05)+6*gk(ph,0.46,0.08)}
 else if(src==='ao'){const s=ph<0.12?0:(ph<0.4?Math.sin((ph-0.12)/0.28*Math.PI*0.75):0);p=72+50*s+(ph>0.4?12*Math.exp(-(ph-0.4)*3):0)-((ph>0.38&&ph<0.42)?4:0)}
 else p=1.5+0.5*Math.sin(ph*TAU);
 return {p:p+(Math.random()-0.5)*0.4,src};
}
function drawPress(t){
 const c=pctx,W=360,H=96;const {p,src}=pressureNow(t);PBUF.push({p,src});while(PBUF.length>220)PBUF.shift();
 c.fillStyle='#0b1015';c.fillRect(0,0,W,H);const max=src==='ao'?150:40;
 c.strokeStyle='rgba(255,255,255,0.08)';c.lineWidth=1;for(let y=0;y<=max;y+=(max>50?25:10)){const yy=H-8-(y/max)*(H-16);c.beginPath();c.moveTo(30,yy);c.lineTo(W,yy);c.stroke();c.fillStyle='#667';c.font='9px system-ui';c.fillText(y,4,yy+3)}
 const col={ra:'#6fb6ff',la:'#ffd24a',ao:'#ff5c5c',peri:'#aaa'}[src];
 c.strokeStyle=col;c.lineWidth=1.8;c.beginPath();PBUF.forEach((q,i)=>{const x=30+i*(W-32)/220,y=H-8-clamp(q.p/max,0,1.05)*(H-16);i?c.lineTo(x,y):c.moveTo(x,y)});c.stroke();
 const nm={ra:'RA (iğne dilatör içinde)',la:'LA basıncı',ao:'AORTİK basınç!',peri:'Sönük / perikardiyal?'}[src];
 c.fillStyle=col;c.font='600 11px system-ui';c.fillText(nm,36,13);
}

// ---------- değerlendirme ----------
function liveHint(r){
 const pp=PROCS[S.proc];
 if(S.outcome==='ao')return ['er','İğneyi geri çekin (↩) ve rotasyonu posteriora (↻) alarak fossaya dönün.'];
 if(S.outcome==='peri')return ['er','İğneyi geri çekin (↩), TEE ile perikardı kontrol edin ve fossaya dönün.'];
 if(S.outcome==='free')return ['wa','İğne RA içinde serbest. Septuma temas olmadan iğneyi ilerletmeyin, çünkü RA serbest duvarı veya RAA perforasyonu riski vardır. İğneyi geri çekin.'];
 if(S.wire)return ['ok','Tel sol üst PV\'de, kılıf LA\'da. Prosedüre özgü kılıf değişimine hazırsınız. Heparin (hedef ACT) unutmayın.'];
 if(S.sheathLA)return ['ok','Dilatör ve kılıf LA\'da. Şimdi teli sol üst pulmoner vene yerleştirin.'];
 if(S.crossed)return ['ok','LA\'ya geçildi: LA basınç trasesi, kontrast ve TEE\'de LA\'da köpük doğrulandı. Dilatör ve kılıfı iğne üzerinden ilerletin.'];
 if(r.inSVC){const ok=S.rot>=4&&S.rot<=5;return ok?['ok','Gösterge saat '+clockTxt(S.rot)+'. LAO veya AP floroskopi altında yavaşça <b>geri çekin</b> (⬇) ve iki sıçramayı izleyin.']:['wa','Geri çekmeden önce iğne göstergesini <b>saat 4–5</b> yönüne çevirin. Şu an saat '+clockTxt(S.rot)+'.']}
 if(r.region==='ivc')return ['wa','İVK girişine indiniz, septum geride kaldı. Sistemi tekrar SVK\'ya ilerletip yeniden geri çekin (pratikte tel ile SVK\'ya dönülür).'];
 if(r.region==='free'){return ['wa','Uç septuma bakmıyor (saat '+clockTxt(S.rot)+'). '+(r.dn<0.3&&Math.sin(S.rot*30*D2R)<0?'Uç RA serbest duvarına bakıyor. ':'')+'Saat 4–5 yönüne çevirin.']}
 const tipsU=du=>du<0?'saat yönünde çevirin (↻ posterior)':'saat yönünün tersine çevirin (↺ anterior)';
 switch(r.region){
  case 'sup':return ['wa','Uç <b>fossanın üzerinde</b>, kalın süperior limbusta. Biraz daha geri çekin ve fossaya düşüşü (2. sıçrama) bekleyin. Bu bölgeden ponksiyon ekstrakardiyak olabilir.'];
  case 'inf':return ['wa','Uç <b>fossanın altında</b>, inferior limbusta. Kılıfı hafifçe ilerletin (⬆).'];
  case 'ant':return ['er','Çok anterior, <b>aort köküne yakın</b>. Saat yönünde (↻) posteriora çevirin. RAO\'da uç pigtail\'in posterioruna geçmeli.'];
  case 'aorta':return ['er','Uç aort kökü (NCC) komşuluğunda. Kısa aksta çadırlanma aortaya bitişik. Ponksiyon <b>yapmayın</b>, saat yönünde çevirin.'];
  case 'post':return ['wa','Çok posterior: posterior katlantı ve ekstrakardiyak alan riski var. Saat yönünün tersine (↺) hafifçe çevirin.'];
  case 'wsup':return ['wa','SVK–RA bileşkesi seviyesindesiniz. Geri çekmeye devam edin.'];
  case 'winf':return ['wa','İVK / KS ağzı bölgesi: çok inferior. Kılıfı ilerletin.'];
  case 'want':return ['er','Anterior RA duvarı ve triküspit yönü. Saat yönünde (↻) çevirin.'];
  case 'wpost':return ['er','Posterior RA serbest duvarı: perforasyon riski. Saat yönünün tersine (↺) çevirin.'];
 }
 // fossa içinde
 if(!pp.t)return ['ok','Fossa ovalis içinde ('+quadName(r.u,r.v)+'). Çadırlanma oluşturup ponksiyon yapabilirsiniz.'];
 const du=pp.t.u-r.u,dv=pp.t.v-r.v,adv=[];
 if(Math.abs(dv)>0.22)adv.push(dv>0?'biraz <b>ilerletin</b> (süperior, ⬆)':'biraz <b>geri çekin</b> (inferior, ⬇)');
 if(Math.abs(du)>0.22)adv.push(tipsU(du));
 if(pp.h&&(r.height<pp.h[0]||r.height>pp.h[1]))adv.push('yükseklik '+r.height.toFixed(1).replace('.',',')+' cm, hedef '+pp.h[0].toFixed(1).replace('.',',')+'–'+pp.h[1].toFixed(1).replace('.',',')+' cm (4 boşlukta ölçün)');
 const inT=((r.u-pp.t.u)/pp.t.ru)**2+((r.v-pp.t.v)/pp.t.rv)**2<=1;
 if(inT&&adv.length===0)return ['ok','<b>Hedef bölgedesiniz</b> ('+quadName(r.u,r.v)+'). TEE\'de doğrulayın, '+(S.push<0.45?'septuma ileri baskı ile <b>çadırlanma</b> oluşturun':'çadırlanma yeterli, <b>iğneyi ilerletin</b>')+'.'];
 return [inT?'ok':'wa','Fossa içinde ('+quadName(r.u,r.v)+'). Hedef: '+pp.kisa+'. Öneri: '+(adv.join('; ')||'konum kabul edilebilir')+'.'];
}
function teeHintTxt(r){
 if(!r.contact||r.region[0]==='w')return '';
 const si=r.v>0.3?'SVK tarafında (süperior)':(r.v<-0.3?'İVK tarafında (inferior)':'ortada (SI)');
 const ap=r.u>0.6?'aortaya yakın (anterior)':(r.u<-0.25?'aortadan uzak (posterior)':'orta (AP)');
 if(S.tee==='bic')return 'Bikaval: çadırlanma '+si+'.';
 if(S.tee==='sax')return 'Kısa aks: çadırlanma '+ap+'.';
 if(S.tee==='4c')return 'Yükseklik: '+r.height.toFixed(1).replace('.',',')+' cm';
 return 'Bikaval: '+si+' · Kısa aks: '+ap;
}
function setTxt(id,v){const e=$(id);if(e.textContent!==v)e.textContent=v}
function setDis(id,v){const e=$(id);if(e.disabled!==v)e.disabled=v}
let lastKV='',lastHint='',lastAlert='';
function updateStatus(r){
 const pp=PROCS[S.proc];
 const reg=r.region==='fossa'?'Fossa ovalis – '+quadName(r.u,r.v):REG[r.region];
 const rows=[['Uç konumu','<b>'+reg+'</b>'],['İğne göstergesi','<b>saat '+clockTxt(S.rot)+'</b>'],
  ['Çadırlanma',r.contact&&r.tent>0.15?'<b>var</b> ('+(r.tent*10).toFixed(0)+' mm)':'yok'],
  ['MV anülüsüne yükseklik',r.contact?'<b>'+r.height.toFixed(1).replace('.',',')+' cm</b>':'–'],
  ['Aort köküne mesafe',r.contact?'<b>'+Math.max(0,r.dA).toFixed(1).replace('.',',')+' cm</b>'+(r.dA<0.6?' ⚠':''):'–'],
  ['Hedef',pp.kisa]];
 if(r.contact&&S.carm<0){rows.push(['RAO işareti',r.u<AO.u-1.4?'uç pigtail\'in posteriorunda ✓':'uç pigtail\'e çok yakın ⚠'])}
 const kvh=rows.map(x=>'<span>'+x[0]+'</span><span>'+x[1]+'</span>').join('');if(kvh!==lastKV){$('kv').innerHTML=kvh;lastKV=kvh}
 const [cls,txt]=liveHint(r);if(cls+txt!==lastHint){const h=$('hint');h.className='hint '+cls;h.innerHTML=txt;lastHint=cls+txt}
 setTxt('teeHint',teeHintTxt(r));
 setTxt('rotTxt',clockTxt(S.rot));
 $('hTxt').textContent=r.inSVC?'SVK':(r.region==='ivc'?'İVK':(r.v>0?'+':'')+r.v.toFixed(1).replace('.',',')+' cm');
 $('pTxt').textContent=Math.round(S.push*100)+'%';
 const ak=S.alert?S.alert.join('|'):'';if(ak!==lastAlert){const al=$('alert');if(S.alert){al.className='alert '+S.alert[0];al.innerHTML=S.alert[1]}else al.className='alert';lastAlert=ak}
 const lock=S.needleOut||S.crossed;['hS','pS'].forEach(id=>setDis(id,lock));['up','dn','cw','ccw'].forEach(id=>$(id).classList.toggle('dim',lock));
 setTxt('needle',S.needleOut&&!S.crossed?'↩ İğneyi geri çek':'🪡 İğneyi ilerlet');{const nb=$('needle'),rt=S.needleOut&&!S.crossed;if(nb.classList.contains('retract')!==rt){nb.classList.toggle('retract',rt);nb.classList.toggle('pri',!rt)}}
 {const ln=$('lockNote'),cls=S.crossed?'lock on okk':(S.needleOut?'lock on':'lock'),tx=S.crossed?'✓ LA\'ya geçildi, kateter sabit. Yeni deneme: ↺ Baştan başla.':(S.needleOut?'🔒 İğne dışarıda, kateter kilitli. Hareket için önce "↩ İğneyi geri çek" (N).':'');if(ln.className!==cls)ln.className=cls;if(ln.textContent!==tx)ln.textContent=tx}setDis('needle',S.crossed);
 setDis('dil',!(S.crossed&&!S.sheathLA));setDis('wire',!(S.sheathLA&&!S.wire));
 setTxt('postNote',S.wire?'Transseptal erişim tamamlandı.':(S.sheathLA?'Sıradaki adım: teli sol üst PV\'ye yerleştirin.':(S.crossed?'LA\'ya geçildi, dilatör ve kılıfı ilerletebilirsiniz.':'Bu iki adım, iğne fossadan LA\'ya geçtikten sonra açılır.')));
 if(document.activeElement!==$('hS')&&+$('hS').value!==S.h)$('hS').value=S.h;if(document.activeElement!==$('pS')&&+$('pS').value!==Math.round(S.push*100))$('pS').value=Math.round(S.push*100);
}

// ---------- adımlar ----------
const STEPS=[
 {id:'svc',t:'Sistem SVK\'da',d:'Femoral venden J-tel SVK\'ya, SL-1 (veya Mullins) kılıf + dilatör tel üzerinden SVK\'ya ilerletildi. Tel çekildi, Brockenbrough iğnesi dilatör içine ucu dilatör ucunun 1–2 cm gerisinde kalacak şekilde yerleştirildi ve yıkandı.',c:()=>true},
 {id:'rot',t:'İğne göstergesini saat 4–5\'e çevir',d:'Ayak ucundan bakıldığında gösterge (iğne flanşı) saat 4–5 yönünde, yani hastanın sol-posterioruna bakmalı. Bu adımı SVK içindeyken yapın.',c:r=>S.rot>=4&&S.rot<=5.25},
 {id:'j1',t:'Geri çek: 1. sıçrama (SVK → RA)',d:'LAO (veya AP) floroskopide sistemi yavaşça geri çekin. Uç SVK–RA bileşkesinden RA\'ya geçerken medial bir sıçrama yapar.',c:r=>!r.inSVC&&r.contact},
 {id:'j2',t:'2. sıçrama: fossaya düşüş',d:'Geri çekmeye devam edin. Uç kalın süperior limbusun altından ince fossa ovalise "düşer". LAO\'da uç sola (LA\'ya) doğru küçük bir sıçrama yapar.',c:r=>r.region==='fossa'},
 {id:'bic',t:'TEE bikaval: süperior–inferior ayar',d:'Bikaval (≈100°) veya X-plane görüntüde çadırlanmanın SVK–İVK eksenindeki yerini değerlendirin. İlerletme ve geri çekme ile ayarlayın.',c:r=>(S.tee==='bic'||S.tee==='xp')&&r.region==='fossa'&&(!PROCS[S.proc].t||Math.abs(PROCS[S.proc].t.v-r.v)<PROCS[S.proc].t.rv)},
 {id:'sax',t:'TEE kısa aks: anterior–posterior ayar',d:'Kısa aks (≈45°) görüntüde çadırlanmanın aortaya uzaklığını değerlendirin. Rotasyonla ayarlayın: saat yönü posterior, tersi anterior.',c:r=>(S.tee==='sax'||S.tee==='xp')&&r.region==='fossa'&&(!PROCS[S.proc].t||Math.abs(PROCS[S.proc].t.u-r.u)<PROCS[S.proc].t.ru)},
 {id:'h4c',t:'4 boşluk: yüksekliği ölç',d:'ME 4 boşlukta (≈0°) çadırlanma noktası ile mitral anülüs (koaptasyon) düzlemi arasındaki mesafeyi ölçün.',c:r=>S.tee==='4c'&&r.region==='fossa'&&PROCS[S.proc].h&&r.height>=PROCS[S.proc].h[0]&&r.height<=PROCS[S.proc].h[1],only:p=>!!PROCS[p].h},
 {id:'tent',t:'Çadırlanma oluştur',d:'"Septuma ileri baskı" kaydırıcısını en az %45\'e getirin (veya <kbd>+</kbd> tuşu). Uç fossa içinde olmalı. TEE\'de belirgin çadırlanma görün. Floroskopide kontrast septal boyanma verir.',c:r=>r.region==='fossa'&&S.push>=0.45},
 {id:'cross',t:'İğneyi ilerlet ve doğrula',d:'"🪡 İğneyi ilerlet" düğmesine basın (veya <kbd>N</kbd>). LA basınç trasesi, kontrastın LA\'yı doldurması ve TEE\'de LA\'da köpük ile doğrulayın.',c:r=>S.crossed},
 {id:'sheath',t:'Dilatör–kılıf LA\'ya, tel sol üst PV\'ye',d:'Önce dilatör, sonra kılıf iğne üzerinden LA\'ya ilerletilir. İğne ve dilatör çekilir, tel sol üst PV\'ye yerleştirilir ve heparin verilir.',c:r=>S.wire}
];
let stepsHTML='';
function updateSteps(r){
 const list=STEPS.filter(s=>!s.only||s.only(S.proc));let cur=-1;
 list.forEach((s,i)=>{if(!S.done[s.id]&&s.c(r)&&(i===0||S.done[list[i-1].id]))S.done[s.id]=true});
 // ileri adımlar tamamlandıysa öncekileri de say
 for(let i=list.length-1;i>=0;i--){if(S.done[list[i].id]){for(let j=0;j<i;j++)S.done[list[j].id]=true;break}}
 for(let i=0;i<list.length;i++){if(!S.done[list[i].id]){cur=i;break}}
 const h=list.map((s,i)=>'<li class="'+(S.done[s.id]?'done':(i===cur?'cur':''))+'">'+s.t+'<div class="d">'+s.d+'</div></li>').join('');
 if(h!==stepsHTML){$('steps').innerHTML=h;stepsHTML=h}
}

// ---------- eylemler ----------
function evaluate(r){
 const pp=PROCS[S.proc];const items=[];let score=100;
 items.push('Ponksiyon yeri: <b>fossa ovalis – '+quadName(r.u,r.v)+'</b>, MV anülüsüne yükseklik <b>'+r.height.toFixed(1).replace('.',',')+' cm</b>, aort köküne <b>'+Math.max(0,r.dA).toFixed(1).replace('.',',')+' cm</b>.');
 if(pp.t){const dz=Math.hypot((r.u-pp.t.u)/pp.t.ru,(r.v-pp.t.v)/pp.t.rv);
  if(dz<=1)items.push('✅ Hedef kadranda ('+pp.kisa+').');
  else{score-=Math.min(45,(dz-1)*35+10);const dv=pp.t.v-r.v,du=pp.t.u-r.u;const w=[];if(Math.abs(dv)>0.25)w.push(dv>0?'daha süperior':'daha inferior');if(Math.abs(du)>0.25)w.push(du>0?'daha anterior':'daha posterior');items.push('⚠️ Hedefin dışında. İdeal yer '+w.join(' ve ')+' olmalıydı.')}}
 if(pp.h){if(r.height<pp.h[0]){score-=Math.min(35,(pp.h[0]-r.height)*45);items.push('⚠️ Yükseklik düşük (hedef '+pp.h[0].toFixed(1).replace('.',',')+'–'+pp.h[1].toFixed(1).replace('.',',')+' cm). Sistemi manevra ettirecek alan kısıtlı olabilir.')}
  else if(r.height>pp.h[1]){score-=Math.min(35,(r.height-pp.h[1])*45);items.push('⚠️ Yükseklik fazla. Sistemin mitral düzleme inişi ve koaksiyel hizalanması zorlaşabilir.')}
  else items.push('✅ Yükseklik uygun.')}
 if(r.dA<0.6){score-=12;items.push('⚠️ Aort köküne çok yakın bir ponksiyon.')}
 score-=S.comp*15+Math.max(0,S.attempts-1)*4;score=Math.round(clamp(score,0,100));
 if(S.comp)items.push('❌ '+S.comp+' komplikasyonlu girişim (aortik / ekstrakardiyak iğne geçişi).');
 S.result={score,items};S.mark={u:r.u,v:r.v,col:score>=80?'#1e8e5a':(score>=55?'#d08000':'#c0392b')};
 renderResult();
}
function renderResult(){
 const el=$('result');
 if(!S.result){el.innerHTML='<span class="small">Henüz ponksiyon yapılmadı. Girişim: '+S.attempts+(S.comp?' · Komplikasyon: '+S.comp:'')+'</span>';return}
 const sc=S.result.score,col=sc>=80?'var(--ok)':(sc>=55?'var(--wa)':'var(--er)');
 el.innerHTML='<div class="score" style="color:'+col+'">'+sc+'<span class="small"> / 100</span></div><div class="small">'+PROCS[S.proc].ad+' · Girişim: '+S.attempts+'</div><ul style="margin:6px 0;padding-left:18px">'+S.result.items.map(x=>'<li>'+x+'</li>').join('')+'</ul>';
}
function doNeedle(){
 const t=performance.now()/1000;const r=tipState();
 if(S.needleOut&&!S.crossed){S.needleOut=false;S.outcome=null;S.alert=['wa','İğne dilatör içine geri çekildi. Konumu yeniden ayarlayın.'];return}
 if(S.crossed)return;
 if(r.inSVC||r.region==='ivc'){S.alert=['wa','Uç SVK veya İVK içinde. İğneyi burada ilerletmeyin.'];return}
 if(!r.contact){S.alert=['wa','Uç septuma temas etmiyor (saat '+clockTxt(S.rot)+'). İğne çıkarılmadı. Önce saat 4–5 yönüne çevirip septuma temas sağlayın; serbest RA\'da iğne ilerletmek RA duvarı perforasyonu riski taşır.'];return}
 if(S.push<0.45){S.alert=['wa','Yeterli çadırlanma yok. Önce kılıf ve dilatörle septuma ileri baskı uygulayın (≥%45).'];return}
 S.attempts++;
 if(r.region==='fossa'){S.needleOut=true;S.crossed=true;S.outcome='la';S.push=0;S.alert=['ok','✅ İğne LA\'da: basınç trasesi LA dalga formuna döndü. Kontrast LA\'yı dolduruyor, TEE\'de LA\'da köpük var.'];
  S.fx.push({type:'la',t0:t,dur:3});addBubbles('la',t);evaluate(r)}
 else if(r.region==='aorta'||(r.region==='ant'&&r.dA<0.35)){S.needleOut=true;S.outcome='ao';S.comp++;S.alert=['er','❌ <b>Aortik ponksiyon!</b> Arteriyel basınç trasesi var, kontrast aortadan yukarı akıyor, kısa aksta köpük aortada. Yalnızca iğne ile yapılan ponksiyon çoğunlukla tolere edilir. İğneyi geri çekin, <b>dilatör veya kılıfı ilerletmeyin</b>, perikardı izleyin.'];
  S.fx.push({type:'ao',t0:t,dur:1.6});addBubbles('ao',t);renderResult()}
 else if(['sup','post','wsup','wpost'].includes(r.region)){S.needleOut=true;S.outcome='peri';S.comp++;S.alert=['er','❌ <b>Ekstrakardiyak geçiş</b> ('+REG[r.region]+'). İğne interatriyal katlantıdan perikardiyal ve ekstrakardiyak alana geçti: basınç sönük, kontrast perikardiyal alanda. İğneyi geri çekin ve tamponad açısından TEE ile izleyin.'];
  S.fx.push({type:'peri',t0:t,dur:8});renderResult()}
 else {S.alert=['wa','Kalın musküler doku ('+REG[r.region]+'): iğne ilerlemiyor. Zorlamayın, fossaya dönün.'+(r.region==='ant'?' Aort köküne de yakınsınız!':'')];renderResult()}
}
function doContrast(){
 const t=performance.now()/1000,r=tipState();const G=sheathGeom(r);
 if(S.outcome==='la'||S.sheathLA){S.fx.push({type:'la',t0:t,dur:3});addBubbles('la',t)}
 else if(S.outcome==='ao'){S.fx.push({type:'ao',t0:t,dur:1.6});addBubbles('ao',t)}
 else if(S.outcome==='peri'){S.fx.push({type:'peri',t0:t,dur:8})}
 else if(r.contact&&S.push>0.2){S.fx.push({type:'stain',t0:t,dur:6,p:G.tip});addBubbles('ra',t);S.alert=['ok','Septal boyanma (tenting stain): dilatör ucu septuma oturmuş durumda.']}
 else {S.fx.push({type:'ra',t0:t,dur:1.0,p:G.tip});addBubbles('ra',t)}
}

// ---------- arayüz ----------
const sel=$('proc');Object.entries(PROCS).forEach(([k,v])=>{const o=document.createElement('option');o.value=k;o.textContent=v.ad;sel.appendChild(o)});
function renderInfo(){const pp=PROCS[S.proc];$('procTag').textContent=pp.kisa;$('info').innerHTML='<h3>'+pp.ad+' – ponksiyon stratejisi</h3><ul style="margin:4px 0;padding-left:20px">'+pp.not.map(x=>'<li>'+x+'</li>').join('')+'</ul>'}
sel.addEventListener('change',()=>{S.proc=sel.value;S.done={};stepsHTML='';if(S.result){const r=tipState();evaluate(r)}renderInfo()});
const CARMS=[[0,'AP'],[-30,'RAO 30'],[-45,'RAO 45'],[45,'LAO 45']];
CARMS.forEach(([a,n])=>{const b=document.createElement('button');b.textContent=n;b.dataset.a=a;b.onclick=()=>{S.carm=a;syncBtns()};$('carmBtns').appendChild(b)});
const TEES=[['xp','X-plane'],['bic','Bikaval'],['sax','Kısa aks'],['4c','4 boşluk']];
TEES.forEach(([k,n])=>{const b=document.createElement('button');b.textContent=n;b.dataset.k=k;b.onclick=()=>{S.tee=k;syncBtns()};$('teeBtns').appendChild(b)});
function syncBtns(){[...$('carmBtns').children].forEach(b=>b.classList.toggle('on',+b.dataset.a===S.carm));[...$('teeBtns').children].forEach(b=>b.classList.toggle('on',b.dataset.k===S.tee))}
const lockd=()=>S.needleOut||S.crossed;
function lockMsg(){S.alert=S.crossed?['ok','LA\'ya geçildi, kateter sabitlendi. Yeni deneme için <b>↺ Baştan başla</b>.']:['er','🔒 İğne dilatörün dışında, kateter hareket ettirilemez. Önce <b>↩ İğneyi geri çek</b> (veya <kbd>N</kbd>).']}
function moveH(dh){if(lockd()){lockMsg();return}S.h=clamp(S.h+dh,-4.5,7);if(S.push>0&&Math.abs(dh)>0){S.push=Math.max(0,S.push-0.15)}S.alert=null}
function rotate(dr){if(lockd()){lockMsg();return}S.rot=((S.rot+dr)%12+12)%12;S.alert=null}
$('up').onclick=()=>moveH(0.15);$('dn').onclick=()=>moveH(-0.15);
$('cw').onclick=()=>rotate(0.25);$('ccw').onclick=()=>rotate(-0.25);
$('hS').oninput=e=>{if(lockd())return;S.h=+e.target.value;S.alert=null};
$('pS').oninput=e=>{if(lockd())return;S.push=+e.target.value/100};
$('needle').onclick=doNeedle;$('contrast').onclick=doContrast;
$('dil').onclick=()=>{S.sheathLA=true;S.alert=['ok','Dilatör ve ardından kılıf LA\'ya ilerletildi, iğne çekildi.']};
$('wire').onclick=()=>{S.wire=true;S.alert=['ok','Tel sol üst pulmoner vende. Transseptal erişim tamamlandı.']};
$('reset').onclick=()=>{initState(true);stepsHTML='';syncBtns();renderResult()};
$('guided').onchange=e=>{$('stepCard').style.display=e.target.checked?'':'none'};
// kadrana tıklama
function dialPick(ev){if(lockd()){lockMsg();return}const b=dl.getBoundingClientRect();const x=(ev.clientX-b.left)/b.width*150-75,y=(ev.clientY-b.top)/b.height*150-75;let h=Math.atan2(x,-y)/D2R/30;if(h<0)h+=12;S.rot=Math.round(h*4)/4%12}
let dragging=false;dl.addEventListener('pointerdown',e=>{dragging=true;dialPick(e)});window.addEventListener('pointerup',()=>dragging=false);dl.addEventListener('pointermove',e=>{if(dragging)dialPick(e)});
document.addEventListener('keydown',e=>{if(e.metaKey||e.ctrlKey||e.altKey)return;if(e.target.tagName==='SELECT'||e.target.tagName==='INPUT'&&e.target.type!=='range'&&e.target.type!=='checkbox')return;
 const k=e.key;if(k==='ArrowUp'){moveH(0.1);e.preventDefault()}else if(k==='ArrowDown'){moveH(-0.1);e.preventDefault()}else if(k==='ArrowRight'){rotate(0.25);e.preventDefault()}else if(k==='ArrowLeft'){rotate(-0.25);e.preventDefault()}
 else{const kk=k.toLowerCase();
  if(kk==='n')doNeedle();else if(kk==='k')doContrast();
  else if(k==='+'||k==='='){if(lockd())lockMsg();else S.push=Math.min(1,S.push+0.1)}else if(k==='-'||k==='_'){if(lockd())lockMsg();else S.push=Math.max(0,S.push-0.1)}
  else if(kk==='d'){if(!$('dil').disabled)$('dil').click()}else if(kk==='t'){if(!$('wire').disabled)$('wire').click()}
  else if('1234'.includes(k)&&k.length===1){S.carm=CARMS[+k-1][0];syncBtns()}
  else if('qwer'.includes(kk)&&kk.length===1){S.tee=TEES['qwer'.indexOf(kk)][0];syncBtns()}}});

// ---------- döngü ----------
let lastStat=0;
function frame(ms){
 const t=ms/1000;const w=t*TAU*1.2;WOB=[0.06*Math.sin(w),0.05*Math.sin(w+0.8),0.06*Math.sin(w+1.6)];
 const r=tipState();
 drawFluoro(t,r);drawTEE(t,r);drawMap(r);drawDial();drawPress(t);
 if(t-lastStat>0.12){updateStatus(r);updateSteps(r);lastStat=t}
 requestAnimationFrame(frame);
}
sel.value=S.proc;renderInfo();syncBtns();renderResult();requestAnimationFrame(frame);
})();
</script>
</body></html>
"""


# ===================== SIDEBAR =====================
with st.sidebar:
    st.title(APP_TITLE)

    menu = st.radio(
        "Menü",
        [
            "🧠 Soru Bankası",
            "🩺 Kateterizasyon Simülasyonu",
            "📈 Kateter Hemodinami Hesaplayıcı",
            "🪡 Transseptal Ponksiyon Simülasyonu",
            "🧮 Mitral Yetmezlik Hesaplayıcı",
            "🫀 Diyastolik Disfonksiyon Hesaplayıcı",
            "🏥 NEÜ Klinik Çalışmalar",
            "⭐ Özellikli Vakalar",
            "📝 Case Report Takip",
            "✉️ Editöre Mektup",
        ],
        index=0,
    )

    if menu == "🏥 NEÜ Klinik Çalışmalar":
        menu = st.radio("Çalışma seçin", CLINICAL_STUDIES, key="clinical_study_menu")

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



# ===================== HEADER / EKG ANİMASYONU =====================
if menu in CLINICAL_STUDIES:
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


# =========================================================
# ===================== EKRAN 0: SORU BANKASI / QUIZ =======
# =========================================================
if menu == "🧠 Soru Bankası":
    if not st.session_state.get("quiz_player"):
        with st.form("quiz_login"):
            name = st.text_input("Kullanıcı adı", max_chars=30)
            if st.form_submit_button("Giriş yap"):
                name = " ".join(name.split())
                if name:
                    st.session_state.quiz_player = name
                    st.rerun()
                st.warning("Kullanıcı adını gir.")
        _render_heart_atlas()
        st.stop()
    if st.button("Kullanıcı değiştir", help=st.session_state.quiz_player):
        for key in list(st.session_state):
            if key.startswith(("quiz_", "atlas_review_")):
                del st.session_state[key]
        st.rerun()
    mode = st.radio(
        "Soru bankası modu",
        ["Kalp atlası", "Fotoğraflı test", "Videolu test", "Karışık test"],
        format_func=lambda mode: {"Fotoğraflı test": "Fotoğraflı sorular", "Videolu test": "Videolu sorular"}.get(mode, mode),
        horizontal=True, key="soru_bankasi_modu",
    )
    if mode != "Karışık test":
        st.subheader("🏆 En uzun doğru serisi")
        try:
            ranks = _rank_quiz_records(_quiz_records_sheet().get_all_values(), mode)
            if ranks:
                for medal, column, (player, score) in zip(("🥇", "🥈", "🥉"), st.columns(3), ranks):
                    column.metric(f"{medal} {player}", f"{score} doğru")
            else:
                st.caption("İlk doğru serisiyle sıralama başlayacak.")
        except gspread.exceptions.GSpreadException:
            st.warning("Seri sıralaması şu anda okunamadı.")
    if mode == "Kalp atlası":
        _render_heart_atlas()
        st.stop()

    st.header("🧠 Kardiyoloji Soru Bankası")

    # Metin soruları üçüncü sekmeden, medya soruları isimli sekmelerden okunur.
    media_kind = "photo" if mode == "Fotoğraflı test" else "video" if mode == "Videolu test" else None
    quiz_sheet_id = MEDIA_SHEET_ID
    quiz_ws = QUESTION_WS_INDEX if not media_kind else MEDIA_PHOTO_TAB if media_kind == "photo" else MEDIA_VIDEO_TAB
    if not _media_sheet_is_configured():
        st.warning("Yeni Google Sheets bağlantısı henüz ayarlanmamış.")
        st.code('MEDIA_SHEET_ID = "YENI_SHEETS_ID_BURAYA"', language="python")
        st.info("web_app.py dosyasında bu değeri yeni Google Sheets ID'si ile değiştirin. Secrets'a yeni bir ID eklemeniz gerekmiyor.")
        st.stop()

    if media_kind and _media_folder_is_configured():
        if st.button("🔄 Drive listesini yenile", key=f"drive_refresh_{media_kind}",
                     help="Klasöre yeni eklenen veya adı değişen dosyaları yeniden tara."):
            _list_drive_media.clear()
            st.rerun()

    dfq = load_data(quiz_sheet_id, quiz_ws, required_col="SoruID")
    if dfq.empty:
        if media_kind:
            st.warning(f"'{quiz_ws}' sekmesi okunamadı veya henüz soru eklenmedi.")
            st.info("Yeni Google Sheets'i servis hesabının client_email adresiyle Düzenleyici olarak paylaşın. Sekme adlarını ve başlıkları kontrol edin.")
        else:
            st.warning("Henüz soru yok veya üçüncü sekmenin başlıkları uygun değil.")
            st.info("İlk satır: `SoruID | Aktif | Kategori | Soru | A | B | C | D | E | Dogru | Aciklama | Kaynak`. Metin soruları üçüncü sekmede olmalı.")
        st.stop()

    # Yeni medya tablolarında Kaynak isteğe bağlıdır; eski testin şeması değişmez.
    required_cols = ["SoruID", "Aktif", "Kategori", "Soru", "A", "B", "C", "D", "E", "Dogru", "Aciklama"]
    if not media_kind:
        required_cols.append("Kaynak")
    missing_cols = [c for c in required_cols if c not in dfq.columns]
    if missing_cols:
        st.error(f"{quiz_ws} sekmesinde eksik kolon var: " + ", ".join(missing_cols))
        st.info("Başlıklar: `SoruID | Aktif | Kategori | Soru | A | B | C | D | E | Dogru | Aciklama | Kaynak`; fotoğraf için `GorselDosya`, video için `VideoDosya` ekleyin.")
        st.stop()
    if media_kind and "Kaynak" not in dfq.columns:
        dfq = dfq.rename(columns={c: "Kaynak" for c in dfq.columns if c.strip().casefold() == "kaynak"})
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
        st.session_state.quiz_streak = 0
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
        st.session_state.quiz_streak = 0
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
        st.session_state.quiz_streak = 0
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

        if not media_kind:
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

    if not media_kind:
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
        if kaynak:
            st.caption(f"Görüntü kaynağı: {kaynak}")

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
                secilen_harf = secenekler[st.session_state.quiz_selected][0]
                if media_kind:
                    streak = st.session_state.quiz_streak + 1 if secilen_harf == dogru else 0
                    try:
                        _record_quiz_streak(mode, streak)
                    except gspread.exceptions.GSpreadException:
                        st.error("Seri kaydedilemedi. Tekrar Cevapla düğmesine basın.")
                        st.stop()
                    st.session_state.quiz_streak = streak
                st.session_state.quiz_answered = True
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

        if kaynak and not media_kind:
            st.caption(f"📚 Kaynak: {kaynak}")


# =========================================================
# ===================== EKRAN KS: KATETERİZASYON SİMÜLASYONU =====
# =========================================================
elif menu == "🩺 Kateterizasyon Simülasyonu":
    components.html(_CATH_SIM_HTML, height=1500, scrolling=True)


# =========================================================
# ===================== EKRAN KH: KATETER HEMODİNAMİ HESAPLAYICI =====
# =========================================================
elif menu == "📈 Kateter Hemodinami Hesaplayıcı":
    components.html(_CATH_CALC_HTML, height=3600, scrolling=True)


# =========================================================
# ===================== EKRAN TS: TRANSSEPTAL PONKSİYON SİMÜLASYONU =====
# =========================================================
elif menu == "🪡 Transseptal Ponksiyon Simülasyonu":
    components.html(_TS_SIM_HTML, height=2700, scrolling=True)


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



