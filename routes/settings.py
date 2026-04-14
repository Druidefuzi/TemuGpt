# ─── ROUTES/SETTINGS.PY — Toggles, Permissions, System-Prompt ────────────────

from flask import Blueprint, request, jsonify

from prompts import SYSTEM_PROMPT, PROMPT_STYLES
from state import save_state
import state

settings_bp = Blueprint("settings", __name__)


@settings_bp.route("/api/thinking/toggle", methods=["POST"])
def toggle_thinking():
    state.thinking_enabled = not state.thinking_enabled
    save_state()
    return jsonify({"enabled": state.thinking_enabled})


@settings_bp.route("/api/thinking/status", methods=["GET"])
def thinking_status():
    return jsonify({"enabled": state.thinking_enabled})


@settings_bp.route("/api/research/toggle", methods=["POST"])
def toggle_research():
    state.research_enabled = not state.research_enabled
    save_state()
    print(f"[Research] Mode: {'ON' if state.research_enabled else 'OFF'}")
    return jsonify({"enabled": state.research_enabled})


@settings_bp.route("/api/research/status", methods=["GET"])
def research_status():
    return jsonify({"enabled": state.research_enabled})


@settings_bp.route("/api/image-generation/toggle", methods=["POST"])
def toggle_image_generation():
    state.image_generation_enabled = not state.image_generation_enabled
    save_state()
    print(f"[ImageGen] {'ON' if state.image_generation_enabled else 'OFF'}")
    return jsonify({"enabled": state.image_generation_enabled})


@settings_bp.route("/api/image-generation/status", methods=["GET"])
def image_generation_status():
    return jsonify({"enabled": state.image_generation_enabled})


@settings_bp.route("/api/permissions/toggle", methods=["POST"])
def toggle_permission():
    data       = request.json
    permission = data.get("permission", "")
    flag_map   = {
        "search":    "search_enabled",
        "document":  "document_enabled",
        "knowledge": "knowledge_enabled",
        "image":     "image_generation_enabled",
    }
    if permission not in flag_map:
        return jsonify({"ok": False, "error": "Unknown permission"}), 400
    attr    = flag_map[permission]
    new_val = not getattr(state, attr)
    setattr(state, attr, new_val)
    print(f"[Permission] {permission}: {'ON' if new_val else 'OFF'}")
    save_state()
    return jsonify({"permission": permission, "enabled": new_val})


@settings_bp.route("/api/permissions/status", methods=["GET"])
def permissions_status():
    return jsonify({
        "search":    state.search_enabled,
        "document":  state.document_enabled,
        "knowledge": state.knowledge_enabled,
        "image":     state.image_generation_enabled,
    })


@settings_bp.route("/api/system-prompt", methods=["GET"])
def get_system_prompt():
    return jsonify({"prompt": state.custom_system_prompt if state.custom_system_prompt is not None else SYSTEM_PROMPT})


@settings_bp.route("/api/system-prompt", methods=["POST"])
def set_system_prompt():
    data = request.json
    state.custom_system_prompt = data.get("prompt", "").strip() or None
    save_state()
    print(f"[SystemPrompt] Changed ({len(state.custom_system_prompt or '')} chars)")
    return jsonify({"ok": True})


@settings_bp.route("/api/system-prompt/reset", methods=["POST"])
def reset_system_prompt():
    state.custom_system_prompt = None
    save_state()
    print("[SystemPrompt] Reset to default")
    return jsonify({"ok": True, "prompt": SYSTEM_PROMPT})


@settings_bp.route("/settings")
def settings_page():
    from flask import send_from_directory
    return send_from_directory("frontend", "settings.html")


@settings_bp.route("/api/config/settings", methods=["GET"])
def get_config_settings():
    from database import get_all_config_settings
    return jsonify({"settings": get_all_config_settings()})


