# Office Assistant — Project Documentation

## Overview

Local AI-powered office assistant with a web UI. Connects LM Studio (LLM) with ComfyUI (image generation) and SearXNG (web search). Runs entirely locally. All UI text and API responses are in English; the LLM responds in whatever language the user writes in.

**Start:** `python server.py` → Browser: `http://localhost:5000`

---

## Dependencies

```bash
pip install flask requests beautifulsoup4 python-docx openpyxl pdfplumber websocket-client Pillow
```

**External services (all local):**
| Service | URL | Purpose |
|---------|-----|---------|
| LM Studio | `http://localhost:1234` | LLM inference (Vision-capable model recommended) |
| ComfyUI | `http://127.0.0.1:8188` | Image generation |
| SearXNG | `http://localhost:8888` | Web search |

---

## File Structure

```
office_assistant/
├── server.py
├── style_creator.py
├── workflows.py
├── config.py
├── state.py
├── prompts.py
├── database.py
├── documents.py
├── search.py
├── llm.py
├── comfy_backend.py
├── migrate.py
├── style.css
│
├── routes/
│   ├── __init__.py
│   ├── chat.py
│   ├── chats_history.py        ← NEW
│   ├── comfy.py
│   ├── gallery.py
│   ├── knowledge.py
│   ├── models.py
│   ├── personality.py          ← NEW
│   ├── reference.py            ← NEW
│   ├── settings.py
│   └── workflows.py
│
├── data/
│   ├── exportImg/
│   │   └── sorted/
│   ├── knowledge/
│   ├── personality/            ← NEW
│   │   └── default/
│   │       ├── personality.txt
│   │       └── logo.png        (optional)
│   ├── reference/              ← NEW
│   │   ├── illustrious/
│   │   │   ├── artists.txt     (one artist per line)
│   │   │   └── @artistname/
│   │   │       └── *.png
│   │   └── anima/
│   │       ├── artists.txt
│   │       └── @artistname/
│   ├── skills/
│   │   └── image_prompt/
│   │       ├── shared/
│   │       ├── danbooru/
│   │       ├── mixed/
│   │       └── natural/
│   ├── wildcards/
│   │   ├── prepend/
│   │   └── replace/
│   ├── workflows/
│   ├── styles/
│   ├── themes/
│   ├── characters/
│   ├── sorts/
│   └── chats.db
│
└── frontend/
    ├── index.html
    ├── workflows.html
    ├── galerie.html
    ├── creator.html
    ├── sort.html
    ├── node_editor.html
    ├── reference.html          ← NEW
    ├── settings.html           ← NEW
    ├── personality.html        ← NEW
    ├── style.css
    ├── workflow_style.css
    ├── app.js
    ├── chat.js
    ├── ui.js
    ├── comfy.js
    ├── models.js
    └── workflow_ui.js
```

---

## Pages & Navigation

| Page | URL | Purpose |
|------|-----|---------|
| Chat | `/` | Main chat interface |
| Image Generator | `/workflows` | ComfyUI workflow-based image generation |
| Gallery | `/gallery` | Grid view with folder navigation |
| Creator | `/creator` | Generate styles/themes/characters/wildcards/sorts via LLM |
| Sort | `/sort` | AI-powered image categorization (accessible from Gallery) |
| Workflow Editor | `/node-editor` | Visual ComfyUI node graph editor (accessible from Image Generator) |
| Reference | `/reference` | Artist reference gallery (accessible from Gallery + Image Generator) |
| Settings | `/settings` | App configuration (connection URLs, feature toggles) |
| Personality | `/personality` | Create and manage AI personalities + logos |

### Navigation structure

Every page has a unified `app-header` with:
- **Logo + name** (left) — links to `/`, logo and name update dynamically to active personality
- **Shared nav tabs** — Home · Image Generator · Gallery · Creator · Personality · Settings
- **Page-specific extras** appended to nav:
  - Gallery → + Sortieren, Reference
  - Image Generator → + Reference, Workflow Editor
  - Sort, Reference, Workflow Editor → own tab marked `active`

