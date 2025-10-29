import streamlit as st
from supabase import create_client, Client
import json, os, tempfile

# === PAGE CONFIG ===
st.set_page_config(page_title="🖋️ Calligraphy Annotator (Cloud)", layout="wide")

# === SUPABASE CONNECTION ===
@st.cache_resource
def init_connection() -> Client:
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_ANON_KEY"])

supabase: Client = init_connection()
BUCKET = st.secrets["SUPABASE_BUCKET"]

# === PAGE TITLE ===
st.title("🖋️ Calligraphy Annotation Tool (Online)")

# === SUPABASE HELPERS ===
@st.cache_data
def get_folders(bucket: str):
    res = supabase.storage.from_(bucket).list("", {"limit": 100})
    return sorted([i["name"] for i in res if i.get("metadata") is None])

@st.cache_data
def get_image_urls(bucket: str, folder: str):
    files = supabase.storage.from_(bucket).list(folder)
    urls = []
    for f in files:
        name = f["name"]
        if name.lower().endswith((".jpg", ".jpeg", ".png")):
            urls.append(supabase.storage.from_(bucket).get_public_url(f"{folder}/{name}"))
    return sorted(urls)

def load_existing_annotations(bucket, folder, filename):
    """Load JSON file from Supabase Storage if exists."""
    try:
        remote_path = f"{folder}/{filename}"
        res = supabase.storage.from_(bucket).download(remote_path)
        if res:
            data = json.loads(res.decode("utf-8"))
            st.info(f"📄 Loaded {filename} ({len(data)} entries).")
            return data
    except Exception:
        st.warning(f"No existing {filename} found in Supabase.")
    return []

def upload_json_direct(data_dict, bucket, folder, filename):
    """Upload JSON file to Supabase Storage (with overwrite)."""
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".json") as tmp:
            json.dump(data_dict, tmp, ensure_ascii=False, indent=2)
            tmp_path = tmp.name

        remote_path = f"{folder}/{filename}"

        supabase.storage.from_(bucket).upload(
            path=remote_path,
            file=tmp_path,
            file_options={
                "content-type": "application/json",
                "x-upsert": "true"
            }
        )

        st.success(f"☁️ Uploaded → {remote_path}")
    except Exception as e:
        st.error(f"❌ Upload failed: {e}")

# === FOLDER SELECTION ===
folders = get_folders(BUCKET)
if not folders:
    st.error("⚠️ No folders found.")
    st.stop()

selected_folder = st.selectbox("📁 Choose dataset folder / Klasör seçiniz", folders)
st.info(f"Selected folder: {selected_folder}")

image_urls = get_image_urls(BUCKET, selected_folder)
if not image_urls:
    st.warning("⚠️ No images found in this folder.")
    st.stop()

# === STATE HANDLING (with folder change detection) ===
if "selected_folder" not in st.session_state:
    st.session_state.selected_folder = None

# If the selected folder changes, reload annotation data
if st.session_state.selected_folder != selected_folder:
    st.cache_data.clear()  # clear cache to reload from Supabase
    st.session_state.selected_folder = selected_folder
    st.session_state.index = 0
    st.session_state.annotations = load_existing_annotations(
        BUCKET, f"{selected_folder}_annotations", "annotations.json"
    )
    st.session_state.deleted = load_existing_annotations(
        BUCKET, f"{selected_folder}_annotations", "deleted.json"
    )
else:
    # Initialize defaults if empty
    if "annotations" not in st.session_state:
        st.session_state.annotations = []
    if "deleted" not in st.session_state:
        st.session_state.deleted = []
    if "index" not in st.session_state:
        st.session_state.index = 0

# === NAVIGATION HELPERS ===
def next_image():
    st.session_state.index = min(st.session_state.index + 1, len(image_urls) - 1)

def prev_image():
    st.session_state.index = max(0, st.session_state.index - 1)

