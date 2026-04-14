# ─── ROUTES/COMFY.PY — ComfyUI-Endpoints + Styles/Themes/Characters ──────────

import requests
from flask import Blueprint, request, jsonify, Response, stream_with_context
import json

from config import COMFY_URL, STYLES_DIR, THEMES_DIR, CHARACTERS_DIR, WILDCARDS_DIR
from comfy_backend import comfy_get_models, comfy_get_models_by_type
import state

comfy_bp = Blueprint("comfy", __name__)


# ─── ComfyUI ──────────────────────────────────────────────────────────────────

@comfy_bp.route("/api/comfy/generate", methods=["POST"])
def api_comfy_generate():
    data         = request.json
    prompt_text  = data.get("prompt", "")
    if not prompt_text:
        return jsonify({"ok": False, "error": "No prompt provided"}), 400

    def generate():
        yield "data: " + json.dumps({"type": "step", "text": "🎨 Connecting to ComfyUI...", "status": "active"}) + "\n\n"
        models = comfy_get_models()
        if not models:
            yield "data: " + json.dumps({"type": "step", "text": "⚠️ No models found", "status": "done"}) + "\n\n"
        else:
            yield "data: " + json.dumps({"type": "step", "text": f"🤖 Modell: {models[0].split(chr(92))[-1].split('/')[-1]}", "status": "done"}) + "\n\n"
        yield "data: " + json.dumps({"type": "done"}) + "\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@comfy_bp.route("/api/comfy/models", methods=["GET"])
def api_comfy_models():
    return jsonify({"models": comfy_get_models()})


@comfy_bp.route("/api/comfy/image-models", methods=["GET"])
def api_comfy_image_models():
    model_type = request.args.get("type", "anima")
    return jsonify({"models": comfy_get_models_by_type(model_type), "type": model_type})


@comfy_bp.route("/api/comfy/all-checkpoints", methods=["GET"])
def api_comfy_all_checkpoints():
    try:
        checkpoints, unets = [], []
        r = requests.get(f"{COMFY_URL}/object_info/CheckpointLoaderSimple", timeout=5)
        if r.ok:
            checkpoints = r.json().get("CheckpointLoaderSimple", {}).get("input", {}).get("required", {}).get("ckpt_name", [None])[0] or []
        r2 = requests.get(f"{COMFY_URL}/object_info/UNETLoader", timeout=5)
        if r2.ok:
            unets = r2.json().get("UNETLoader", {}).get("input", {}).get("required", {}).get("unet_name", [None])[0] or []
        return jsonify({"checkpoints": checkpoints, "unets": unets})
    except Exception as e:
        return jsonify({"checkpoints": [], "unets": [], "error": str(e)})


@comfy_bp.route("/api/comfy/all-loras", methods=["GET"])
def api_comfy_all_loras():
    try:
        r = requests.get(f"{COMFY_URL}/object_info/LoraLoader", timeout=5)
        if r.ok:
            loras = r.json().get("LoraLoader", {}).get("input", {}).get("required", {}).get("lora_name", [None])[0] or []
            return jsonify({"loras": loras})
        return jsonify({"loras": []})
    except Exception as e:
        return jsonify({"loras": [], "error": str(e)})


# ─── Wildcards / Styles / Themes / Characters ─────────────────────────────────

@comfy_bp.route("/api/wildcards", methods=["GET"])
def list_wildcards():
    wildcards = []
    for folder in ("prepend", "replace"):
        d = WILDCARDS_DIR / folder
        if d.exists():
            for f in sorted(d.iterdir()):
                if f.is_file() and f.suffix.lower() == ".txt":
                    wildcards.append({"name": f.stem, "folder": folder})
    return jsonify({"wildcards": wildcards})


@comfy_bp.route("/api/styles", methods=["GET"])
def list_styles():
    styles = []
    if STYLES_DIR.exists():
        for f in sorted(STYLES_DIR.iterdir()):
            if f.is_file() and f.suffix.lower() == ".txt" and not f.name.startswith("_"):
                styles.append(f.stem)
    return jsonify({"styles": styles})


@comfy_bp.route("/api/themes", methods=["GET"])
def list_themes():
    themes = []
    if THEMES_DIR.exists():
        for f in sorted(THEMES_DIR.iterdir()):
            if f.is_file() and f.suffix.lower() == ".txt" and not f.name.startswith("_"):
                themes.append(f.stem)
    return jsonify({"themes": themes})


@comfy_bp.route("/api/characters", methods=["GET"])
def list_characters():
    characters = []
    if CHARACTERS_DIR.exists():
        for f in sorted(CHARACTERS_DIR.iterdir()):
            if f.is_file() and f.suffix.lower() == ".txt" and not f.name.startswith("_"):
                characters.append(f.stem)
    return jsonify({"characters": characters})


@comfy_bp.route("/api/image-style", methods=["GET", "POST"])
def image_style():
    if request.method == "POST":
        data = request.get_json() or {}
        state.active_image_style = data.get("style") or None
        print(f"[Style] Active: {state.active_image_style or 'default'}")
        return jsonify({"ok": True, "style": state.active_image_style})
    return jsonify({"style": getattr(state, "active_image_style", None)})


@comfy_bp.route("/api/image-theme", methods=["GET", "POST"])
def image_theme():
    if request.method == "POST":
        data = request.get_json() or {}
        state.active_image_theme = data.get("theme") or None
        print(f"[Theme] Active: {state.active_image_theme or 'none'}")
        return jsonify({"ok": True, "theme": state.active_image_theme})
    return jsonify({"theme": getattr(state, "active_image_theme", None)})


@comfy_bp.route("/api/image-character", methods=["GET", "POST"])
def image_character():
    if request.method == "POST":
        data = request.get_json() or {}
        state.active_image_character = data.get("character") or None
        print(f"[Character] Active: {state.active_image_character or 'none'}")
        return jsonify({"ok": True, "character": state.active_image_character})
    return jsonify({"character": getattr(state, "active_image_character", None)})
