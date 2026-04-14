# ─── ROUTES/PERSONALITY.PY — Personality Management ──────────────────────────

import re
import json
import base64
import requests
from pathlib import Path
from flask import Blueprint, request, jsonify, send_file, send_from_directory, Response, stream_with_context

from config import PERSONALITY_DIR, LM_STUDIO_URL
import state

personality_bp = Blueprint("personality", __name__)

_LOGO_TEMPLATE = (
    "masterpiece, best quality, score_7, minimalist app icon, "
    "{subject}, "
    "dark elegant background, #0f0f17, soft vignette, clean design, "
    "vector art, flat illustration, digital art, modern aesthetic, "
    "no clutter, isolated on black, high contrast, stylized, anime style, "
    "cute character, friendly expression, tech theme, minimalist icon design"
)

_DESCRIPTION_SYSTEM = """You write a short welcome screen tagline for an AI assistant.
The user provides the assistant's personality text. Write ONE sentence (max 15 words) that a user sees
when opening a new chat — something inviting that fits the personality's tone and character.
Do NOT start with "I". Do NOT use quotes. Output plain text only, no JSON, no markdown."""


_PERSONALITY_SYSTEM = """You generate personality descriptions for an AI assistant.
The user describes the desired personality. Output ONLY the personality text -- 2-3 sentences max.
Start with "You are [description]." followed by personality traits, communication style, and quirks.
Do NOT include any rules, capabilities, or technical instructions -- only the personality itself.
Output plain text, no JSON, no markdown."""


@personality_bp.route("/personality")
def personality_page():
    return send_from_directory("frontend", "personality.html")


@personality_bp.route("/api/personalities")
def list_personalities():
    personalities = []
    if PERSONALITY_DIR.exists():
        for d in sorted(PERSONALITY_DIR.iterdir()):
            if not d.is_dir():
                continue
            txt  = d / "personality.txt"
            logo = d / "logo.png"
            desc = d / "description.txt"
            tts  = d / "tts_voice.txt"
            personalities.append({
                "name":            d.name,
                "has_text":        txt.exists(),
                "has_logo":        logo.exists(),
                "has_description": desc.exists(),
                "description":     desc.read_text(encoding="utf-8").strip() if desc.exists() else "",
                "tts_voice":       tts.read_text(encoding="utf-8").strip() if tts.exists() else "",
                "preview":         txt.read_text(encoding="utf-8").strip()[:120] if txt.exists() else ""
            })
    return jsonify({"personalities": personalities, "active": state.active_personality})


@personality_bp.route("/api/personalities/active", methods=["GET"])
def get_active():
    return jsonify({"active": state.active_personality})


@personality_bp.route("/api/personalities/active", methods=["POST"])
def set_active():
    name = (request.get_json() or {}).get("name", "").strip()
    if not name or ".." in name:
        return jsonify({"error": "Invalid name"}), 400
    state.active_personality = name
    from state import save_state
    save_state()
    print(f"[Personality] Active: {name}")
    return jsonify({"ok": True, "active": name})


@personality_bp.route("/api/personalities/<name>/logo")
def serve_logo(name):
    if ".." in name:
        return "Invalid", 400
    logo = PERSONALITY_DIR / name / "logo.png"
    if logo.exists():
        return send_file(logo, mimetype="image/png")
    return send_file(Path("frontend/assets/logo.png"))


@personality_bp.route("/api/personalities/<name>/text")
def serve_text(name):
    if ".." in name:
        return jsonify({"error": "Invalid"}), 400
    txt = PERSONALITY_DIR / name / "personality.txt"
    if txt.exists():
        return jsonify({"text": txt.read_text(encoding="utf-8").strip()})
    return jsonify({"text": ""})


