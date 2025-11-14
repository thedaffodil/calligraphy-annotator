import streamlit as st
from supabase import create_client, Client
import json
import os
import tempfile
import io
import datetime

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

st.title("🖋️ Calligraphy Annotation Tool (Online)")

# =========================
# SUPABASE HELPERS
# =========================
@st.cache_data
def get_folders(bucket: str):
    """List top-level folders in the bucket."""
    res = supabase.storage.from_(bucket).list("", {"limit": 200})
    # Only keep items that represent folders (no metadata → it's a "folder")
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
            st.info(f"📄 Loaded {filename} ({len(data)} entries).")
            return data
    except Exception:
        st.warning(f"No existing {filename} found in Supabase.")
    return []

def upload_json_direct(data_obj, bucket: str, folder: str, filename: str):
    """Upload JSON file to Supabase Storage (overwrite via x-upsert)."""
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", delete=False, suffix=".json"
        ) as tmp:
            json.dump(data_obj, tmp, ensure_ascii=False, indent=2)
            tmp_path = tmp.name

        remote_path = f"{folder}/{filename}"

        supabase.storage.from_(bucket).upload(
            path=remote_path,
            file=tmp_path,
            file_options={
                "content-type": "application/json",
                "x-upsert": "true",
            },
        )

        st.success(f"☁️ Uploaded → {remote_path}")
    except Exception as e:
        st.error(f"❌ Upload failed: {e}")

def backup_and_upload_json(data_obj, bucket: str, folder: str, filename: str):
    """
    Create a timestamped backup, then overwrite the main JSON file.
    Backups go under: {folder}/_backups/...
    """
    # 1) timestamped backup
    ts = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    backup_key = f"{folder}/_backups/{filename.replace('.json','')}-{ts}.json"
    buf = io.BytesIO(json.dumps(data_obj, ensure_ascii=False, indent=2).encode("utf-8"))
    supabase.storage.from_(bucket).upload(
        backup_key,
        buf,
        {
            "content-type": "application/json",
            "x-upsert": "true",
        },
    )

    # 2) overwrite canonical file
    upload_json_direct(data_obj, bucket, folder, filename)

def normalize_records(obj):
    """Ensure JSON is list[dict]; coerce dict → [dict], ignore other types."""
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

# =========================
# STATE HANDLING
# =========================
if "selected_folder" not in st.session_state:
    st.session_state.selected_folder = None

# When folder changes: reload annotations & deleted, reset index
if st.session_state.selected_folder != selected_folder:
    st.cache_data.clear()                      # clear cached lists
    st.session_state.selected_folder = selected_folder
    st.session_state.index = 0
    st.session_state.annotations = load_existing_annotations(
        BUCKET, f"{selected_folder}_annotations", "annotations.json"
    )
    st.session_state.deleted = load_existing_annotations(
        BUCKET, f"{selected_folder}_annotations", "deleted.json"
    )
else:
    if "annotations" not in st.session_state:
        st.session_state.annotations = []
    if "deleted" not in st.session_state:
        st.session_state.deleted = []
    if "index" not in st.session_state:
        st.session_state.index = 0

# Navigation helpers
def next_image():
    st.session_state.index = min(
        st.session_state.index + 1, len(image_urls) - 1
    )

def prev_image():
    st.session_state.index = max(0, st.session_state.index - 1)

# =========================
# AUTO-SKIP ALREADY PROCESSED
# =========================
annotated_ids = {a["id"] for a in st.session_state.annotations}
deleted_ids = {d["id"] for d in st.session_state.deleted}
processed_ids = annotated_ids.union(deleted_ids)

while st.session_state.index < len(image_urls):
    current_id = os.path.splitext(
        os.path.basename(image_urls[st.session_state.index])
    )[0]
    if current_id not in processed_ids:
        break
    st.session_state.index += 1

if st.session_state.index >= len(image_urls):
    st.success("🎉 All images in this folder are processed (annotated or deleted)!")
    st.stop()

# =========================
# TABS: ANNOTATE & REVIEW
# =========================
tab_annotate, tab_review = st.tabs(["🖊️ Annotate", "📄 Review / Edit JSON"])

