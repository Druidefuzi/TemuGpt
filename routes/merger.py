# ─── ROUTES/MERGER.PY — Model Merger (ComfyUI) ───────────────────────────────

import base64
import re
from datetime import datetime
from pathlib import Path
from flask import Blueprint, request, jsonify, send_from_directory, send_file

from config import EXPORT_IMG_DIR

merger_bp = Blueprint("merger", __name__)

MERGES_DIR = EXPORT_IMG_DIR / "merges"


@merger_bp.route("/merger")
def merger_page():
    return send_from_directory("frontend", "merger.html")


@merger_bp.route("/api/merger/save-image", methods=["POST"])
def save_merge_image():
    data   = request.get_json() or {}
    img_b64 = data.get("image_b64", "").strip()
    name    = data.get("name", "").strip()
    if not img_b64:
        return jsonify({"error": "No image"}), 400

    MERGES_DIR.mkdir(parents=True, exist_ok=True)
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe     = re.sub(r'[^a-zA-Z0-9_\-]', '_', name)[:40] if name else "merge"
    filename = f"{ts}_{safe}.png"
    path     = MERGES_DIR / filename
    path.write_bytes(base64.b64decode(img_b64))
    print(f"[Merger] Saved: {path}")
    return jsonify({"ok": True, "filename": filename, "path": str(path)})


@merger_bp.route("/api/merger/images")
def list_merge_images():
    if not MERGES_DIR.exists():
        return jsonify({"images": []})
    allowed = {".png", ".jpg", ".jpeg", ".webp"}
    images  = []
    for f in sorted(MERGES_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.is_file() and f.suffix.lower() in allowed:
            images.append({
                "filename": f.name,
                "path":     f"merges/{f.name}",
                "url":      f"/api/gallery/file?path=merges/{f.name}",
                "size_kb":  round(f.stat().st_size / 1024),
            })
    return jsonify({"images": images})