@settings_bp.route("/api/config/settings/<key>", methods=["POST"])
def update_config_setting(key):
    from database import set_config_setting, get_config_setting
    import config
    value = (request.json or {}).get("value", "").strip()
    if not value:
        return jsonify({"ok": False, "error": "Empty value"}), 400
    if not set_config_setting(key, value):
        return jsonify({"ok": False, "error": "Unknown key"}), 404
    if hasattr(config, key):
        setattr(config, key, value)
        print(f"[Config] {key} = {value}")
    return jsonify({"ok": True, "value": value})


@settings_bp.route("/api/config/settings/<key>/reset", methods=["POST"])
def reset_config_setting_route(key):
    from database import reset_config_setting
    import config
    value = reset_config_setting(key)
    if value is None:
        return jsonify({"ok": False, "error": "Unknown key"}), 404
    if hasattr(config, key):
        setattr(config, key, value)
        print(f"[Config] {key} reset → {value}")
    return jsonify({"ok": True, "value": value})


@settings_bp.route("/api/prompt-style", methods=["GET", "POST"])
def prompt_style_endpoint():
    if request.method == "POST":
        new_style = request.json.get("style", "danbooru")
        if new_style in PROMPT_STYLES:
            state.prompt_style = new_style
            save_state()
            print(f"[PromptStyle] Changed: {state.prompt_style}")
        return jsonify({"style": state.prompt_style})
    return jsonify({"style": state.prompt_style})


# ─── Personality Settings ──────────────────────────────────────────────────────

@settings_bp.route("/api/personality/settings", methods=["GET", "POST"])
def personality_settings():
    if request.method == "POST":
        data = request.json or {}
        if "enabled" in data:
            state.personality_enabled = bool(data["enabled"])
        if "affects_prompt" in data:
            state.personality_affects_prompt = bool(data["affects_prompt"])
        if "affects_critic" in data:
            state.personality_affects_critic = bool(data["affects_critic"])
        if "affects_music" in data:
            state.personality_affects_music = bool(data["affects_music"])
        save_state()
        print(f"[Personality] enabled={state.personality_enabled} "
              f"prompt={state.personality_affects_prompt} "
              f"critic={state.personality_affects_critic}")
        return jsonify({"ok": True})
    return jsonify({
        "enabled":        state.personality_enabled,
        "affects_prompt": state.personality_affects_prompt,
        "affects_critic": state.personality_affects_critic,
        "affects_music":  getattr(state, "personality_affects_music", True),
    })


# ─── TTS Settings ─────────────────────────────────────────────────────────────

@settings_bp.route("/api/tts/settings", methods=["GET", "POST"])
def tts_settings():
    if request.method == "POST":
        data = request.json or {}
        if "enabled" in data:
            state.tts_enabled = bool(data["enabled"])
        if "voice" in data:
            state.tts_voice = data["voice"].strip()
        if "url" in data:
            state.tts_url = data["url"].strip().rstrip("/")
        save_state()
        print(f"[TTS] enabled={state.tts_enabled} voice={state.tts_voice} url={state.tts_url}")
        return jsonify({"ok": True})
    return jsonify({
        "enabled": state.tts_enabled,
        "voice":   state.tts_voice,
        "url":     state.tts_url,
    })


@settings_bp.route("/api/tts/speak", methods=["POST"])
def tts_speak():
    import requests as _req
    data  = request.json or {}
    text  = data.get("text", "").strip()
    voice = data.get("voice", state.tts_voice).strip() or state.tts_voice
    if not text:
        return jsonify({"error": "No text"}), 400
    if not state.tts_enabled:
        return jsonify({"error": "TTS disabled"}), 403
    try:
        resp = _req.post(
            f"{state.tts_url}/v1/audio/speech",
            json={"model": "kokoro", "voice": voice, "input": text, "response_format": "mp3"},
            timeout=30
        )
        resp.raise_for_status()
        from flask import Response
        return Response(resp.content, mimetype="audio/mpeg",
                        headers={"Content-Disposition": "inline; filename=tts.mp3"})
    except Exception as e:
        print(f"[TTS] Error: {e}")
        return jsonify({"error": str(e)}), 500
