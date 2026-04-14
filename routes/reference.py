# ─── ROUTES/REFERENCE.PY — Artist Reference Gallery ──────────────────────────

from flask import Blueprint, request, jsonify, send_file, send_from_directory
from config import REFERENCE_DIR

reference_bp = Blueprint("reference", __name__)

_ALLOWED_IMG = {".png", ".jpg", ".jpeg", ".webp"}


@reference_bp.route("/reference")
def reference_page():
    return send_from_directory("frontend", "reference.html")


@reference_bp.route("/api/reference/models")
def list_models():
    models = []
    if REFERENCE_DIR.exists():
        for d in sorted(REFERENCE_DIR.iterdir()):
            if d.is_dir():
                models.append(d.name)
    return jsonify({"models": models or ["illustrious", "anima"]})


@reference_bp.route("/api/reference/artists")
def list_artists():
    model = request.args.get("model", "").strip().strip("/\\")
    if not model or ".." in model:
        return jsonify({"error": "Invalid model"}), 400

    model_dir = REFERENCE_DIR / model
    if not model_dir.exists():
        return jsonify({"artists": []})

    # Read artist names from model-level artists.txt
    artists_txt = model_dir / "artists.txt"
    if not artists_txt.exists():
        return jsonify({"artists": []})

    names = [line.strip() for line in artists_txt.read_text(encoding="utf-8-sig").splitlines()
             if line.strip()]

    # Scan existing dirs for image counts
    counts = {}
    for d in model_dir.iterdir():
        if d.is_dir():
            counts[d.name] = sum(
                1 for f in d.iterdir()
                if f.is_file() and f.suffix.lower() in _ALLOWED_IMG
            )
    counts_lower = {k.lower(): v for k, v in counts.items()}

    def get_count(name):
        return counts.get(name) or counts_lower.get(name.lower(), 0)

    artists = [{"name": name, "img_count": get_count(name)} for name in names]
    artists.sort(key=lambda x: x["img_count"], reverse=True)
    return jsonify({"artists": artists})


@reference_bp.route("/api/reference/images")
def list_images():
    model  = request.args.get("model",  "").strip().strip("/\\")
    artist = request.args.get("artist", "").strip().strip("/\\")
    if not model or ".." in model or ".." in artist:
        return jsonify({"error": "Invalid params"}), 400

    model_dir = REFERENCE_DIR / model
    if not model_dir.exists():
        return jsonify({"images": []})

    # No artist selected → all images from all artist subfolders
    if not artist:
        images = []
        for d in sorted(model_dir.iterdir()):
            if not d.is_dir():
                continue
            for f in sorted(d.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
                if f.is_file() and f.suffix.lower() in _ALLOWED_IMG:
                    images.append({
                        "filename": f.name,
                        "artist":   d.name,
                        "url":      f"/api/reference/image?model={model}&artist={d.name}&file={f.name}",
                        "size_kb":  round(f.stat().st_size / 1024)
                    })
        images.sort(key=lambda x: x["artist"])
        return jsonify({"images": images})

    artist_dir = model_dir / artist
    if not artist_dir.exists():
        return jsonify({"images": []})

    images = []
    for f in sorted(artist_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.is_file() and f.suffix.lower() in _ALLOWED_IMG:
            images.append({
                "filename": f.name,
                "artist":   artist,
                "url":      f"/api/reference/image?model={model}&artist={artist}&file={f.name}",
                "size_kb":  round(f.stat().st_size / 1024)
            })
    return jsonify({"images": images})


@reference_bp.route("/api/reference/image")
def serve_image():
    model  = request.args.get("model",  "").strip().strip("/\\")
    artist = request.args.get("artist", "").strip().strip("/\\")
    file   = request.args.get("file",   "").strip()
    if not all([model, artist, file]) or ".." in f"{model}{artist}{file}" or "/" in file or "\\" in file:
        return "Invalid", 400
    path = REFERENCE_DIR / model / artist / file
    if path.exists() and path.is_file():
        return send_file(path)
    return "Not found", 404