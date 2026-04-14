# ─── ROUTES/GALLERY.PY — Galerie + Sort ──────────────────────────────────────

import re
import base64
import requests
import json
from datetime import datetime
from pathlib import Path
from flask import Blueprint, request, jsonify, send_file, send_from_directory, Response, stream_with_context

from config import EXPORT_IMG_DIR, OUTPUT_DIR, LM_STUDIO_URL, SORTS_DIR
import state

gallery_bp = Blueprint("gallery", __name__)

_ALLOWED_IMG = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


# ─── Gallery ──────────────────────────────────────────────────────────────────

@gallery_bp.route("/gallery")
def gallery_page():
    return send_from_directory("frontend", "galerie.html")


@gallery_bp.route("/api/gallery")
def list_gallery():
    subfolder = request.args.get("folder", "").strip().strip("/\\")
    if ".." in subfolder or subfolder.startswith("/"):
        return jsonify({"error": "Invalid folder"}), 400

    # merges/ is accessible as a subfolder
    base = EXPORT_IMG_DIR / subfolder if subfolder else EXPORT_IMG_DIR
    if not base.exists() or not base.is_dir():
        return jsonify({"error": "Folder not found"}), 404

    folders, images = [], []
    for item in sorted(base.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if item.is_dir():
            count = sum(1 for f in item.iterdir() if f.is_file() and f.suffix.lower() in _ALLOWED_IMG)
            rel   = f"{subfolder}/{item.name}" if subfolder else item.name
            folders.append({"name": item.name, "path": rel, "count": count})
        elif item.is_file() and item.suffix.lower() in _ALLOWED_IMG:
            rel_path = f"{subfolder}/{item.name}" if subfolder else item.name
            images.append({
                "filename": item.name,
                "path":     rel_path,
                "size_kb":  round(item.stat().st_size / 1024),
                "modified": datetime.fromtimestamp(item.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                "url":      f"/api/gallery/file?path={rel_path}",
                "thumb":    f"/api/gallery/thumb?path={rel_path}"
            })

    return jsonify({"folder": subfolder, "folders": folders, "images": images, "total": len(images)})


@gallery_bp.route("/api/gallery/file")
def serve_gallery_file():
    rel = request.args.get("path", "").strip().strip("/\\")
    if ".." in rel or not rel:
        return "Invalid path", 400
    path = EXPORT_IMG_DIR / rel
    if path.exists() and path.is_file():
        return send_file(path)
    return "Not found", 404


@gallery_bp.route("/api/gallery/thumb")
def serve_gallery_thumb():
    from PIL import Image as PILImage
    import io
    rel = request.args.get("path", "").strip().strip("/\\")
    if ".." in rel or not rel:
        return "Invalid path", 400
    size = int(request.args.get("size", 256))
    src  = EXPORT_IMG_DIR / rel
    if not src.exists() or not src.is_file():
        return "Not found", 404

    # Cache path
    thumb_dir  = EXPORT_IMG_DIR / ".thumbs" / str(size)
    thumb_path = thumb_dir / (rel.replace("/", "_").replace("\\", "_"))
    thumb_dir.mkdir(parents=True, exist_ok=True)

    # Return cached if fresh
    if thumb_path.exists() and thumb_path.stat().st_mtime >= src.stat().st_mtime:
        return send_file(thumb_path, mimetype="image/jpeg")

    try:
        img = PILImage.open(src).convert("RGB")
        img.thumbnail((size, size), PILImage.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=82)
        thumb_path.write_bytes(buf.getvalue())
        buf.seek(0)
        return send_file(buf, mimetype="image/jpeg")
    except Exception as e:
        return str(e), 500


@gallery_bp.route("/api/gallery/delete", methods=["DELETE"])
def delete_gallery_file():
    rel = request.args.get("path", "").strip().strip("/\\")
    if ".." in rel or not rel:
        return jsonify({"error": "Invalid path"}), 400
    path = EXPORT_IMG_DIR / rel
    if not path.exists() or not path.is_file():
        return jsonify({"error": "Not found"}), 404
    path.unlink()
    # Remove thumb if exists
    for size in (256, 512):
        t = EXPORT_IMG_DIR / ".thumbs" / str(size) / (rel.replace("/","_").replace("\\","_"))
        if t.exists(): t.unlink()
    print(f"[Gallery] Deleted: {rel}")
    return jsonify({"ok": True})


@gallery_bp.route("/api/gallery/delete-batch", methods=["POST"])
def delete_gallery_batch():
    paths = (request.get_json() or {}).get("paths", [])
    deleted, errors = 0, []
    for rel in paths:
        rel = rel.strip().strip("/\\")
        if ".." in rel or not rel:
            errors.append(rel); continue
        path = EXPORT_IMG_DIR / rel
        if path.exists() and path.is_file():
            path.unlink()
            for size in (256, 512):
                t = EXPORT_IMG_DIR / ".thumbs" / str(size) / (rel.replace("/","_").replace("\\","_"))
                if t.exists(): t.unlink()
            deleted += 1
        else:
            errors.append(rel)
    print(f"[Gallery] Batch delete: {deleted} deleted, {len(errors)} errors")
    return jsonify({"ok": True, "deleted": deleted, "errors": errors})


@gallery_bp.route("/download/<filename>")
def download(filename):
    safe = re.sub(r'[<>:"/\\|?*]', '_', filename)
    path = OUTPUT_DIR / safe
    if path.exists():
        return send_file(path, as_attachment=True)
    return "File not found", 404




# ─── Auto-Tagging ──────────────────────────────────────────────────────────────

_TAG_SYSTEM = """You are an image tagging assistant. Analyze the image or prompt and output Danbooru-style tags.
Rules:
- Output ONLY comma-separated tags, nothing else
- 5-15 tags maximum
- Lowercase, underscores for spaces (e.g. long_hair, blue_eyes)
- Cover: subject, style, colors, mood, composition
- Keep tags short: 1-2 words each
- No explanations, no sentences, no punctuation except commas"""


def _read_tags(img_path: Path) -> list:
    tag_file = img_path.with_suffix('.tags.json')
    if tag_file.exists():
        try: return json.loads(tag_file.read_text(encoding='utf-8'))
        except: pass
    return []


def _write_tags(img_path: Path, tags: list):
    tag_file = img_path.with_suffix('.tags.json')
    tag_file.write_text(json.dumps(tags, ensure_ascii=False), encoding='utf-8')


@gallery_bp.route("/api/gallery/tags")
def get_image_tags():
    rel = request.args.get("path", "").strip().strip("/\\")
    if ".." in rel or not rel:
        return jsonify({"error": "Invalid"}), 400
    tags = _read_tags(EXPORT_IMG_DIR / rel)
    return jsonify({"tags": tags})


@gallery_bp.route("/api/gallery/tags", methods=["POST"])
def save_image_tags():
    data = request.get_json() or {}
    rel  = data.get("path", "").strip().strip("/\\")
    tags = data.get("tags", [])
    if ".." in rel or not rel:
        return jsonify({"error": "Invalid"}), 400
    _write_tags(EXPORT_IMG_DIR / rel, tags)
    return jsonify({"ok": True})


@gallery_bp.route("/api/gallery/tag-image", methods=["POST"])
def tag_single_image():
    """Tag a single image. Returns tags array."""
    data        = request.get_json() or {}
    rel         = data.get("path", "").strip().strip("/\\")
    use_vision  = bool(data.get("use_vision", True))
    vision_size = data.get("vision_size", "512")

    if ".." in rel or not rel:
        return jsonify({"error": "Invalid"}), 400

    img_path = EXPORT_IMG_DIR / rel
    if not img_path.exists():
        return jsonify({"error": "Not found"}), 404

    try:
        from routes.workflows import extract_positive_prompt_from_png
        image_b64, mime, prompt_text = "", "image/png", ""

        if use_vision:
            img_bytes = img_path.read_bytes()
            if vision_size in ("256", "512", "768"):
                from PIL import Image as PILImage
                import io
                size    = int(vision_size)
                img_obj = PILImage.open(io.BytesIO(img_bytes)).convert("RGB")
                img_obj.thumbnail((size, size), PILImage.LANCZOS)
                buf = io.BytesIO()
                img_obj.save(buf, format="JPEG", quality=85)
                img_bytes = buf.getvalue()
            image_b64 = base64.b64encode(img_bytes).decode("utf-8")
            mime      = "image/jpeg"
        else:
            prompt_text = extract_positive_prompt_from_png(img_path.read_bytes()) or img_path.stem

        if use_vision and image_b64:
            user_content = [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
                {"type": "text", "text": "Output only comma-separated Danbooru tags for this image."}
            ]
        else:
            user_content = f"Image prompt: {prompt_text}\n\nOutput only comma-separated Danbooru-style tags."

        resp = requests.post(LM_STUDIO_URL, json={
            "model":       state.active_model["name"],
            "messages":    [{"role": "system", "content": _TAG_SYSTEM},
                            {"role": "user",   "content": user_content}],
            "temperature": 0.1, "max_tokens": 80, "stream": False
        }, timeout=60)
        raw  = resp.json()["choices"][0]["message"].get("content", "").strip()
        raw  = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
        tags = [t.strip().lower().replace(' ', '_') for t in raw.split(',') if t.strip()][:15]
        _write_tags(img_path, tags)
        return jsonify({"ok": True, "tags": tags})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@gallery_bp.route("/api/gallery/tag-batch", methods=["POST"])
def tag_batch():
    """SSE: tag all images in a folder."""
    data        = request.get_json() or {}
    folder      = data.get("folder", "").strip().strip("/\\")
    use_vision  = bool(data.get("use_vision", True))
    vision_size = data.get("vision_size", "512")
    overwrite   = bool(data.get("overwrite", False))
    batch_size  = max(1, min(20, int(data.get("batch_size", 3))))

    if ".." in folder:
        return jsonify({"error": "Invalid"}), 400

    src    = EXPORT_IMG_DIR / folder if folder else EXPORT_IMG_DIR
    images = [f for f in src.iterdir() if f.is_file() and f.suffix.lower() in _ALLOWED_IMG]

    def run():
        if not images:
            yield "data: " + json.dumps({"type": "done", "text": "Keine Bilder."}) + "\n\n"
            return

        from concurrent.futures import ThreadPoolExecutor, as_completed

        yield "data: " + json.dumps({"type": "info", "text": f"🏷️ {len(images)} Bilder — {batch_size} parallel"}) + "\n\n"
        done = 0

        def _process(img_path):
            from routes.workflows import extract_positive_prompt_from_png
            image_b64, mime, prompt_text = "", "image/png", ""
            if use_vision:
                img_bytes = img_path.read_bytes()
                if vision_size in ("256", "512", "768"):
                    from PIL import Image as PILImage
                    import io
                    sz      = int(vision_size)
                    img_obj = PILImage.open(io.BytesIO(img_bytes)).convert("RGB")
                    img_obj.thumbnail((sz, sz), PILImage.LANCZOS)
                    buf = io.BytesIO()
                    img_obj.save(buf, format="JPEG", quality=85)
                    img_bytes = buf.getvalue()
                image_b64 = base64.b64encode(img_bytes).decode("utf-8")
                mime      = "image/jpeg"
            else:
                prompt_text = extract_positive_prompt_from_png(img_path.read_bytes()) or img_path.stem
            user_content = [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
                {"type": "text", "text": "Output only comma-separated Danbooru tags."}
            ] if (use_vision and image_b64) else f"Image prompt: {prompt_text}\n\nOutput only comma-separated Danbooru-style tags."
            resp = requests.post(LM_STUDIO_URL, json={
                "model": state.active_model["name"],
                "messages": [{"role": "system", "content": _TAG_SYSTEM},
                             {"role": "user",   "content": user_content}],
                "temperature": 0.1, "max_tokens": 80, "stream": False
            }, timeout=60)
            raw  = resp.json()["choices"][0]["message"].get("content", "").strip()
            raw  = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
            return [t.strip().lower().replace(' ', '_') for t in raw.split(',') if t.strip()][:15]

        for batch_start in range(0, len(images), batch_size):
            batch = images[batch_start:batch_start + batch_size]

            # Skip already-tagged in this batch
            to_process = []
            for img_path in batch:
                if not overwrite and _read_tags(img_path):
                    yield "data: " + json.dumps({"type": "skip", "text": f"⏭️ {img_path.name}"}) + "\n\n"
                else:
                    to_process.append(img_path)

            if not to_process:
                continue

            yield "data: " + json.dumps({"type": "progress",
                "current": batch_start + len(batch), "total": len(images),
                "text": f"[{batch_start+1}–{batch_start+len(batch)}/{len(images)}] Analysiere..."}) + "\n\n"

            with ThreadPoolExecutor(max_workers=len(to_process)) as ex:
                futures = {ex.submit(_process, img_path): img_path for img_path in to_process}
                for future in as_completed(futures):
                    img_path = futures[future]
                    rel = str(img_path.relative_to(EXPORT_IMG_DIR)).replace('\\', '/')
                    try:
                        tags = future.result()
                        _write_tags(img_path, tags)
                        done += 1
                        yield "data: " + json.dumps({"type": "tagged", "path": rel, "tags": tags,
                            "text": f"✅ {img_path.name}: {', '.join(tags[:5])}"}) + "\n\n"
                    except Exception as e:
                        yield "data: " + json.dumps({"type": "warn", "text": f"⚠️ {img_path.name}: {e}"}) + "\n\n"

        yield "data: " + json.dumps({"type": "done", "text": f"✅ {done}/{len(images)} Bilder getaggt."}) + "\n\n"

    return Response(stream_with_context(run()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ─── Sort Presets ─────────────────────────────────────────────────────────────

@gallery_bp.route("/api/sorts", methods=["GET"])
def list_sort_presets():
    presets = []
    if SORTS_DIR.exists():
        for f in sorted(SORTS_DIR.iterdir()):
            if f.is_file() and f.suffix.lower() == ".txt":
                presets.append({
                    "name":    f.stem,
                    "content": f.read_text(encoding="utf-8").strip()
                })
    return jsonify({"presets": presets})


# ─── Sort ─────────────────────────────────────────────────────────────────────

@gallery_bp.route("/sort")
def sort_page():
    return send_from_directory("frontend", "sort.html")


@gallery_bp.route("/api/sort/run", methods=["POST"])
def sort_run():
    data          = request.get_json() or {}
    user_instr    = data.get("instruction", "").strip()
    use_vision    = bool(data.get("use_vision", False))
    vision_size   = data.get("vision_size", "512")
    source_folder = data.get("source_folder", "").strip().strip("/\\")
    batch_size    = max(1, min(10, int(data.get("batch_size", 1))))

    if ".." in source_folder:
        return jsonify({"error": "Invalid folder"}), 400

    source_dir  = EXPORT_IMG_DIR / source_folder if source_folder else EXPORT_IMG_DIR
    sorted_base = EXPORT_IMG_DIR / "sorted"
    sorted_base.mkdir(exist_ok=True)

    images = [f for f in source_dir.iterdir() if f.is_file() and f.suffix.lower() == ".png"]

    def process_one(img_path, idx):
        from routes.workflows import extract_positive_prompt_from_png
        events      = []
        prompt_text = ""
        image_b64   = ""
        mime        = "image/png"

        if use_vision:
            try:
                img_bytes = img_path.read_bytes()
                if vision_size in ("512", "256"):
                    from PIL import Image as PILImage
                    import io
                    size    = int(vision_size)
                    img_obj = PILImage.open(io.BytesIO(img_bytes)).convert("RGB")
                    img_obj.thumbnail((size, size), PILImage.LANCZOS)
                    buf = io.BytesIO()
                    img_obj.save(buf, format="JPEG", quality=85)
                    img_bytes = buf.getvalue()
                image_b64 = base64.b64encode(img_bytes).decode("utf-8")
                mime      = "image/jpeg" if vision_size != "original" else "image/png"
            except Exception as e:
                events.append({"type": "warn", "text": f"⚠️ Bild laden fehlgeschlagen: {e}"})
        else:
            try:
                prompt_text = extract_positive_prompt_from_png(img_path.read_bytes())
                if prompt_text:
                    events.append({"type": "info", "text": f"✅ Prompt: {prompt_text[:80]}..."})
            except Exception as e:
                events.append({"type": "warn", "text": f"⚠️ {type(e).__name__}: {e}"})

            if not prompt_text:
                stem  = img_path.stem
                clean = re.sub(r'^\d{8}_\d{6}_?', '', stem)
                clean = re.sub(r'_+\d{4,6}_?$', '', clean)
                clean = re.sub(r'_+', '_', clean).strip('_')
                prompt_text = clean or stem
                events.append({"type": "warn", "text": f"⚠️ {img_path.name}: Slug: '{prompt_text}'"})

        existing_folders = sorted([d.name for d in sorted_base.iterdir() if d.is_dir()]) if sorted_base.exists() else []

        folder_name = "misc"
        try:
            if user_instr:
                sys_prompt = f"""Your task: {user_instr}

Apply this rule to the image and output a folder name.
Rules:
- Output ONLY the folder name, nothing else, no explanation
- Lowercase, underscores instead of spaces, max 20 chars
- If the result fits an existing folder, use that EXACT name
- Keep it short: 1-2 words maximum"""
            else:
                sys_prompt = """Assign this image to a folder based on its visual style or subject.
Output ONLY the folder name — lowercase, underscores, max 2 words, no explanation.
If an existing folder fits, use that EXACT name. Keep names broad and reusable."""

            existing = ', '.join(existing_folders) if existing_folders else 'none'
            if use_vision and image_b64:
                user_content = [
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
                    {"type": "text", "text": f"Existing folders: {existing}\n\nOutput only the folder name."}
                ]
            else:
                user_content = f"Image prompt: {prompt_text}\n\nExisting folders: {existing}"

            resp = requests.post(LM_STUDIO_URL, json={
                "model":       state.active_model["name"],
                "messages":    [{"role": "system", "content": sys_prompt},
                                {"role": "user",   "content": user_content}],
                "temperature": 0.1,
                "max_tokens":  20,
                "stream":      False
            }, timeout=60)
            raw         = resp.json()["choices"][0]["message"].get("content", "").strip()
            raw         = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
            folder_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', raw.lower().strip())[:40] or "misc"
        except Exception as e:
            events.append({"type": "warn", "text": f"⚠️ LLM: {e}"})

        return events, folder_name, img_path

    def run():
        from concurrent.futures import ThreadPoolExecutor, as_completed

        if not images:
            yield "data: " + json.dumps({"type": "done", "text": "Keine Bilder zum Sortieren."}) + "\n\n"
            return

        yield "data: " + json.dumps({"type": "info", "text": f"📦 {len(images)} Bilder gefunden. Parallelität: {batch_size}"}) + "\n\n"

        completed = 0
        for batch_start in range(0, len(images), batch_size):
            batch = [(img, idx) for idx, img in enumerate(images[batch_start:batch_start + batch_size], batch_start + 1)]

            for img_path, idx in batch:
                yield "data: " + json.dumps({
                    "type": "progress", "current": idx, "total": len(images),
                    "text": f"🔍 [{idx}/{len(images)}] {img_path.name}"
                }) + "\n\n"

            with ThreadPoolExecutor(max_workers=batch_size) as ex:
                futures = {ex.submit(process_one, img_path, idx): (img_path, idx) for img_path, idx in batch}
                for future in as_completed(futures):
                    img_path, idx = futures[future]
                    try:
                        events, folder_name, img_path = future.result()
                    except Exception as e:
                        yield "data: " + json.dumps({"type": "warn", "text": f"⚠️ {img_path.name}: {e}"}) + "\n\n"
                        continue

                    for ev in events:
                        yield "data: " + json.dumps(ev) + "\n\n"

                    target_dir  = sorted_base / folder_name
                    target_dir.mkdir(exist_ok=True)
                    target_path = target_dir / img_path.name
                    if target_path.exists():
                        target_path = target_dir / f"{img_path.stem}_{idx}.png"
                    try:
                        img_path.rename(target_path)
                        completed += 1
                        yield "data: " + json.dumps({
                            "type": "moved", "file": img_path.name,
                            "folder": folder_name,
                            "text": f"✅ {img_path.name} → {folder_name}/"
                        }) + "\n\n"
                    except Exception as e:
                        yield "data: " + json.dumps({"type": "warn", "text": f"⚠️ Verschieben fehlgeschlagen: {e}"}) + "\n\n"

        yield "data: " + json.dumps({"type": "done", "text": f"✅ Fertig — {completed}/{len(images)} Bilder sortiert."}) + "\n\n"

    return Response(stream_with_context(run()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@gallery_bp.route("/api/sort/unsort", methods=["POST"])
def sort_unsort():
    sorted_base = EXPORT_IMG_DIR / "sorted"
    if not sorted_base.exists():
        return jsonify({"ok": True, "moved": 0, "text": "Kein sorted/ Ordner vorhanden."})

    moved, conflicts = 0, 0
    for subdir in sorted_base.iterdir():
        if not subdir.is_dir(): continue
        if subdir.name == "merges": continue  # protected
        for f in subdir.iterdir():
            if not f.is_file(): continue
            target = EXPORT_IMG_DIR / f.name
            if target.exists():
                target = EXPORT_IMG_DIR / f"{f.stem}_unsorted{f.suffix}"
                conflicts += 1
            f.rename(target)
            moved += 1

    for subdir in sorted_base.iterdir():
        if subdir.is_dir():
            try: subdir.rmdir()
            except Exception: pass
    try: sorted_base.rmdir()
    except Exception: pass

    print(f"[Sort] Unsort: {moved} Bilder zurückverschoben, {conflicts} Konflikte umbenannt")
    return jsonify({"ok": True, "moved": moved, "conflicts": conflicts,
                    "text": f"✅ {moved} Bilder zurückverschoben{f' ({conflicts} umbenannt)' if conflicts else ''}."})