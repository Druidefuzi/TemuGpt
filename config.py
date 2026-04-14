# ─── CONFIG.PY — Unveränderliche Konstanten ───────────────────────────────────

from pathlib import Path

LM_STUDIO_URL = "http://localhost:1234/v1/chat/completions"
LM_API        = "http://localhost:1234"
COMFY_URL     = "http://127.0.0.1:8188"
MODEL_DEFAULT = "huihui-qwen3-vl-4b-instruct-abliterated"

# ─── Basis-Verzeichnisse ───────────────────────────────────────────────────────
_ROOT     = Path(__file__).parent
_DATA     = _ROOT / "data"

# ─── Externe Pfade ────────────────────────────────────────────────────────────
OUTPUT_DIR  = Path.home() / "Dokumente" / "LLM_Output"
MODELS_DIR  = Path.home() / ".lmstudio" / "models"

# ─── Datenpfade (alle unter data/) ────────────────────────────────────────────
EXPORT_IMG_DIR = _DATA / "exportImg"
REFERENCE_DIR  = _DATA / "reference"
PERSONALITY_DIR = _DATA / "personality"
KNOWLEDGE_DIR  = _DATA / "knowledge"
SORTS_DIR      = _DATA / "sorts"
SKILLS_DIR     = _DATA / "skills" / "image_prompt"
WILDCARDS_DIR  = _DATA / "wildcards"
WORKFLOWS_DIR  = _DATA / "workflows"
STYLES_DIR     = _DATA / "styles"
THEMES_DIR     = _DATA / "themes"
CHARACTERS_DIR = _DATA / "characters"
DB_PATH        = _DATA / "chats.db"

# ─── Verzeichnisse anlegen ────────────────────────────────────────────────────
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
EXPORT_IMG_DIR.mkdir(parents=True, exist_ok=True)
REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
PERSONALITY_DIR.mkdir(parents=True, exist_ok=True)
(PERSONALITY_DIR / "default").mkdir(exist_ok=True)
KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
SORTS_DIR.mkdir(parents=True, exist_ok=True)
WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
STYLES_DIR.mkdir(parents=True, exist_ok=True)
THEMES_DIR.mkdir(parents=True, exist_ok=True)
CHARACTERS_DIR.mkdir(parents=True, exist_ok=True)
WILDCARDS_DIR.mkdir(parents=True, exist_ok=True)
(WILDCARDS_DIR / "prepend").mkdir(exist_ok=True)
(WILDCARDS_DIR / "replace").mkdir(exist_ok=True)
SKILLS_DIR.mkdir(parents=True, exist_ok=True)
(SKILLS_DIR / "danbooru").mkdir(exist_ok=True)
(SKILLS_DIR / "mixed").mkdir(exist_ok=True)
(SKILLS_DIR / "natural").mkdir(exist_ok=True)
(SKILLS_DIR / "shared").mkdir(exist_ok=True)