### Shared header system

All HTML pages include the same CSS (`.app-header`, `.app-brand`, `.app-tab`) and a shared JS snippet `loadAppHeader()` that fetches the active personality and updates logo + name on load. No page-specific back buttons.

---

## Blueprint Overview

| Blueprint | File | Routes |
|-----------|------|--------|
| chat_bp | `routes/chat.py` | `/chat`, `/smart_chat`, `/stream-think` |
| chats_history_bp | `routes/chats_history.py` | `/api/chats/*` |
| comfy_bp | `routes/comfy.py` | `/api/comfy/*`, styles/themes/characters/wildcards |
| gallery_bp | `routes/gallery.py` | `/gallery`, `/api/gallery`, `/sort`, `/api/sort/*`, `/api/sorts` |
| knowledge_bp | `routes/knowledge.py` | `/api/knowledge/*`, `/api/skills/*` |
| models_bp | `routes/models.py` | `/api/models/*` |
| personality_bp | `routes/personality.py` | `/personality`, `/api/personalities/*` |
| reference_bp | `routes/reference.py` | `/reference`, `/api/reference/*` |
| settings_bp | `routes/settings.py` | toggles, permissions, system-prompt, prompt-style, `/api/config/*` |
| workflows_bp | `routes/workflows.py` | `/api/workflows/*`, PNG helpers, img2img patch, prompt critic |
| creator_bp | `style_creator.py` | `/creator`, `/api/creator/*` |

---

## Data Directory

All runtime data lives under `data/`. `config.py` defines all paths relative to `_DATA = Path(__file__).parent / "data"`.

**Path constants in config.py:**
```python
_DATA           = Path(__file__).parent / "data"
EXPORT_IMG_DIR  = _DATA / "exportImg"
REFERENCE_DIR   = _DATA / "reference"
PERSONALITY_DIR = _DATA / "personality"
KNOWLEDGE_DIR   = _DATA / "knowledge"
SKILLS_DIR      = _DATA / "skills" / "image_prompt"
WILDCARDS_DIR   = _DATA / "wildcards"
WORKFLOWS_DIR   = _DATA / "workflows"
STYLES_DIR      = _DATA / "styles"
THEMES_DIR      = _DATA / "themes"
CHARACTERS_DIR  = _DATA / "characters"
SORTS_DIR       = _DATA / "sorts"
DB_PATH         = _DATA / "chats.db"
```

---

## Personality System

Personalities live in `data/personality/{name}/`. Each has:
- `personality.txt` — 2-3 sentences describing the assistant's character (replaces the default personality header)
- `logo.png` — optional avatar shown in chat bubbles and header

### How it works

`prompts.py` splits the system prompt into two parts:
- `DEFAULT_PERSONALITY` — fallback personality text
- `SYSTEM_RULES` — all JSON action rules (never changes)

`get_system_prompt()` reads `data/personality/{active_personality}/personality.txt` and combines it with `SYSTEM_RULES`. Called in `llm.py → build_messages()`.

`state.active_personality` (default: `"default"`) is persisted in `state.json`.

### Switching personalities

- **Index.html** — dropdown in header, switches instantly
- **Settings page** — `/settings`
- **Personality Creator** — `/personality` — generate text via LLM, generate logo via ComfyUI workflow

### Logo display

`ui.js` loads `_assistantLogoSrc` from `/api/personalities/active` on page load. All chat bubbles (streaming, history, document messages) use this dynamic source.

### API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/personalities` | List all personalities + active |
| GET/POST | `/api/personalities/active` | Get/set active personality |
| GET | `/api/personalities/<n>/logo` | Serve logo (fallback: assets/logo.png) |
| GET | `/api/personalities/<n>/text` | Read personality.txt |
| POST | `/api/personalities/generate-text` | SSE: generate personality via LLM |
| POST | `/api/personalities/logo-prompt` | Build logo prompt from subject description |
| POST | `/api/personalities/save` | Save personality.txt |
| POST | `/api/personalities/save-logo` | Save logo.png from base64 |
| DELETE | `/api/personalities/<n>` | Delete (default cannot be deleted) |

