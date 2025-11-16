import streamlit as st
from supabase import create_client, Client
import json
import os
import tempfile
import datetime
import pandas as pd

# =========================
# PAGE CONFIG
# =========================
st.set_page_config(
    page_title="🖋️ Calligraphy Annotator (Cloud)",
    layout="wide"
)

# =========================
# SUPABASE CONNECTION
# =========================
@st.cache_resource
def init_connection() -> Client:
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_ANON_KEY"]
    )

supabase: Client = init_connection()
BUCKET = st.secrets["SUPABASE_BUCKET"]

st.title("🖋️ Calligraphy Annotation Tool (Grid Mode)")

# =========================
# SUPABASE HELPERS
# =========================
@st.cache_data
def get_folders(bucket: str):
    """List top-level folders in the bucket."""
    res = supabase.storage.from_(bucket).list("", {"limit": 500})
    return sorted([i["name"] for i in res if i.get("metadata") is None])

@st.cache_data
def get_image_urls(bucket: str, folder: str):
    """Return public URLs for images in a given folder."""
    files = supabase.storage.from_(bucket).list(folder)
    urls = []
    for f in files:
        name = f["name"]
        if name.lower().endswith((".jpg", ".jpeg", ".png")):
            urls.append(
                supabase.storage.from_(bucket).get_public_url(f"{folder}/{name}")
            )
    return sorted(urls)

def load_existing_annotations(bucket: str, folder: str, filename: str):
    """Load JSON file from Supabase Storage if it exists."""
    try:
        remote_path = f"{folder}/{filename}"
        res = supabase.storage.from_(bucket).download(remote_path)
        if res:
            data = json.loads(res.decode("utf-8"))
            st.info(f"📄 Loaded {filename} ({len(data)} entries)")
            return data
    except Exception:
        st.warning(f"No existing {filename} found in Supabase.")
    return []

def backup_and_upload_json(data_obj, bucket: str, folder: str, filename: str):
    """Create a timestamped backup, then overwrite the main JSON file."""
    try:
        # 1) timestamped backup file
        ts = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        backup_name = f"{filename.replace('.json','')}-{ts}.json"
        backup_folder = f"{folder}/_backups"
        backup_remote_path = f"{backup_folder}/{backup_name}"

        # backup temp file
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json", encoding="utf-8") as tmp_bk:
            json.dump(data_obj, tmp_bk, ensure_ascii=False, indent=2)
            backup_tmp_path = tmp_bk.name

        supabase.storage.from_(bucket).upload(
            path=backup_remote_path,
            file=backup_tmp_path,
            file_options={"content-type": "application/json", "x-upsert": "true"}
        )

        # 2) main JSON overwrite
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json", encoding="utf-8") as tmp_main:
            json.dump(data_obj, tmp_main, ensure_ascii=False, indent=2)
            main_tmp_path = tmp_main.name

        main_remote_path = f"{folder}/{filename}"

        supabase.storage.from_(bucket).upload(
            path=main_remote_path,
            file=main_tmp_path,
            file_options={"content-type": "application/json", "x-upsert": "true"}
        )

        st.success(f"☁️ Backup + Upload completed → {main_remote_path}")

    except Exception as e:
        st.error(f"❌ Backup/Upload failed: {e}")

def normalize_records(obj):
    """Ensure JSON is list[dict]."""
    if obj is None:
        return []
    if isinstance(obj, dict):
        return [obj]
    if isinstance(obj, list):
        return [r for r in obj if isinstance(r, dict)]
    return []

# =========================
# FOLDER SELECTION
# =========================
folders = get_folders(BUCKET)
if not folders:
    st.error("⚠️ No folders found in bucket.")
    st.stop()

selected_folder = st.selectbox(
    "📁 Choose dataset folder / Klasör seçiniz",
    folders
)
st.info(f"Selected folder: {selected_folder}")

image_urls = get_image_urls(BUCKET, selected_folder)
if not image_urls:
    st.warning("⚠️ No images found in this folder.")
    st.stop()

st.write(f"Toplam görsel sayısı / Total images: **{len(image_urls)}**")

# =========================
# LOAD EXISTING ANNOTATIONS & BUILD GRID ROWS
# =========================
ann_folder = f"{selected_folder}_annotations"
ann_filename = "annotations.json"

existing = normalize_records(
    load_existing_annotations(BUCKET, ann_folder, ann_filename)
)

# map id -> existing annotation
existing_by_id = {rec.get("id"): rec for rec in existing}

# columns we will use in the grid
ann_cols = [
    "id",
    "image_url",
    "text_original",
    "text_latinized",
    "text_translation_tr",
    "surah_name",
    "ayah_number",
    "comment",
]

rows = []
for url in image_urls:
    img_name = os.path.basename(url)
    image_id = os.path.splitext(img_name)[0]
    base = existing_by_id.get(image_id, {})

    row = {
        "id": image_id,
        "image_url": url,
        "text_original": base.get("text_original", ""),
        "text_latinized": base.get("text_latinized", ""),
        "text_translation_tr": base.get("text_translation_tr", ""),
        "surah_name": base.get("surah_name", ""),
        "ayah_number": base.get("ayah_number", ""),
        "comment": base.get("comment", ""),
    }
    rows.append(row)

df = pd.DataFrame(rows, columns=ann_cols)

st.markdown("### 🧾 Annotations grid (edit in-place and click Save)")

edited_df = st.data_editor(
    df,
    key="ann_grid",
    num_rows="fixed",  # no extra rows; one row per image
    use_container_width=True,
    column_config={
        "image_url": st.column_config.ImageColumn(
            "Image",
            help="Preview of the image",
            width="large"
        ),
        "id": st.column_config.Column("ID (from filename)"),
        "text_original": st.column_config.TextColumn("Original Text / Asıl Metin"),
        "text_latinized": st.column_config.TextColumn("Latinized / Latin Yazım"),
        "text_translation_tr": st.column_config.TextColumn("Translation / Çeviri"),
        "surah_name": st.column_config.TextColumn("Surah / Sûre"),
        "ayah_number": st.column_config.TextColumn("Ayah / Ayet"),
        "comment": st.column_config.TextColumn("Comment / Yorum"),
    },
    hide_index=True,
)

col_save, col_download = st.columns([1, 1])

with col_save:
    if st.button("💾 Save all annotations to Supabase", use_container_width=True):
        records = edited_df.to_dict(orient="records")
        backup_and_upload_json(
            records,
            BUCKET,
            ann_folder,
            ann_filename,
        )
        st.success(f"Saved {len(records)} rows to annotations.json")

with col_download:
    st.download_button(
        "⬇️ Download annotations.json",
        data=json.dumps(edited_df.to_dict(orient="records"), ensure_ascii=False, indent=2),
        file_name="annotations.json",
        mime="application/json",
        use_container_width=True,
    )
