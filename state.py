# ─── STATE.PY — Veränderliche Laufzeit-Globals mit Persistenz ─────────────────
import json
from pathlib import Path
from config import MODEL_DEFAULT

STATE_FILE = Path(__file__).parent / "state.json"

# ─── Defaults ─────────────────────────────────────────────────────────────────
active_model             = {"name": MODEL_DEFAULT}
thinking_enabled         = True
active_image_style       = None
active_image_theme       = None
active_image_character   = None
research_enabled         = False
image_generation_enabled = True
search_enabled           = True
document_enabled         = True
knowledge_enabled        = True
custom_system_prompt     = None
prompt_style             = "danbooru"
active_personality       = "default"

# ─── TTS ──────────────────────────────────────────────────────────────────────
tts_enabled = False
tts_voice   = "af_bella"
tts_url     = "http://localhost:8880"

# ─── Personality controls ──────────────────────────────────────────────────────
personality_enabled        = True   # False → always use default personality
personality_affects_prompt = True   # inject personality into prompt/image generation
personality_affects_critic = True   # inject personality tone into critic feedback
personality_affects_music  = True   # inject personality into song/lyrics generation

# ─── Welche Felder persistiert werden ─────────────────────────────────────────
_PERSISTED_KEYS = [
    "thinking_enabled",
    "research_enabled",
    "image_generation_enabled",
    "search_enabled",
    "document_enabled",
    "knowledge_enabled",
    "custom_system_prompt",
    "prompt_style",
    "active_personality",
    "tts_enabled",
    "tts_voice",
    "tts_url",
    "personality_enabled",
    "personality_affects_prompt",
    "personality_affects_critic",
    "personality_affects_music",
]


def save_state():
    data = {}
    current = globals()
    for key in _PERSISTED_KEYS:
        data[key] = current[key]
    try:
        STATE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"[State] Fehler beim Speichern: {e}")


def load_state():
    global thinking_enabled, research_enabled, image_generation_enabled
    global search_enabled, document_enabled, knowledge_enabled
    global custom_system_prompt, prompt_style, active_personality
    global tts_enabled, tts_voice, tts_url
    global personality_enabled, personality_affects_prompt, personality_affects_critic, personality_affects_music

    if not STATE_FILE.exists():
        print("[State] Keine state.json gefunden, nutze Defaults")
        return

    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        current = globals()
        loaded = []
        for key in _PERSISTED_KEYS:
            if key in data:
                current[key] = data[key]
                loaded.append(key)
        print(f"[State] Geladen aus state.json ({len(loaded)} Settings)")
    except Exception as e:
        print(f"[State] Fehler beim Laden: {e}")


load_state()