---

## Reference Gallery

Artist reference images for Illustrious and Anima models. Stored in `data/reference/{model}/{artistname}/`.

### artists.txt format

One artist name per line in `data/reference/{model}/artists.txt`:
```
@adzn
@yuri
blue-senpai
```

The API reads this file for the sidebar list, scans existing subdirectories for image counts, and sorts by image count descending.

### Virtual list

The sidebar uses a virtual scroll implementation (absolute positioning + `translateY`) to handle 39,000+ entries without freezing. Only ~30 DOM elements rendered at any time.

### Artist Mode (Workflow Editor)

Toggle **🎨 Artist Mode** in the params panel. Select model type (Illustrious/Anima) and artist from the reference list. On generation:
- Artist tag is prepended to the positive prompt: `@artistname, [rest of prompt]`
- PNG saved to `data/reference/{model_type}/{artistname}/{timestamp}_{artist}.png` instead of `exportImg`

When opening a PNG from Reference Gallery in Workflow Editor: artist mode is pre-activated with the correct model type and artist — no img2img.

### API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/reference` | Reference gallery page |
| GET | `/api/reference/models` | List model folders |
| GET | `/api/reference/artists?model=` | List artists with image counts |
| GET | `/api/reference/images?model=&artist=` | List images (artist empty = all) |
| GET | `/api/reference/image?model=&artist=&file=` | Serve image |

---

## Settings Page (`/settings`)

Three sections:

**Connections** — DB-backed config values (LM_STUDIO_URL, LM_API, COMFY_URL, MODEL_DEFAULT). Editable with reset-to-default. Changes applied live to `config` module via `setattr`. Persisted in `config_settings` SQLite table.

**Features** — Toggles for: Thinking Mode, Research Mode, Image Generation, Web Search, Document Creation, Knowledge Writing.

**Prompt** — Prompt style pills (Danbooru/Mixed/Natural) and System Prompt editor.

### Database table: config_settings

```sql
CREATE TABLE config_settings (
    key           TEXT PRIMARY KEY,
    value         TEXT NOT NULL,
    default_value TEXT NOT NULL,
    label         TEXT NOT NULL,
    category      TEXT NOT NULL,
    description   TEXT DEFAULT ''
);
```

### API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/config/settings` | List all config settings |
| POST | `/api/config/settings/<key>` | Update a setting (applied live) |
| POST | `/api/config/settings/<key>/reset` | Reset to default |

---

## Chat History (`/api/chats/*`)

Stored in SQLite (`chats.db`). Implemented in `routes/chats_history.py`.

### API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET/POST | `/api/chats` | List / create chats |
| GET/PATCH/DELETE | `/api/chats/<id>` | Get / rename / delete |
| POST | `/api/chats/<id>/generate-title` | LLM title generation |
| POST | `/api/chats/<id>/messages` | Add messages (single `{role,content}` or array `{messages:[...]}`) |

---

## Creator Page (`/creator`)

**`style_creator.py`** — Flask Blueprint.

| Mode | Output | Saved to |
|------|--------|----------|
| 👤 Character | Appearance tags | `data/characters/` |
| 🎨 Style | Rendering/aesthetic tags | `data/styles/` |
| 🌍 Theme | World/setting tags | `data/themes/` |
| 🎲 Wildcard | Value list (one per line) | `data/wildcards/replace/` or `prepend/` |
| 🗂️ Sort | Classifier instruction for Sort page | `data/sorts/` |

### Sort Mode

Generates a precise classifier instruction for the Sort page in the same format as manual `data/sorts/*.txt` files. Includes an Auto-Critic that checks for: clear role sentence, explicit task, unambiguous rules, correct output format (lowercase slug).

---

## Sort Page (`/sort`)

AI-powered image categorizer. Only images directly in the source folder are processed.

### Subfolder-aware sorting

