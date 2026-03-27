# ─── CONFIG.PY — Unveränderliche Konstanten ───────────────────────────────────

from pathlib import Path

LM_STUDIO_URL = "http://localhost:1234/v1/chat/completions"
LM_API        = "http://localhost:1234"
COMFY_URL     = "http://127.0.0.1:8188"
MODEL_DEFAULT = "huihui-qwen3-vl-4b-instruct-abliterated"

OUTPUT_DIR     = Path.home() / "Dokumente" / "LLM_Output"
EXPORT_IMG_DIR = Path(r"C:\Users\Druid\office-assistent\exportImg")
MODELS_DIR     = Path.home() / ".lmstudio" / "models"
KNOWLEDGE_DIR  = Path(__file__).parent / "knowledge"
WORKFLOWS_DIR  = Path(__file__).parent / "workflows"
DB_PATH        = Path(__file__).parent / "chats.db"

# Verzeichnisse anlegen
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
EXPORT_IMG_DIR.mkdir(parents=True, exist_ok=True)
KNOWLEDGE_DIR.mkdir(exist_ok=True)
WORKFLOWS_DIR.mkdir(exist_ok=True)