# -------------------------------------------------------------------
# TAB 1: ANNOTATE
# -------------------------------------------------------------------
with tab_annotate:
    img_url = image_urls[st.session_state.index]
    img_name = os.path.basename(img_url)
    progress_text = (
        f"Image {st.session_state.index + 1}/{len(image_urls)} "
        f"| Annotated: {len(st.session_state.annotations)}"
    )
    st.subheader(f"🖼️ {progress_text}")

    col_img, col_form = st.columns([2, 3])

    with col_img:
        st.image(img_url, width=600)

    with col_form:
        with st.form(key="annotation_form", clear_on_submit=False):
            idx = st.session_state.index
            st.markdown("### 📝 Annotation Fields / Etiketleme Alanları")

            # --- TEXTS ---
            text_original = st.text_area(
                "Original Text / Asıl Metin",
                key=f"text_original_{idx}",
                placeholder="بسم الله الرحمن الرحیم",
            )
            text_latinized = st.text_area(
                "Latinized Version / Latin Yazım",
                key=f"text_latinized_{idx}",
                placeholder="Bismillahirrahmanirrahim",
            )
            text_translation_tr = st.text_area(
                "Turkish Translation / Türkçe Çeviri",
                key=f"text_translation_{idx}",
                placeholder="Rahmân ve rahîm olan Allah'ın adıyla",
            )

            # --- QURAN DETAILS ---
            st.markdown("#### 📖 Quran Details / Kur'an Bilgileri")
            surah_name = st.text_input(
                "Surah Name / Sûre Adı",
                key=f"surah_{idx}",
                placeholder="Örnek: Fatiha",
            )
            ayah_number = st.text_input(
                "Ayah Number / Ayet Numarası",
                key=f"ayah_{idx}",
                placeholder="Örnek: 1-7",
            )

            comment = st.text_area(
                "Comment / Yorum veya Not",
                key=f"comment_{idx}",
                placeholder="örnek: Yazı mihrap üzerinde yer almakta.",
            )

            submitted = st.form_submit_button(
                "💾 Save & Next / Kaydet ve Sonraki",
                use_container_width=True,
            )
            delete_btn = st.form_submit_button(
                "❌ Delete / Uygun Değil",
                use_container_width=True,
            )

    back_btn = st.button("⬅️ Back / Geri", use_container_width=True)

    # ----- BUTTON LOGIC -----
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
                "comment": comment,
            }
            st.session_state.annotations.append(entry)
            backup_and_upload_json(
                st.session_state.annotations,
                BUCKET,
                f"{selected_folder}_annotations",
                "annotations.json",
            )
            st.success("✅ Saved annotation to Supabase.")
        next_image()
        st.rerun()

    elif delete_btn:
        image_id = os.path.splitext(img_name)[0]
        st.session_state.deleted.append(
            {
                "id": image_id,
                "image_url": img_url,
                "reason": "Not suitable for labeling",
            }
        )
        backup_and_upload_json(
            st.session_state.deleted,
            BUCKET,
            f"{selected_folder}_annotations",
            "deleted.json",
        )
        st.warning(f"🗑️ {img_name} marked as deleted.")
        next_image()
        st.rerun()

    elif back_btn:
        prev_image()
        st.info("⏪ Moved back.")
        st.rerun()

# -------------------------------------------------------------------
# TAB 2: REVIEW / EDIT JSON
# -------------------------------------------------------------------
with tab_review:
    st.markdown("### 📄 Review & Edit JSON Files")

    ann_folder = f"{selected_folder}_annotations"
    ann_path = f"{ann_folder}/annotations.json"
    del_path = f"{ann_folder}/deleted.json"

    colA, colB, colC, colD = st.columns(4)
    if colA.button("🔄 Reload annotations.json"):
        st.session_state.annotations = load_existing_annotations(
            BUCKET, ann_folder, "annotations.json"
        )
        st.rerun()
    if colB.button("🔄 Reload deleted.json"):
        st.session_state.deleted = load_existing_annotations(
            BUCKET, ann_folder, "deleted.json"
        )
        st.rerun()

    # ---- DOWNLOAD BUTTONS ----
    st.subheader("⬇️ Download JSON")
    st.download_button(
        "Download annotations.json",
        data=json.dumps(
            st.session_state.annotations, ensure_ascii=False, indent=2
        ),
        file_name="annotations.json",
        mime="application/json",
        use_container_width=True,
    )
    st.download_button(
        "Download deleted.json",
        data=json.dumps(
            st.session_state.deleted, ensure_ascii=False, indent=2
        ),
        file_name="deleted.json",
        mime="application/json",
        use_container_width=True,
    )

    st.divider()

    # ---- GRID EDITOR FOR ANNOTATIONS ----
    st.subheader("🧾 Grid editor (annotations.json)")

    ann_list = normalize_records(st.session_state.annotations)
    ann_df_cols = [
        "id",
        "image_url",
        "text_original",
        "text_latinized",
        "text_translation_tr",
        "surah_name",
        "ayah_number",
        "comment",
    ]

    def to_row(d, cols):
        return {k: d.get(k, "") for k in cols}

    ann_rows = [to_row(r, ann_df_cols) for r in ann_list]

    ann_df = st.data_editor(
        ann_rows,
        key="ann_grid",
        num_rows="dynamic",
        use_container_width=True,
    )

    if st.button("💾 Save grid → annotations.json", type="primary"):
        st.session_state.annotations = [dict(row) for row in ann_df]
        backup_and_upload_json(
            st.session_state.annotations,
            BUCKET,
            ann_folder,
            "annotations.json",
        )
        st.success(
            f"Saved {len(st.session_state.annotations)} rows to annotations.json"
        )

    st.caption("Tip: you can add / remove rows in the grid, then click save.")

    st.divider()

    # ---- RAW JSON EDITOR ----
    st.subheader("✏️ Raw JSON editor (advanced)")

    raw_choice = st.radio(
        "Which file do you want to edit?",
        ["annotations.json", "deleted.json"],
        horizontal=True,
    )

    if raw_choice == "annotations.json":
        raw_initial = json.dumps(
            st.session_state.annotations, ensure_ascii=False, indent=2
        )
        keyname = "raw_ann"
    else:
        raw_initial = json.dumps(
            st.session_state.deleted, ensure_ascii=False, indent=2
        )
        keyname = "raw_del"

    raw_text = st.text_area(
        "Edit JSON below:",
        value=raw_initial,
        height=300,
        key=keyname,
    )

    if st.button("✅ Validate & Save JSON"):
        try:
            obj = json.loads(raw_text)
            obj = normalize_records(obj)

            if raw_choice == "annotations.json":
                st.session_state.annotations = obj
                backup_and_upload_json(
                    obj, BUCKET, ann_folder, "annotations.json"
                )
            else:
                st.session_state.deleted = obj
                backup_and_upload_json(
                    obj, BUCKET, ann_folder, "deleted.json"
                )

            st.success(f"Saved {len(obj)} records to {raw_choice}")
        except json.JSONDecodeError as e:
            st.error(f"Invalid JSON: {e}")