@personality_bp.route("/api/personalities/generate-text", methods=["POST"])
def generate_personality_text():
    desc = (request.get_json() or {}).get("description", "").strip()
    if not desc:
        return jsonify({"error": "No description"}), 400

    def stream():
        try:
            resp = requests.post(LM_STUDIO_URL, json={
                "model":       state.active_model["name"],
                "messages":    [
                    {"role": "system", "content": _PERSONALITY_SYSTEM},
                    {"role": "user",   "content": desc}
                ],
                "temperature": 0.7,
                "max_tokens":  200,
                "stream":      True
            }, stream=True, timeout=60)
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                line = line.decode("utf-8")
                if line.startswith("data: "):
                    line = line[6:]
                if line == "[DONE]":
                    yield "data: " + json.dumps({"type": "done"}) + "\n\n"
                    break
                try:
                    chunk = json.loads(line)
                    delta = chunk["choices"][0].get("delta", {})
                    if delta.get("content"):
                        yield "data: " + json.dumps({"type": "token", "text": delta["content"]}) + "\n\n"
                except Exception:
                    continue
        except Exception as e:
            yield "data: " + json.dumps({"type": "error", "text": str(e)}) + "\n\n"

    return Response(stream_with_context(stream()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@personality_bp.route("/api/personalities/save", methods=["POST"])
def save_personality():
    data    = request.get_json() or {}
    name    = re.sub(r'[^a-zA-Z0-9_\-]', '_', data.get("name", "").strip()).strip('_')
    content = data.get("content", "").strip()
    if not name or not content:
        return jsonify({"error": "Name and content required"}), 400
    folder = PERSONALITY_DIR / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "personality.txt").write_text(content, encoding="utf-8")
    print(f"[Personality] Saved: {name}")
    return jsonify({"ok": True, "name": name})


@personality_bp.route("/api/personalities/save-logo", methods=["POST"])
def save_logo():
    data    = request.get_json() or {}
    name    = re.sub(r'[^a-zA-Z0-9_\-]', '_', data.get("name", "").strip()).strip('_')
    img_b64 = data.get("image_b64", "").strip()
    if not name or not img_b64:
        return jsonify({"error": "Name and image required"}), 400
    folder = PERSONALITY_DIR / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "logo.png").write_bytes(base64.b64decode(img_b64))
    print(f"[Personality] Logo saved: {name}")
    return jsonify({"ok": True})


@personality_bp.route("/api/personalities/logo-prompt", methods=["POST"])
def build_logo_prompt():
    subject = (request.get_json() or {}).get("subject", "").strip()
    if not subject:
        return jsonify({"error": "No subject"}), 400
    prompt = _LOGO_TEMPLATE.format(subject=subject)
    return jsonify({"prompt": prompt})


@personality_bp.route("/api/personalities/<name>/description")
def serve_description(name):
    if ".." in name:
        return jsonify({"error": "Invalid"}), 400
    desc = PERSONALITY_DIR / name / "description.txt"
    if desc.exists():
        return jsonify({"description": desc.read_text(encoding="utf-8").strip()})
    return jsonify({"description": ""})


@personality_bp.route("/api/personalities/save-description", methods=["POST"])
def save_description():
    data    = request.get_json() or {}
    name    = re.sub(r'[^a-zA-Z0-9_\-]', '_', data.get("name", "").strip()).strip('_')
    content = data.get("content", "").strip()
    if not name or not content:
        return jsonify({"error": "Name and content required"}), 400
    folder = PERSONALITY_DIR / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "description.txt").write_text(content, encoding="utf-8")
    print(f"[Personality] Description saved: {name}")
    return jsonify({"ok": True})


