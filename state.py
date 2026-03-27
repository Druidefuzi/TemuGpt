# ─── STATE.PY — Veränderliche Laufzeit-Globals ────────────────────────────────
# Alle Module importieren von hier statt aus server.py um circular imports zu vermeiden.

from config import MODEL_DEFAULT

active_model             = {"name": MODEL_DEFAULT}
thinking_enabled         = True
research_enabled         = False
image_generation_enabled = True
search_enabled           = True   # Websuche erlaubt
document_enabled         = True   # Dokument-Erstellung erlaubt
knowledge_enabled        = True   # Knowledge-Schreiben erlaubt
custom_system_prompt     = None   # None = SYSTEM_PROMPT aus prompts.py
prompt_style             = "danbooru"  # "danbooru" | "mixed" | "natural"
