diff --git a/web_app.py b/web_app.py
index db26dddf28c3f8c8d464b954d8fa9000826211dd..80756ae4cd29915e35347447180525d0f5709d94 100644
--- a/web_app.py
+++ b/web_app.py
@@ -1,89 +1,179 @@
 import streamlit as st
 import pandas as pd
 import gspread
 from oauth2client.service_account import ServiceAccountCredentials
 from datetime import datetime
 
 # --- AYARLAR ---
 SHEET_NAME = "H_Type_HT_Verileri"
 CASE_SHEET_NAME = "Vaka_Takip_Notlari"
 
 st.set_page_config(page_title="NEÜ-KARDİYO", page_icon="❤️", layout="wide")
 
+
 # --- BAĞLANTILAR ---
+@st.cache_resource
 def connect_to_gsheets():
     scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
-    creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
-    client = gspread.authorize(creds)
+    try:
+        creds = ServiceAccountCredentials.from_json_keyfile_dict(
+            st.secrets["gcp_service_account"], scope
+        )
+    except KeyError:
+        st.error(
+            "Google Sheets bağlantı bilgileri bulunamadı. Streamlit Secrets alanına hizmet hesabı JSON'unu ekleyin."
+        )
+        return None
+
+    try:
+        client = gspread.authorize(creds)
+    except Exception as exc:  # pragma: no cover - dış servis
+        st.error(f"Google Sheets bağlantısı kurulamadı: {exc}")
+        return None
+
     return client
 
+
+def get_sheet(sheet_name):
+    client = connect_to_gsheets()
+    if client is None:
+        return None
+
+    try:
+        return client.open(sheet_name).sheet1
+    except Exception as exc:  # pragma: no cover - dış servis
+        st.error(f"{sheet_name} adlı tabloya erişilemedi: {exc}")
+        return None
+
+
+def get_text_default(field, default=""):
+    return st.session_state.get("form_defaults", {}).get(field, default)
+
+
+def get_number_default(field, default=0.0):
+    raw_val = st.session_state.get("form_defaults", {}).get(field, default)
+    try:
+        return float(raw_val)
+    except (TypeError, ValueError):
+        return default
+
+
+def get_bool_default(field):
+    raw_val = st.session_state.get("form_defaults", {}).get(field, False)
+    if isinstance(raw_val, bool):
+        return raw_val
+    return str(raw_val).strip().lower() in {"1", "true", "evet", "yes", "on"}
+
+
 # --- VERİ İŞLEMLERİ ---
 def load_data(sheet_name):
+    sheet = get_sheet(sheet_name)
+    if sheet is None:
+        return pd.DataFrame()
+
     try:
-        client = connect_to_gsheets()
-        sheet = client.open(sheet_name).sheet1
         data = sheet.get_all_records()
         df = pd.DataFrame(data)
         if "Dosya Numarası" in df.columns:
             df["Dosya Numarası"] = df["Dosya Numarası"].astype(str)
         return df
-    except Exception as e:
+    except Exception as exc:  # pragma: no cover - dış servis
+        st.error(f"{sheet_name} verileri okunurken hata: {exc}")
         return pd.DataFrame()
 
 def delete_patient(sheet_name, dosya_no):
-    client = connect_to_gsheets()
-    sheet = client.open(sheet_name).sheet1
+    sheet = get_sheet(sheet_name)
+    if sheet is None:
+        return False
+
     try:
         cell = sheet.find(str(dosya_no))
+    except Exception as exc:  # pragma: no cover - dış servis
+        st.error(f"Silme başarısız: {exc}")
+        return False
+
+    if cell is None:
+        st.warning("Silinecek hasta bulunamadı.")
+        return False
+
+    try:
         sheet.delete_rows(cell.row)
         return True
-    except:
+    except Exception as exc:  # pragma: no cover - dış servis
+        st.error(f"Silme başarısız: {exc}")
         return False
 
 def save_data_row(sheet_name, data_dict, unique_col="Dosya Numarası"):
