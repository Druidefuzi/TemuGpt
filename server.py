"""
LM Studio Office Assistant - Flask Backend
==========================================
Starten: python server.py
Browser: http://localhost:5000
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import requests
from flask import Flask, send_from_directory

from config import LM_API, MODEL_DEFAULT, OUTPUT_DIR
import state
from database import init_db

# ─── Blueprints ────────────────────────────────────────────────────────────────

from routes.chat      import chat_bp
from routes.chats_history import chats_history_bp
from routes.comfy     import comfy_bp
from routes.gallery   import gallery_bp
from routes.knowledge import knowledge_bp
from routes.models    import models_bp
from routes.settings  import settings_bp
from routes.workflows import workflows_bp
from style_creator    import creator_bp
from routes.reference import reference_bp
from routes.personality import personality_bp
from routes.merger      import merger_bp
from routes.music       import music_bp

app = Flask(__name__, static_folder="frontend")


def _apply_config_from_db():
    try:
        from database import get_all_config_settings
        import config
        for s in get_all_config_settings():
            if hasattr(config, s["key"]):
                setattr(config, s["key"], s["value"])
        print("[Config] DB-Einstellungen geladen")
    except Exception as e:
        print(f"[Config] Laden fehlgeschlagen: {e}")


app.register_blueprint(chat_bp)
app.register_blueprint(chats_history_bp)
app.register_blueprint(comfy_bp)
app.register_blueprint(gallery_bp)
app.register_blueprint(knowledge_bp)
app.register_blueprint(models_bp)
app.register_blueprint(settings_bp)
app.register_blueprint(workflows_bp)
app.register_blueprint(creator_bp)
app.register_blueprint(reference_bp)
app.register_blueprint(personality_bp)
app.register_blueprint(merger_bp)
app.register_blueprint(music_bp)


# ─── System ───────────────────────────────────────────────────────────────────

@app.route("/api/server/restart", methods=["POST"])
def server_restart():
    import threading, os, signal
    def _restart():
        import time; time.sleep(0.3)
        os.execv(sys.executable, [sys.executable] + sys.argv)
    threading.Thread(target=_restart, daemon=True).start()
    return __import__('flask').jsonify({"ok": True, "message": "Restarting..."})


# ─── Page Routes ───────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("frontend", "index.html")

@app.route("/workflows")
def workflows_page():
    return send_from_directory("frontend", "workflows.html")

@app.route("/node-editor")
def node_editor_page():
    return send_from_directory("frontend", "node_editor.html")


# ─── Init ──────────────────────────────────────────────────────────────────────

def _init_active_model():
    try:
        resp = requests.get(f"{LM_API}/api/v1/models", timeout=3)
        if resp.ok:
            for m in resp.json().get("models", []):
                if m.get("loaded_instances"):
                    state.active_model["name"] = m["key"]
                    print(f"[Init] Active model: {m['display_name']} ({m['key']})")
                    return
        print(f"[Init] No loaded model found, using default: {MODEL_DEFAULT}")
    except Exception:
        print(f"[Init] LM Studio not reachable, using default: {MODEL_DEFAULT}")


# ─── Start ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    _apply_config_from_db()
    _init_active_model()
    # Write default personality if missing
    try:
        from config import PERSONALITY_DIR
        from prompts import DEFAULT_PERSONALITY
        default_dir = PERSONALITY_DIR / "default"
        default_dir.mkdir(parents=True, exist_ok=True)
        p_file = default_dir / "personality.txt"
        if not p_file.exists():
            p_file.write_text(DEFAULT_PERSONALITY, encoding="utf-8")
        d_file = default_dir / "description.txt"
        if not d_file.exists():
            d_file.write_text("Your intelligent office assistant, ready to help with documents, research, and more.", encoding="utf-8")
    except Exception as e:
        print(f"[Personality] Default init failed: {e}")
    print("\n🚀 LM Studio Office Assistant")
    print(f"   Active model: {state.active_model['name']}")
    print(f"   Open browser: http://localhost:5000")
    print(f"   Files saved to: {OUTPUT_DIR}\n")
    app.run(debug=False, host="0.0.0.0", port=5000)