When sorting from a subfolder (e.g. `sorted/good_quality/`), sorted output goes into subfolders of that same directory — not always into `exportImg/sorted/`. The LLM only sees existing folders within the current source directory.

### Sort Presets

`.txt` files in `data/sorts/` load as dropdown presets. Format:
```
You are a strict classifier.
Task: [what to detect]
Rules:
- [specific rules]
Output ONLY the folder name — lowercase, underscores, max 20 chars
```

---

## Prompt Critic

LLM-based quality analysis for image prompts. Injects the active personality into the critic system prompt for flavored feedback.

Available in:
1. **Workflow Editor** — toggle 🔍 Prompt Critic in params panel
2. **Workflow Prompt Assistant** — Auto-Critic checkbox after prompt suggestion
3. **Creator Page** — Auto-Critic toggle per mode (character/style/theme/wildcard/sort)

---

## Workflow Editor

### Artist Mode

New section in params panel. Select Illustrious or Anima, then choose artist from reference list (searchable). On generate: artist tag prepended to positive prompt, PNG saved to reference folder.

### Image to Image

Toggle in params panel. `apply_img2img_patch()` in `routes/workflows.py` replaces `EmptyLatentImage` with `LoadImage + VAEEncode`. Auto-activated when loading PNG from Gallery with embedded workflow.

### Dynamic LoRA Management, Refiner, Prompt Critic

Unchanged from previous version.

---

## prompts.py

```python
DEFAULT_PERSONALITY  # Swappable personality text (fallback)
SYSTEM_RULES         # Fixed JSON action rules
SYSTEM_PROMPT        # Legacy alias = DEFAULT_PERSONALITY + SYSTEM_RULES
get_system_prompt()  # Returns active personality + SYSTEM_RULES
PROMPT_STYLES        # danbooru / mixed / natural
THINKING_PROMPT
INTENT_PROMPT
PROMPT_CRITIC_PROMPT
```

---

## state.py

Persisted in `state.json`:

```python
active_model             # {"name": "..."}
thinking_enabled         # bool
research_enabled         # bool
image_generation_enabled # bool
search_enabled           # bool
document_enabled         # bool
knowledge_enabled        # bool
custom_system_prompt     # str | None  ← set to null to enable personality system
prompt_style             # "danbooru" | "mixed" | "natural"
active_personality       # str (folder name in data/personality/)
active_image_style       # str | None
active_image_theme       # str | None
active_image_character   # str | None
```

**Important:** `custom_system_prompt` must be `null` in `state.json` for the personality system to work. If set to a string, it overrides everything.

---

## llm.py

```python
build_messages(...)           # Uses get_system_prompt() — personality-aware
critique_prompt(prompt)       # Injects active personality into critic system prompt
read_style_content(name)
read_theme_content(name)
read_character_content(name)
```

---

## API Endpoints (complete)

### Chat
| POST | `/chat` | Blocking chat (file uploads) |
| POST | `/smart_chat` | Streaming chat with intent detection |
| POST | `/stream-think` | SSE: thinking stream |

### Chat History
| GET/POST | `/api/chats` | List / create chats |
| GET/PATCH/DELETE | `/api/chats/<id>` | Get / rename / delete |
| POST | `/api/chats/<id>/generate-title` | LLM title generation |
| POST | `/api/chats/<id>/messages` | Add messages |

### Models
| GET | `/api/models` | List LM Studio models |
| POST | `/api/models/load` | Load a model |
| POST | `/api/models/unload` | Unload a model |
| GET/POST | `/api/models/active` | Get/set active model |

### Settings & Config
| POST | `/api/thinking/toggle` | Toggle thinking |
| GET | `/api/thinking/status` | |
| POST | `/api/research/toggle` | Toggle research mode |
| GET | `/api/research/status` | |
| POST | `/api/image-generation/toggle` | Toggle image generation |
| GET | `/api/image-generation/status` | |
| POST | `/api/permissions/toggle` | Toggle search/document/knowledge/image |
| GET | `/api/permissions/status` | |
| GET/POST | `/api/system-prompt` | Get/set custom system prompt |
| POST | `/api/system-prompt/reset` | Reset to default |
| GET/POST | `/api/prompt-style` | Get/set danbooru/mixed/natural |
| GET | `/api/config/settings` | List DB-backed config settings |
| POST | `/api/config/settings/<key>` | Update config setting |
| POST | `/api/config/settings/<key>/reset` | Reset to default |