-    client = connect_to_gsheets()
-    sheet = client.open(sheet_name).sheet1
-    all_records = sheet.get_all_records()
+    sheet = get_sheet(sheet_name)
+    if sheet is None:
+        return
+
+    try:
+        all_records = sheet.get_all_records()
+    except Exception as exc:  # pragma: no cover - dış servis
+        st.error(f"Tablo okunamadı: {exc}")
+        return
+
     df = pd.DataFrame(all_records)
-    
+
     # Güncelleme kontrolü
     if not df.empty and str(data_dict[unique_col]) in df[unique_col].astype(str).values:
-        cell = sheet.find(str(data_dict[unique_col]))
-        sheet.delete_rows(cell.row)
-        st.toast(f"{data_dict[unique_col]} güncelleniyor...", icon="🔄")
-    
+        try:
+            cell = sheet.find(str(data_dict[unique_col]))
+            sheet.delete_rows(cell.row)
+            st.toast(f"{data_dict[unique_col]} güncelleniyor...", icon="🔄")
+        except Exception as exc:  # pragma: no cover - dış servis
+            st.error(f"Güncelleme sırasında hata: {exc}")
+            return
+
     # Kayıt
-    if df.empty:
-        sheet.append_row(list(data_dict.keys()))
-        sheet.append_row(list(data_dict.values()))
-    else:
+    try:
+        if df.empty:
+            sheet.append_row(list(data_dict.keys()))
+            sheet.append_row(list(data_dict.values()))
+        else:
+            headers = sheet.row_values(1)
+            row_to_add = [str(data_dict.get(header, "")) for header in headers]
+            sheet.append_row(row_to_add)
+    except Exception as exc:  # pragma: no cover - dış servis
+        st.error(f"Kayıt eklenemedi: {exc}")
+
+
+def get_patient_by_file_no(sheet_name, dosya_no):
+    sheet = get_sheet(sheet_name)
+    if sheet is None:
+        return None
+
+    try:
+        cell = sheet.find(str(dosya_no))
         headers = sheet.row_values(1)
-        row_to_add = []
-        for header in headers:
-            row_to_add.append(str(data_dict.get(header, "")))
-        sheet.append_row(row_to_add)
+        values = sheet.row_values(cell.row)
+        return dict(zip(headers, values))
+    except Exception as exc:  # pragma: no cover - dış servis
+        st.error(f"Hasta bilgisi alınamadı: {exc}")
+        return None
 
 # --- ARAYÜZ ---
 with st.sidebar:
     st.title("❤️ NEÜ-KARDİYO")
     menu = st.radio("Menü", ["🏥 Veri Girişi (H-Type HT)", "📝 Vaka Takip (Notlar)"])
     st.divider()
     with st.expander("📋 ÇALIŞMA KRİTERLERİ", expanded=True):
         st.success("**✅ DAHİL:** Son 6 ayda yeni tanı esansiyel HT")
         st.error("**⛔ HARİÇ:** Sekonder HT, KY, AKS, Cerrahi, Konjenital, Pulmoner HT, ABY, **AF (Atriyal Fibrilasyon)**")
 
 # --- MOD 1: VAKA TAKİP ---
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
                 save_data_row(CASE_SHEET_NAME, note_data, unique_col="Dosya No")
                 st.success("Kaydedildi")
     with col2:
@@ -143,198 +233,276 @@ elif menu == "🏥 Veri Girişi (H-Type HT)":
         z-index: 2;
     }
     </style>
     <div class="monitor-container">
         <div class="ecg-grid"></div>
         <div class="ecg-wave"></div>
         <div class="monitor-overlay"></div>
     </div>
     """
     st.markdown(ecg_monitor_html, unsafe_allow_html=True)
     
     st.title("H-TYPE HİPERTANSİYON ÇALIŞMASI")
     
     tab_list, tab_klinik, tab_lab, tab_eko = st.tabs(["📋 HASTA LİSTESİ / SİLME", "👤 KLİNİK", "🩸 LABORATUVAR", "🫀 EKO"])
 
     with tab_list:
         c_list1, c_list2 = st.columns([3, 1])
         with c_list1:
             if st.button("🔄 Listeyi Yenile"): st.rerun()
             df = load_data(SHEET_NAME)
             if not df.empty:
                 st.metric("Toplam Kayıtlı Hasta", len(df))
                 st.dataframe(df, use_container_width=True)
             else:
                 st.info("Veritabanı boş.")
-        
+
         # SİLME BÖLÜMÜ
         with c_list2:
             st.error("⚠️ HASTA SİLME")
             if not df.empty:
                 del_list = df["Dosya Numarası"].astype(str).tolist()
-                del_select = st.selectbox("Silinecek Dosya No", del_list)
+                del_select = st.selectbox("Silinecek Dosya No", del_list, key="del_select")
                 if st.button("🗑️ HASTAYI SİL"):
                     with st.spinner("Siliniyor..."):
                         if delete_patient(SHEET_NAME, del_select):
                             st.success("Hasta Silindi!")
                             st.rerun()
                         else:
                             st.error("Silinemedi.")
 
+            st.divider()
+            st.info("✏️ KAYIT DÜZENLE")
+            if not df.empty:
+                edit_select = st.selectbox(
+                    "Düzenlenecek Dosya No", del_list if not df.empty else [], key="edit_select"
+                )
+                if st.button("🔍 Formu Doldur"):
+                    patient = get_patient_by_file_no(SHEET_NAME, edit_select)
+                    if patient:
+                        st.session_state["form_defaults"] = patient
+                        st.success("Form, seçilen hasta ile dolduruldu.")
+                        st.rerun()
+
+            if st.button("➕ Yeni Kayıt Başlat"):
+                st.session_state["form_defaults"] = {}
+                st.rerun()
+
+    form_defaults = st.session_state.get("form_defaults", {})
+
     with st.form("main_form"):
         # 1. KLİNİK
         with tab_klinik:
             c1, c2 = st.columns(2)
             with c1:
                 st.markdown("##### Kimlik")
-                dosya_no = st.text_input("Dosya Numarası (Zorunlu)")
-                ad_soyad = st.text_input("Adı Soyadı")
-                basvuru = st.date_input("Başvuru Tarihi")
-                hekim = st.text_input("Veriyi Giren Hekim")
-                iletisim = st.text_input("İletişim")
+                dosya_no = st.text_input(
+                    "Dosya Numarası (Zorunlu)", value=get_text_default("Dosya Numarası")
+                )
+                ad_soyad = st.text_input("Adı Soyadı", value=get_text_default("Adı Soyadı"))
+                try:
+                    tarih_val = form_defaults.get("Tarih")
+                    tarih_default = datetime.fromisoformat(tarih_val).date() if tarih_val else datetime.now().date()
+                except Exception:
+                    tarih_default = datetime.now().date()
+                basvuru = st.date_input("Başvuru Tarihi", value=tarih_default)
+                hekim = st.text_input("Veriyi Giren Hekim", value=get_text_default("Hekim"))
+                iletisim = st.text_input("İletişim", value=get_text_default("İletişim"))
             with c2:
                 st.markdown("##### Fizik Muayene")
                 col_y, col_c = st.columns(2)
-                yas = col_y.number_input("Yaş", step=1)
-                cinsiyet = col_c.radio("Cinsiyet", ["Erkek", "Kadın"], horizontal=True)
+                yas = col_y.number_input("Yaş", step=1, value=get_number_default("Yaş", 0))
+                cinsiyet_default = get_text_default("Cinsiyet", "Erkek")
+                cinsiyet_index = 0 if cinsiyet_default == "Erkek" else 1
+                cinsiyet = col_c.radio(
+                    "Cinsiyet", ["Erkek", "Kadın"], horizontal=True, index=cinsiyet_index
+                )
                 cb1, cb2, cb3 = st.columns(3)
-                boy = cb1.number_input("Boy (cm)")
-                kilo = cb2.number_input("Kilo (kg)")
+                boy = cb1.number_input("Boy (cm)", value=get_number_default("Boy", 0))
+                kilo = cb2.number_input("Kilo (kg)", value=get_number_default("Kilo", 0))
                 bmi = 0
                 bsa = 0
-                if boy > 0 and kilo > 0: 
+                if boy > 0 and kilo > 0:
                     bmi = kilo/((boy/100)**2)
-                    bsa = (boy * kilo / 3600) ** 0.5 
+                    bsa = (boy * kilo / 3600) ** 0.5
                 
                 cb3.metric("BMI", f"{bmi:.2f}")
                 
                 ct1, ct2 = st.columns(2)
-                ta_sis = ct1.number_input("TA Sistol", step=1)
-                ta_dia = ct2.number_input("TA Diyastol", step=1)
-            
+                ta_sis = ct1.number_input("TA Sistol", step=1, value=get_number_default("TA Sistol", 0))
+                ta_dia = ct2.number_input("TA Diyastol", step=1, value=get_number_default("TA Diyastol", 0))
+
             st.divider()
-            ekg = st.selectbox("EKG Bulgusu", ["NSR", "LBBB", "RBBB", "VPB", "SVT", "Diğer"]) 
+            ekg_options = ["NSR", "LBBB", "RBBB", "VPB", "SVT", "Diğer"]
+            try:
+                ekg_index = ekg_options.index(get_text_default("EKG", "NSR"))
+            except ValueError:
+                ekg_index = 0
+            ekg = st.selectbox("EKG Bulgusu", ekg_options, index=ekg_index)
             ci1, ci2 = st.columns(2)
-            ilaclar = ci1.text_area("Kullandığı İlaçlar")
-            baslanan = ci2.text_area("Başlanan İlaçlar")
-            
+            ilaclar = ci1.text_area("Kullandığı İlaçlar", value=get_text_default("İlaçlar"))
+            baslanan = ci2.text_area("Başlanan İlaçlar", value=get_text_default("Başlanan İlaçlar"))
+
             st.markdown("##### Ek Hastalıklar")
             cc1, cc2, cc3, cc5 = st.columns(4)
-            dm = cc1.checkbox("DM"); kah = cc2.checkbox("KAH"); hpl = cc3.checkbox("HPL"); inme = cc5.checkbox("İnme")
-            diger_hst = st.text_input("Diğer Hastalıklar")
+            dm = cc1.checkbox("DM", value=get_bool_default("DM"))
+            kah = cc2.checkbox("KAH", value=get_bool_default("KAH"))
+            hpl = cc3.checkbox("HPL", value=get_bool_default("HPL"))
+            inme = cc5.checkbox("İnme", value=get_bool_default("İnme"))
+            diger_hst = st.text_input("Diğer Hastalıklar", value=get_text_default("Diğer Hast"))
 
         # 2. LAB
         with tab_lab:
             l1, l2, l3, l4 = st.columns(4)
             with l1:
                 st.markdown("🔴 **Hemogram**")
-                hgb = st.number_input("Hgb"); hct = st.number_input("Hct"); wbc = st.number_input("WBC"); plt = st.number_input("PLT")
-                neu = st.number_input("Nötrofil"); lym = st.number_input("Lenfosit"); mpv = st.number_input("MPV"); rdw = st.number_input("RDW")
+                hgb = st.number_input("Hgb", value=get_number_default("Hgb"))
+                hct = st.number_input("Hct", value=get_number_default("Hct"))
+                wbc = st.number_input("WBC", value=get_number_default("WBC"))
+                plt = st.number_input("PLT", value=get_number_default("PLT"))
+                neu = st.number_input("Nötrofil", value=get_number_default("Neu"))
+                lym = st.number_input("Lenfosit", value=get_number_default("Lym"))
+                mpv = st.number_input("MPV", value=get_number_default("MPV"))
+                rdw = st.number_input("RDW", value=get_number_default("RDW"))
             with l2:
                 st.markdown("🧪 **Biyokimya**")
-                glukoz = st.number_input("Glukoz"); ure = st.number_input("Üre"); krea = st.number_input("Kreatinin"); uric = st.number_input("Ürik Asit")
-                na = st.number_input("Na"); k_val = st.number_input("K"); alt = st.number_input("ALT"); ast = st.number_input("AST")
-                tot_prot = st.number_input("Total Prot"); albumin = st.number_input("Albümin")
+                glukoz = st.number_input("Glukoz", value=get_number_default("Glukoz"))
+                ure = st.number_input("Üre", value=get_number_default("Üre"))
+                krea = st.number_input("Kreatinin", value=get_number_default("Kreatinin"))
+                uric = st.number_input("Ürik Asit", value=get_number_default("Ürik Asit"))
+                na = st.number_input("Na", value=get_number_default("Na"))
+                k_val = st.number_input("K", value=get_number_default("K"))
+                alt = st.number_input("ALT", value=get_number_default("ALT"))
+                ast = st.number_input("AST", value=get_number_default("AST"))
+                tot_prot = st.number_input("Total Prot", value=get_number_default("Tot. Prot"))
+                albumin = st.number_input("Albümin", value=get_number_default("Albümin"))
             with l3:
                 st.markdown("🟡 **Lipid**")
-                chol = st.number_input("Kolesterol"); ldl = st.number_input("LDL"); hdl = st.number_input("HDL"); trig = st.number_input("Trig")
+                chol = st.number_input("Kolesterol", value=get_number_default("Chol"))
+                ldl = st.number_input("LDL", value=get_number_default("LDL"))
+                hdl = st.number_input("HDL", value=get_number_default("HDL"))
+                trig = st.number_input("Trig", value=get_number_default("Trig"))
             with l4:
                 st.markdown("⚡ **Spesifik**")
-                homosis = st.number_input("Homosistein"); lpa = st.number_input("Lp(a)"); folik = st.number_input("Folik Asit"); b12 = st.number_input("B12")
+                homosis = st.number_input("Homosistein", value=get_number_default("Homosistein"))
+                lpa = st.number_input("Lp(a)", value=get_number_default("Lp(a)"))
+                folik = st.number_input("Folik Asit", value=get_number_default("Folik Asit"))
+                b12 = st.number_input("B12", value=get_number_default("B12"))
 
         # 3. EKO
         with tab_eko:
             # GÜNCELLENEN BİLGİ KUTUSU
             st.info("ℹ️ **OTOMATİK HESAPLANACAK PARAMETRELER:**\n"
                     "Veri girişi yapıldıkça aşağıdaki değerler sistem tarafından hesaplanıp kaydedilecektir:\n"
                     "🔹 **Klinik:** BMI, BSA\n"
                     "🔹 **Yapısal:** LV Mass, LVMi, RWT, LACi\n"
                     "🔹 **Fonksiyonel:** E/A, E/e', TAPSE/Sm")
 
             e1, e2, e3, e4 = st.columns(4)
             with e1:
                 st.markdown("**1. LV Yapı (Mass & RWT)**")
-                lvedd = st.number_input("LVEDD (mm)")
-                lvesd = st.number_input("LVESD (mm)")
-                ivs = st.number_input("IVS (mm)")
-                pw = st.number_input("PW (mm)")
-                lvedv = st.number_input("LVEDV (mL)")
-                lvesv = st.number_input("LVESV (mL)")
-                ao_asc = st.number_input("Ao Asc (mm)")
+                lvedd = st.number_input("LVEDD (mm)", value=get_number_default("LVEDD"))
+                lvesd = st.number_input("LVESD (mm)", value=get_number_default("LVESD"))
+                ivs = st.number_input("IVS (mm)", value=get_number_default("IVS"))
+                pw = st.number_input("PW (mm)", value=get_number_default("PW"))
+                lvedv = st.number_input("LVEDV (mL)", value=get_number_default("LVEDV"))
+                lvesv = st.number_input("LVESV (mL)", value=get_number_default("LVESV"))
+                ao_asc = st.number_input("Ao Asc (mm)", value=get_number_default("Ao Asc"))
                 
                 # --- OTOMATİK HESAPLAMALAR ---
                 lv_mass = 0.0; lvmi = 0.0; rwt = 0.0
                 
                 if lvedd > 0 and ivs > 0 and pw > 0:
                     lvedd_cm = lvedd / 10; ivs_cm = ivs / 10; pw_cm = pw / 10
                     lv_mass = 0.8 * (1.04 * ((lvedd_cm + ivs_cm + pw_cm)**3 - lvedd_cm**3)) + 0.6
                     if bsa > 0: lvmi = lv_mass / bsa
                 
                 if lvedd > 0 and pw > 0:
                     rwt = (2 * pw) / lvedd
                 
                 # Mavi İkonlu Sabit Gösterim
                 st.markdown(f"🔵 **LV Mass:** {lv_mass:.1f} g")
                 st.markdown(f"🔵 **LVMi:** {lvmi:.1f} g/m²")
                 st.markdown(f"🔵 **RWT:** {rwt:.2f}")
 
             with e2:
                 st.markdown("**2. Sistolik**")
-                lvef = st.number_input("LVEF"); sv = st.number_input("SV"); lvot_vti = st.number_input("LVOT VTI"); gls = st.number_input("GLS"); gcs = st.number_input("GCS"); sd_ls = st.number_input("SD-LS")
+                lvef = st.number_input("LVEF", value=get_number_default("LVEF"))
+                sv = st.number_input("SV", value=get_number_default("SV"))
+                lvot_vti = st.number_input("LVOT VTI", value=get_number_default("LVOT VTI"))
+                gls = st.number_input("GLS", value=get_number_default("GLS"))
+                gcs = st.number_input("GCS", value=get_number_default("GCS"))
+                sd_ls = st.number_input("SD-LS", value=get_number_default("SD-LS"))
             with e3:
                 st.markdown("**3. Diyastolik**")
-                mit_e = st.number_input("Mitral E"); mit_a = st.number_input("Mitral A"); sept_e = st.number_input("Septal e'"); lat_e = st.number_input("Lateral e'")
-                laedv = st.number_input("LAEDV"); laesv = st.number_input("LAESV"); la_strain = st.number_input("LA Strain")
+                mit_e = st.number_input("Mitral E", value=get_number_default("Mitral E"))
+                mit_a = st.number_input("Mitral A", value=get_number_default("Mitral A"))
+                sept_e = st.number_input("Septal e'", value=get_number_default("Septal e'"))
+                lat_e = st.number_input("Lateral e'", value=get_number_default("Lateral e'"))
+                laedv = st.number_input("LAEDV", value=get_number_default("LAEDV"))
+                laesv = st.number_input("LAESV", value=get_number_default("LAESV"))
+                la_strain = st.number_input("LA Strain", value=get_number_default("LA Strain"))
                 
                 # Hesaplamalar
                 mit_ea = mit_e/mit_a if mit_a > 0 else 0.0
                 mit_ee = mit_e/sept_e if sept_e > 0 else 0.0
                 laci = laedv/lvedv if lvedv > 0 else 0.0
                 
                 # Mavi İkonlu Sabit Gösterim
                 st.markdown(f"🔵 **E/A:** {mit_ea:.2f}")
                 st.markdown(f"🔵 **E/e':** {mit_ee:.2f}")
                 st.markdown(f"🔵 **LACi:** {laci:.2f}")
 
             with e4:
                 st.markdown("**4. Sağ Kalp**")
-                tapse = st.number_input("TAPSE"); rv_sm = st.number_input("RV Sm"); spap = st.number_input("sPAP"); rvot_vti = st.number_input("RVOT VTI"); rvot_acct = st.number_input("RVOT accT")
+                tapse = st.number_input("TAPSE", value=get_number_default("TAPSE"))
+                rv_sm = st.number_input("RV Sm", value=get_number_default("RV Sm"))
+                spap = st.number_input("sPAP", value=get_number_default("sPAP"))
+                rvot_vti = st.number_input("RVOT VTI", value=get_number_default("RVOT VTI"))
+                rvot_acct = st.number_input("RVOT accT", value=get_number_default("RVOT accT"))
                 
                 tapse_sm = tapse/rv_sm if rv_sm > 0 else 0.0
                 
                 # Mavi İkonlu Sabit Gösterim
                 st.markdown(f"🔵 **TAPSE/Sm:** {tapse_sm:.2f}")
 
         submitted = st.form_submit_button("💾 KAYDET / GÜNCELLE", type="primary")
-        
+
         if submitted:
             if not dosya_no:
                 st.error("Dosya No Zorunlu!")
             else:
+                existing_df = load_data(SHEET_NAME)
+                is_update = (
+                    not existing_df.empty
+                    and dosya_no in existing_df.get("Dosya Numarası", pd.Series(dtype=str)).astype(str).values
+                )
                 mit_ea = mit_e/mit_a if mit_a>0 else ""
                 mit_ee = mit_e/sept_e if sept_e>0 else ""
                 laci = laedv/lvedv if lvedv>0 else ""
                 tapse_sm = tapse/rv_sm if rv_sm>0 else ""
                 
                 data_row = {
                     "Dosya Numarası": dosya_no, "Adı Soyadı": ad_soyad, "Tarih": str(basvuru), "Hekim": hekim,
                     "Yaş": yas, "Cinsiyet": cinsiyet, "Boy": boy, "Kilo": kilo, "BMI": bmi, "BSA": bsa,
                     "TA Sistol": ta_sis, "TA Diyastol": ta_dia, "EKG": ekg, 
                     "İlaçlar": ilaclar, "Başlanan İlaçlar": baslanan,
                     "DM": dm, "KAH": kah, "HPL": hpl, "İnme": inme, "Diğer Hast": diger_hst,
                     # LAB
                     "Hgb": hgb, "Hct": hct, "WBC": wbc, "PLT": plt, "Neu": neu, "Lym": lym, "MPV": mpv, "RDW": rdw,
                     "Glukoz": glukoz, "Üre": ure, "Kreatinin": krea, "Ürik Asit": uric, "Na": na, "K": k_val, 
                     "ALT": alt, "AST": ast, "Tot. Prot": tot_prot, "Albümin": albumin,
                     "Chol": chol, "LDL": ldl, "HDL": hdl, "Trig": trig, 
                     "Lp(a)": lpa, "Homosistein": homosis, "Folik Asit": folik, "B12": b12, # CRP çıkarıldı
                     # EKO
                     "LVEDD": lvedd, "LVESD": lvesd, "IVS": ivs, "PW": pw, "LVEDV": lvedv, "LVESV": lvesv, 
                     "LV Mass": lv_mass, "LVMi": lvmi, "RWT": rwt, "Ao Asc": ao_asc,
                     "LVEF": lvef, "SV": sv, "LVOT VTI": lvot_vti, "GLS": gls, "GCS": gcs, "SD-LS": sd_ls,
                     "Mitral E": mit_e, "Mitral A": mit_a, "Mitral E/A": mit_ea, "Septal e'": sept_e, "Lateral e'": lat_e, "Mitral E/e'": mit_ee,
                     "LAEDV": laedv, "LAESV": laesv, "LA Strain": la_strain, "LACi": laci,
                     "TAPSE": tapse, "RV Sm": rv_sm, "TAPSE/Sm": tapse_sm, "sPAP": spap, "RVOT VTI": rvot_vti, "RVOT accT": rvot_acct
                 }
-                
+
                 save_data_row(SHEET_NAME, data_row)
-                st.success(f"✅ {dosya_no} nolu hasta başarıyla kaydedildi!")
+                st.session_state["form_defaults"] = data_row
+                message = "güncellendi" if is_update else "kaydedildi"
+                st.success(f"✅ {dosya_no} nolu hasta başarıyla {message}!")
