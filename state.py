# ─── STATE.PY — Veränderliche Laufzeit-Globals ────────────────────────────────
# Alle Module importieren von hier statt aus server.py um circular imports zu vermeiden.

from config import MODEL_DEFAULT

active_model             = {"name": MODEL_DEFAULT}
thinking_enabled         = True
research_enabled         = False
image_generation_enabled = True
custom_system_prompt     = None   # None = SYSTEM_PROMPT aus prompts.py
prompt_style             = "danbooru"  # "danbooru" | "mixed" | "natural"