### Personality
| GET | `/personality` | Personality creator page |
| GET | `/api/personalities` | List all + active |
| GET/POST | `/api/personalities/active` | Get/set active |
| GET | `/api/personalities/<n>/logo` | Serve logo |
| GET | `/api/personalities/<n>/text` | Read personality text |
| POST | `/api/personalities/generate-text` | SSE: generate personality |
| POST | `/api/personalities/logo-prompt` | Build logo prompt |
| POST | `/api/personalities/save` | Save personality.txt |
| POST | `/api/personalities/save-logo` | Save logo.png |
| DELETE | `/api/personalities/<n>` | Delete personality |

### Knowledge & Skills
| GET | `/api/knowledge` | List knowledge files |
| GET | `/api/knowledge/<filename>` | Read a file |
| GET | `/api/skills` | List skill files grouped by style |
| GET | `/api/skills/<style>/<filename>` | Read a skill file |

### ComfyUI
| GET | `/api/comfy/models` | List models |
| GET | `/api/comfy/image-models?type=` | By type |
| GET | `/api/comfy/all-checkpoints` | Checkpoints + UNETs |
| GET | `/api/comfy/all-loras` | LoRAs |

### Styles / Themes / Characters / Wildcards
| GET | `/api/styles` | List style files |
| GET/POST | `/api/image-style` | Get/set active style |
| GET | `/api/themes` | List theme files |
| GET/POST | `/api/image-theme` | Get/set active theme |
| GET | `/api/characters` | List character files |
| GET/POST | `/api/image-character` | Get/set active character |
| GET | `/api/wildcards` | List wildcard files with folder info |

### Gallery & Sort
| GET | `/api/gallery?folder=` | List images + subfolders |
| GET | `/api/gallery/file?path=` | Serve image |
| GET | `/api/sorts` | List sort preset files |
| POST | `/api/sort/run` | SSE: sort images |
| POST | `/api/sort/unsort` | Move all back |

### Workflows
| GET | `/api/workflows` | List workflow JSONs |
| GET | `/api/workflows/<n>` | Load a workflow |
| POST | `/api/workflows/save` | Save workflow JSON |
| POST | `/api/workflows/run` | SSE: run workflow (img2img, artist mode, refiner) |
| POST | `/api/workflows/prompt-suggest` | SSE: generate prompt |
| POST | `/api/workflows/extract-from-image` | Extract workflow from PNG |
| POST | `/api/workflows/critique-prompt` | LLM critique of a prompt |

### Creator
| GET | `/creator` | Creator page |
| POST | `/api/creator/generate` | SSE: generate content |
| POST | `/api/creator/save` | Save to folder |
| POST | `/api/creator/critique` | LLM critique |

### Reference Gallery
| GET | `/reference` | Reference gallery page |
| GET | `/api/reference/models` | List model folders |
| GET | `/api/reference/artists?model=` | Artists with image counts |
| GET | `/api/reference/images?model=&artist=` | Images (empty artist = all) |
| GET | `/api/reference/image?model=&artist=&file=` | Serve image |

---

## Known TODOs

- [ ] WebSocket Preview — Anima Turbo may not deliver JPEG previews
- [ ] LLM is not automatically reloaded after image generation
- [ ] Knowledge files re-read from disk on every request (no caching)
- [ ] Wildcard cache: files cached on first read, restart required for new files
- [ ] Sort parallelität > 2 causes LLM timeouts with LM Studio
- [ ] Personality logo not yet shown as favicon
- [ ] Reference gallery image count only updates on server restart (not live after Artist Mode generation)