@personality_bp.route("/api/personalities/generate-description", methods=["POST"])
def generate_description():
    personality_text = (request.get_json() or {}).get("personality_text", "").strip()
    if not personality_text:
        return jsonify({"error": "No personality text"}), 400

    def stream():
        try:
            resp = requests.post(LM_STUDIO_URL, json={
                "model":       state.active_model["name"],
                "messages":    [
                    {"role": "system", "content": _DESCRIPTION_SYSTEM},
                    {"role": "user",   "content": personality_text}
                ],
                "temperature": 0.7,
                "max_tokens":  60,
                "stream":      True
            }, stream=True, timeout=60)
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                line = line.decode("utf-8")
                if line.startswith("data: "):
                    line = line[6:]
                if line == "[DONE]":
                    yield "data: " + json.dumps({"type": "done"}) + "\n\n"
                    break
                try:
                    chunk = json.loads(line)
                    delta = chunk["choices"][0].get("delta", {})
                    if delta.get("content"):
                        yield "data: " + json.dumps({"type": "token", "text": delta["content"]}) + "\n\n"
                except Exception:
                    continue
        except Exception as e:
            yield "data: " + json.dumps({"type": "error", "text": str(e)}) + "\n\n"

    return Response(stream_with_context(stream()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@personality_bp.route("/api/personalities/<name>/tts-voice")
def serve_tts_voice(name):
    if ".." in name:
        return jsonify({"error": "Invalid"}), 400
    tts = PERSONALITY_DIR / name / "tts_voice.txt"
    voice = tts.read_text(encoding="utf-8").strip() if tts.exists() else ""
    return jsonify({"voice": voice})


@personality_bp.route("/api/personalities/save-tts-voice", methods=["POST"])
def save_tts_voice():
    data  = request.get_json() or {}
    name  = re.sub(r'[^a-zA-Z0-9_\-]', '_', data.get("name", "").strip()).strip('_')
    voice = data.get("voice", "").strip()
    if not name:
        return jsonify({"error": "Name required"}), 400
    folder = PERSONALITY_DIR / name
    folder.mkdir(parents=True, exist_ok=True)
    tts = folder / "tts_voice.txt"
    if voice:
        tts.write_text(voice, encoding="utf-8")
    elif tts.exists():
        tts.unlink()  # empty = use global setting
    print(f"[Personality] TTS voice: {name} → {voice or '(global)'}")
    return jsonify({"ok": True})


@personality_bp.route("/api/personalities/<name>/full")
def serve_full(name):
    """Return text + description + tts_voice in one call."""
    if ".." in name:
        return jsonify({"error": "Invalid"}), 400
    folder = PERSONALITY_DIR / name
    def read(f): return (folder / f).read_text(encoding="utf-8").strip() if (folder / f).exists() else ""
    return jsonify({
        "name":        name,
        "text":        read("personality.txt"),
        "description": read("description.txt"),
        "tts_voice":   read("tts_voice.txt"),
    })


@personality_bp.route("/api/personalities/save-all", methods=["POST"])
def save_all():
    """Save personality text, description and TTS voice in one atomic call."""
    data    = request.get_json() or {}
    name    = re.sub(r'[^a-zA-Z0-9_\-]', '_', data.get("name", "").strip()).strip('_')
    content = data.get("content", "").strip()
    desc    = data.get("description", "").strip()
    voice   = data.get("tts_voice", "").strip()
    img_b64 = data.get("image_b64", "").strip()
    if not name:
        return jsonify({"error": "Name required"}), 400
    folder = PERSONALITY_DIR / name
    folder.mkdir(parents=True, exist_ok=True)
    if content:
        (folder / "personality.txt").write_text(content, encoding="utf-8")
    if desc:
        (folder / "description.txt").write_text(desc, encoding="utf-8")
    tts_file = folder / "tts_voice.txt"
    if voice:
        tts_file.write_text(voice, encoding="utf-8")
    elif tts_file.exists():
        tts_file.unlink()
    if img_b64:
        (folder / "logo.png").write_bytes(base64.b64decode(img_b64))
    print(f"[Personality] save-all: {name}")
    return jsonify({"ok": True, "name": name})


@personality_bp.route("/api/personalities/<name>", methods=["DELETE"])
def delete_personality(name):
    import shutil
    if ".." in name or name == "default":
        return jsonify({"error": "Cannot delete default"}), 400
    folder = PERSONALITY_DIR / name
    if folder.exists():
        shutil.rmtree(folder)
    if state.active_personality == name:
        state.active_personality = "default"
        from state import save_state
        save_state()
    return jsonify({"ok": True})