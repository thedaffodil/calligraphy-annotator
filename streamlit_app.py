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
    page_title="🖋️ Calligraphy Annotator (Grid Mode)",
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

def get_folders(bucket: str):
    """Always fetch live folder list (no caching)."""
    res = supabase.storage.from_(bucket).list("", {"limit": 500})
    return sorted([i["name"] for i in res if i.get("metadata") is None])

def get_image_urls(bucket: str, folder: str):
    """Always fetch live image list (no caching)."""
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
            return data
    except Exception:
        pass
    return []

def backup_and_upload_json(data_obj, bucket: str, folder: str, filename: str):
    """Create a timestamped backup, then overwrite the main JSON file."""
    try:
        # 1) backup
        ts = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        backup_name = f"{filename.replace('.json','')}-{ts}.json"
        backup_path = f"{folder}/_backups/{backup_name}"

        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json", encoding="utf-8") as tmp_bk:
            json.dump(data_obj, tmp_bk, ensure_ascii=False, indent=2)
            tmp_bk_path = tmp_bk.name

        supabase.storage.from_(bucket).upload(
            backup_path,
            tmp_bk_path,
            file_options={"content-type": "application/json", "x-upsert": "true"}
        )

        # 2) overwrite main JSON
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json", encoding="utf-8") as tmp_main:
            json.dump(data_obj, tmp_main, ensure_ascii=False, indent=2)
            tmp_main_path = tmp_main.name

        main_remote_path = f"{folder}/{filename}"

        supabase.storage.from_(bucket).upload(
            main_remote_path,
            tmp_main_path,
            file_options={"content-type": "application/json", "x-upsert": "true"}
        )

        st.success(f"☁️ Saved → {main_remote_path}")

    except Exception as e:
        st.error(f"❌ Upload failed: {e}")

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
col_folder, col_refresh = st.columns([3, 1])

with col_folder:
    folders = get_folders(BUCKET)
    if not folders:
        st.error("⚠️ No folders found in bucket.")
        st.stop()

    selected_folder = st.selectbox("📁 Choose folder", folders)

with col_refresh:
    if st.button("🔄 Refresh folders", use_container_width=True):
        st.experimental_rerun()

st.info(f"Selected folder: **{selected_folder}**")

# Load images
image_urls = get_image_urls(BUCKET, selected_folder)
st.write(f"Total images: **{len(image_urls)}**")

if not image_urls:
    st.warning("⚠️ This folder is empty.")
    st.stop()

# =========================
# LOAD EXISTING ANNOTATIONS
# =========================
ann_folder = f"{selected_folder}_annotations"
ann_filename = "annotations.json"

existing = normalize_records(load_existing_annotations(BUCKET, ann_folder, ann_filename))
existing_by_id = {rec.get("id"): rec for rec in existing}

# =========================
# BUILD GRID ROWS
# =========================
rows = []
for url in image_urls:
    img_name = os.path.basename(url)
    image_id = os.path.splitext(img_name)[0]
    base = existing_by_id.get(image_id, {})

    row = {
        "image": url,  # will be displayed as thumbnail
        "id": image_id,
        "text_original": base.get("text_original", ""),
        "text_latinized": base.get("text_latinized", ""),
        "text_translation_tr": base.get("text_translation_tr", ""),
        "surah_name": base.get("surah_name", ""),
        "ayah_number": base.get("ayah_number", ""),
        "comment": base.get("comment", "")
    }
    rows.append(row)

df = pd.DataFrame(rows)

# =========================
# GRID UI
# =========================
st.markdown("### 🧾 Annotation Grid (edit directly and save)")

edited_df = st.data_editor(
    df,
    key="ann_grid",
    num_rows="fixed",
    use_container_width=True,
    column_config={
        "image": st.column_config.ImageColumn(
            "Image",
            width="large",
            help="Preview of the image"
        ),
        "id": st.column_config.TextColumn("ID"),
        "text_original": st.column_config.TextColumn("Original Text"),
        "text_latinized": st.column_config.TextColumn("Latinized"),
        "text_translation_tr": st.column_config.TextColumn("Translation (TR)"),
        "surah_name": st.column_config.TextColumn("Surah"),
        "ayah_number": st.column_config.TextColumn("Ayah"),
        "comment": st.column_config.TextColumn("Comment"),
    },
    hide_index=True,
)

# =========================
# SAVE + DOWNLOAD
# =========================
col_save, col_download = st.columns(2)

with col_save:
    if st.button("💾 Save all annotations to Supabase", use_container_width=True):
        records = edited_df.to_dict(orient="records")
        backup_and_upload_json(
            records,
            BUCKET,
            ann_folder,
            ann_filename,
        )
        st.success(f"Saved {len(records)} annotations.")

with col_download:
    st.download_button(
        "⬇️ Download annotations.json",
        data=json.dumps(edited_df.to_dict(orient="records"), ensure_ascii=False, indent=2),
        file_name="annotations.json",
        mime="application/json",
        use_container_width=True,
    )