# === AUTO-SKIP ALREADY ANNOTATED ===
annotated_ids = {a["id"] for a in st.session_state.annotations}
while st.session_state.index < len(image_urls):
    current_id = os.path.splitext(os.path.basename(image_urls[st.session_state.index]))[0]
    if current_id not in annotated_ids:
        break
    st.session_state.index += 1

if st.session_state.index >= len(image_urls):
    st.success("🎉 All images annotated!")
    st.stop()

# === CURRENT IMAGE ===
img_url = image_urls[st.session_state.index]
img_name = os.path.basename(img_url)
progress_text = f"Image {st.session_state.index + 1}/{len(image_urls)} | Annotated: {len(st.session_state.annotations)}"
st.subheader(f"🖼️ {progress_text}")

col_img, col_form = st.columns([2, 3])

with col_img:
    st.image(img_url, width=600)

with col_form:
    with st.form(key="annotation_form", clear_on_submit=False):
        idx = st.session_state.index
        st.markdown("### 📝 Annotation Fields / Etiketleme Alanları")

        # --- TEXTS ---
        text_original = st.text_area("Original Text / Asıl Metin", key=f"text_original_{idx}", placeholder="بسم الله الرحمن الرحیم")
        text_latinized = st.text_area("Latinized Version / Latin Yazım", key=f"text_latinized_{idx}", placeholder="Bismillahirrahmanirrahim")
        text_translation_tr = st.text_area("Turkish Translation / Türkçe Çeviri", key=f"text_translation_{idx}", placeholder="Rahmân ve rahîm olan Allah'ın adıyla")

        # --- QURAN DETAILS ---
        st.markdown("#### 📖 Quran Details / Kur'an Bilgileri")
        surah_name = st.text_input("Surah Name / Sûre Adı", key=f"surah_{idx}", placeholder="Örnek: Fatiha")
        ayah_number = st.text_input("Ayah Number / Ayet Numarası", key=f"ayah_{idx}", placeholder="Örnek: 1-7")

        comment = st.text_area("Comment / Yorum veya Not", key=f"comment_{idx}", placeholder="örnek: Yazı mihrap üzerinde yer almakta.")

        submitted = st.form_submit_button("💾 Save & Next / Kaydet ve Sonraki", use_container_width=True)
        #skip_btn = st.form_submit_button("⏭ Skip / Atla", use_container_width=True)
        delete_btn = st.form_submit_button("❌ Delete / Uygun Değil", use_container_width=True)

back_btn = st.button("⬅️ Back / Geri", use_container_width=True)

# === BUTTON LOGIC ===
if submitted:
    image_id = os.path.splitext(img_name)[0]
    existing_ids = {a["id"] for a in st.session_state.annotations}
    if image_id in existing_ids:
        st.info("⚠️ This image is already annotated. Skipping save.")
    else:
        entry = {
            "id": image_id,
            "image_url": img_url,
            "text_original": text_original,
            "text_latinized": text_latinized,
            "text_translation_tr": text_translation_tr,
            "surah_name": surah_name,
            "ayah_number": ayah_number,
            "comment": comment
        }
        st.session_state.annotations.append(entry)
        upload_json_direct(st.session_state.annotations, BUCKET, f"{selected_folder}_annotations", "annotations.json")
        st.success("✅ Saved annotation to Supabase.")
    next_image()
    st.rerun()

elif delete_btn:
    image_id = os.path.splitext(img_name)[0]
    st.session_state.deleted.append({
        "id": image_id,
        "image_url": img_url,
        "reason": "Not suitable for labeling"
    })
    upload_json_direct(st.session_state.deleted, BUCKET, f"{selected_folder}_annotations", "deleted.json")
    st.warning(f"🗑️ {img_name} marked as deleted.")
    next_image()
    st.rerun()

#elif skip_btn:
 #   next_image()
  #  st.info("⏭ Skipped.")
   # st.rerun()

elif back_btn:
    prev_image()
    st.info("⏪ Moved back.")
    st.rerun()
