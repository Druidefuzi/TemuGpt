# Office Assistant — Projektdokumentation

## Übersicht

Lokaler KI-gestützter Büroassistent mit Web-UI. Verbindet LM Studio (LLM) mit ComfyUI (Bildgenerierung) und SearXNG (Websuche). Läuft vollständig lokal.

**Starten:** `python server.py` → Browser: `http://localhost:5000`

---

## Abhängigkeiten

```bash
pip install flask requests beautifulsoup4 python-docx openpyxl pdfplumber websocket-client
```

**Externe Dienste (alle lokal):**
| Dienst | URL | Zweck |
|--------|-----|-------|
| LM Studio | `http://localhost:1234` | LLM-Inferenz |
| ComfyUI | `http://127.0.0.1:8188` | Bildgenerierung |
| SearXNG | `http://localhost:8888` | Websuche |

---

## Dateistruktur

```
office-assistent/
├── server.py              # Flask App + alle Routes
├── config.py              # Unveränderliche Konstanten & Pfade
├── state.py               # Veränderliche Laufzeit-Globals
├── prompts.py             # Alle LLM System-Prompts (auf Englisch)
├── database.py            # SQLite + Knowledge-Dateien
├── documents.py           # Word/Excel/Text Erstellung + File-Reading
├── search.py              # SearXNG + fetch_page + Spracherkennung
├── llm.py                 # LLM-Calls, intent, enforce_action, stream_generator
├── comfy_backend.py       # ComfyUI WebSocket-Kommunikation + Modell-Listen
├── workflows.py           # ComfyUI Workflow-Definitionen
├── chats.db               # SQLite Datenbank (auto-erstellt)
├── knowledge/             # Wissens-Dateien (.html, .txt, .md, .json, .js, .css)
├── exportImg/             # Generierte Bilder (relativ zum Projektordner)
└── frontend/
    ├── index.html         # Haupt-HTML
    ├── style.css          # Stylesheet
    ├── app.js             # Globaler State, Init, Keyboard-Shortcuts, Sidebar-Resize
    ├── chat.js            # Chat, Stream, DB-History, Export, Auto-Titel
    ├── ui.js              # DOM-Helpers, Markdown-Renderer
    ├── comfy.js           # Bildgenerierung UI & Panel
    └── models.js          # Modell-Manager, Settings
```

---

## Modul-Übersicht (Backend)

### `config.py` — Konstanten

Alle unveränderlichen Pfade und URLs. Beim Import werden die Verzeichnisse automatisch angelegt.

```python
LM_STUDIO_URL  = "http://localhost:1234/v1/chat/completions"
LM_API         = "http://localhost:1234"
COMFY_URL      = "http://127.0.0.1:8188"
MODEL_DEFAULT  = "huihui-qwen3-vl-4b-instruct-abliterated"

OUTPUT_DIR     = Path.home() / "Dokumente" / "LLM_Output"
EXPORT_IMG_DIR = Path(__file__).parent / "exportImg"   # relativ zum Projektordner
KNOWLEDGE_DIR  = Path(__file__).parent / "knowledge"
WORKFLOWS_DIR  = Path(__file__).parent / "workflows"
DB_PATH        = Path(__file__).parent / "chats.db"
```

> `EXPORT_IMG_DIR` ist seit Refactoring relativ — kein hardcodierter Windows-Pfad mehr.

---

### `state.py` — Laufzeit-Globals

Veränderliche Flags die zur Laufzeit über API-Endpunkte getoggelt werden. Alle anderen Module importieren von hier statt aus `server.py`, um circular imports zu vermeiden.

```python
active_model             = {"name": MODEL_DEFAULT}
thinking_enabled         = True    # Reasoning-Anzeige AN/AUS (zeigt reasoning_content des Modells)
research_enabled         = False   # Deep-Research (Seiten scrapen)
image_generation_enabled = True    # Bildgenerierung (aus = LLM weiß nichts davon)
search_enabled           = True    # Websuche erlaubt
document_enabled         = True    # Dokument-Erstellung erlaubt
knowledge_enabled        = True    # Knowledge-Schreiben erlaubt
custom_system_prompt     = None    # None = SYSTEM_PROMPT aus prompts.py
prompt_style             = "danbooru"  # "danbooru" | "mixed" | "natural"
```

---

### `prompts.py` — System-Prompts

Alle LLM-Prompts auf Englisch für besseres Modell-Verständnis. Chat-Antworten werden trotzdem auf Deutsch ausgegeben (`"Write your chat messages in German"` am Ende des SYSTEM_PROMPT).

| Konstante | Beschreibung |
|-----------|-------------|
| `SYSTEM_PROMPT` | Haupt-Prompt mit 5 Regeln (chat / search / document / image / knowledge) |
| `PROMPT_STYLES` | Dict mit drei Bild-Prompt-Stilen (danbooru / mixed / natural) |
| `DANBOORU_PROMPT` | Alias auf `PROMPT_STYLES["danbooru"]` — für Workflow-Editor |
| `THINKING_PROMPT` | Prompt für den internen Reasoning-Schritt |
| `INTENT_PROMPT` | Kurzer Prompt zur Aktionserkennung (Preflight) |

#### Prompt-Stile (`PROMPT_STYLES`)

| Stil | Modell | Beispiel-Output |
|------|--------|-----------------|
| `danbooru` | Illustrious/SDXL | `masterpiece, best quality, 1girl, long hair, ...` |
| `mixed` | Anima | `masterpiece, 1girl. A girl with long silver hair standing in a misty forest...` |
| `natural` | Z-Image | `A cinematic portrait shot on 85mm f/1.4. Soft golden hour light...` |

Der aktive Stil wird in `state.prompt_style` gespeichert und via `GET/POST /api/prompt-style` gesteuert. Beim Wechsel des Modell-Typs im Frontend wird der Stil automatisch gesetzt (`anima→mixed`, `illustrious→danbooru`, `zimage→natural`).

---

### `database.py` — SQLite + Knowledge

```python
get_db()                              # SQLite-Verbindung
init_db()                             # Tabellen anlegen (beim Start)
read_knowledge() -> str               # Alle Knowledge-Dateien als String
write_knowledge(filename, content)    # Datei im knowledge/ Ordner schreiben
```

**Schema:**
```sql
CREATE TABLE chats (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    title   TEXT    NOT NULL DEFAULT 'Neuer Chat',
    model   TEXT,
    created TEXT    NOT NULL,
    updated TEXT    NOT NULL
);

CREATE TABLE messages (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    role    TEXT    NOT NULL,   -- 'user' | 'assistant'
    content TEXT    NOT NULL,   -- Text oder JSON für Bilder
    created TEXT    NOT NULL
);
```

**Bilder werden als JSON in `content` gespeichert:**
```json
{
  "__type": "image",
  "b64": "...",
  "model": "anima-preview2.safetensors",
  "model_type": "anima",
  "prompt": "...",
  "filename": "ComfyUI_00042_.png"
}
```

---

### `documents.py` — Dokumente & Datei-Lesen

**Datei-Lesen (`read_file_content`):**
Unterstützte Upload-Formate:
- Bilder (png/jpg/gif/webp) → Base64 → direkt ans LLM als `image_url`
- PDF → pdfplumber → Text
- DOCX → python-docx → Text
- XLSX/XLS → openpyxl → Tabellentext
- TXT → direkt

**Dokument-Erstellung:**
```python
create_word(data, path)    # Word .docx
create_excel(data, path)   # Excel .xlsx
create_text(data, path)    # Plaintext .txt
save_document(data)        # Dispatcher → gibt (path, filename) zurück
```

---

### `search.py` — Websuche

```python
detect_language(text) -> str                                    # "en-US" oder "de-DE"
fetch_page(url, query, max_words) -> str                        # Seite scrapen, relevante Absätze
search_searxng(query, max_results=8, min_pages=5) -> list       # SearXNG abfragen
format_search_results(query, results) -> str                    # Für LLM formatieren
```

`search_searxng` akzeptiert jetzt `max_results` und `min_pages` als Parameter — diese werden vom Frontend via `smart_chat` übergeben und steuern die Research-Slider-Werte tatsächlich. Scraping läuft bis `min_pages` erfolgreiche Seiten erreicht sind.

---

### `llm.py` — LLM-Logik

```python
enforce_action(parsed, expected) -> dict  # Stellt sicher dass LLM-Action mit Intent übereinstimmt
parse_json_response(text) -> dict         # JSON aus LLM-Antwort extrahieren
call_llm(messages, temperature, ...) -> (text, reasoning)  # Non-streaming Call
build_messages(message, history, files)   # messages-Liste aufbauen
_detect_intent(messages, forced_action) -> dict  # Preflight: Action erkennen (temp=0, max_tokens=200)
generate_danbooru_prompt(message) -> dict # Prompt im aktiven Stil generieren
stream_generator(messages, ...)           # SSE-Streaming Generator
```

**`enforce_action`** — Sicherheitsnetz gegen Intent/LLM-Mismatch: Falls der Preflight `create_document` erkennt, der Haupt-LLM aber `chat` zurückgibt, wird die Action korrigiert und geloggt:
```
[ActionMismatch] Erwartet='create_document' | LLM='chat' → erzwinge 'create_document'
```

**`_detect_intent`** — Schneller Preflight-Call (Temperature 0, 200 Tokens) bevor der eigentliche LLM-Call startet. Nimmt optionalen `forced_action` Parameter — bei gesetzter Forced Action wird der LLM-Call komplett übersprungen. Deaktivierte Permissions werden als Fallback auf `chat` abgefangen.

`generate_danbooru_prompt` wählt automatisch den richtigen Prompt aus `PROMPT_STYLES` basierend auf `state.prompt_style`.

---

### `comfy_backend.py` — ComfyUI

```python
comfy_get_models_by_type(model_type) -> list  # Modelle nach Typ (anima/illustrious/zimage)
comfy_get_models() -> list                     # Legacy-Alias für Anima
comfy_generate_stream(workflow, model_type)    # Generator: WebSocket → image_preview | image_progress | image_final | error
```

**Modell-Quellen nach Typ:**
| Typ | ComfyUI Node | Filter |
|-----|-------------|--------|
| `anima` | `UNETLoader` | `"anima"` im Pfad |
| `zimage` | `UNETLoader` | `"zimage"` im Pfad |
| `illustrious` | `CheckpointLoaderSimple` | alle |

`comfy_generate_stream` kommuniziert via WebSocket mit ComfyUI und liefert:
- `image_preview` — JPEG-Preview während Generierung (binäre WS-Message)
- `image_progress` — Fortschritt `{value, max, pct}`
- `image_final` — Fertiggestelltes Bild als `{b64, filename, img_bytes}`
- `error` — Fehlermeldung

---

### `server.py` — Flask Routes

Nur noch Routes + `_init_active_model()`. Importiert alles aus den anderen Modulen.

#### Chat-Ablauf (`/smart_chat`)

```
User-Nachricht
    → build_messages()
    → _detect_intent(forced_action?) → action erkennen (Preflight, temp=0)
        → forced_action gesetzt      → überspringt LLM-Preflight direkt
        → "chat"            → stream_generator() (SSE Stream)
        → "search"          → SearXNG (max_results, min_pages) → ggf. Seiten scrapen → LLM → SSE
        → "create_document" → LLM → enforce_action() → save_document() → SSE
        → "write_knowledge" → LLM → enforce_action() → write_knowledge() → JSON
        → "generate_image"  → generate_danbooru_prompt() → LLM entladen
                            → build_workflow() → comfy_generate_stream() → SSE
```

`/smart_chat` liest jetzt zusätzlich `research_max_results` und `research_min_pages` aus dem Request-Body und reicht sie an `search_searxng()` weiter.

#### Bildgenerierungs-Ablauf

1. `_detect_intent()` erkennt `generate_image`
2. `generate_danbooru_prompt()` — generiert Prompt im aktuellen Stil (außer `image_raw_prompt=True`)
3. LLM aus VRAM entladen via `LM_API/api/v1/models/unload`
4. `build_workflow()` aus `workflows.py` — wählt Workflow nach `model_type` + `turbo`
5. `comfy_generate_stream()` — WebSocket zu ComfyUI, streamt JPEG-Previews + Fortschritt
6. Finales Bild → Base64 → SSE `image_done` + Speichern nach `EXPORT_IMG_DIR`

---

## `workflows.py`

Alle ComfyUI-Workflows ausgelagert. Jeder Workflow hat eine `WORKFLOW_*` Konstante + `patch_*()` Funktion.

| Typ | Normal | Turbo |
|-----|--------|-------|
| **Anima** | `WORKFLOW_ANIMA` + `patch_anima()` | `WORKFLOW_ANIMA_TURBO` + `patch_anima_turbo()` — mit `AnimaLayerReplayPatcher` |
| **Illustrious** | `WORKFLOW_ILLUSTRIOUS` + `patch_illustrious()` — mit FaceDetailer | `WORKFLOW_ILLUSTRIOUS_TURBO` + `patch_illustrious_turbo()` — DMD2 LoRA, 6 Steps, cfg 1.3 |
| **Z-Image** | `WORKFLOW_ZIMAGE` + `patch_zimage()` — UNETLoader + CLIPLoaderGGUF + FaceDetailer | — |

**`build_workflow(model_type, prompt, negative, aspect_ratio, model_name, turbo=False)`**
→ Zentraler Dispatcher, gibt fertigen gepatchten Workflow zurück.

**Aspect Ratios → Pixel:**
| Ratio | W × H |
|-------|-------|
| 1:1 | 1024 × 1024 |
| 3:4 (Golden Ratio) | 896 × 1152 |
| 4:3 | 1152 × 896 |
| 16:9 | 1216 × 704 |
| 9:16 | 704 × 1216 |

---

## API-Endpunkte

### Chat
| Methode | Endpoint | Beschreibung |
|---------|----------|--------------|
| POST | `/chat` | Blocking-Chat mit Datei-Upload (multipart/form-data) |
| POST | `/smart_chat` | Haupt-Chat-Endpoint mit SSE-Stream |
| POST | `/stream-think` | Reasoning SSE-Stream |

### Modelle (LM Studio)
| Methode | Endpoint | Beschreibung |
|---------|----------|--------------|
| GET | `/api/models` | Alle verfügbaren Modelle |
| POST | `/api/models/load` | Modell laden `{load_id, name}` |
| POST | `/api/models/unload` | Modell entladen `{instance_id}` |
| GET | `/api/models/active` | Aktives Modell |
| POST | `/api/models/active` | Aktives Modell setzen `{id}` |

### Einstellungen
| Methode | Endpoint | Beschreibung |
|---------|----------|--------------|
| POST | `/api/thinking/toggle` | Reasoning-Anzeige AN/AUS |
| GET | `/api/thinking/status` | Status |
| POST | `/api/research/toggle` | Research-Modus AN/AUS |
| GET | `/api/research/status` | Status |
| POST | `/api/image-generation/toggle` | Bildgenerierung AN/AUS (sync mit Permissions) |
| GET | `/api/image-generation/status` | Status |
| POST | `/api/permissions/toggle` | Permission AN/AUS `{permission: "search"\|"document"\|"knowledge"\|"image"}` |
| GET | `/api/permissions/status` | Alle Permission-Flags als JSON |
| GET | `/api/system-prompt` | System-Prompt abrufen |
| POST | `/api/system-prompt` | System-Prompt setzen `{prompt}` |
| POST | `/api/system-prompt/reset` | Auf Standard zurücksetzen |
| GET | `/api/prompt-style` | Aktiven Prompt-Stil abrufen |
| POST | `/api/prompt-style` | Stil setzen `{style: "danbooru"\|"mixed"\|"natural"}` |

### Chat-History
| Methode | Endpoint | Beschreibung |
|---------|----------|--------------|
| GET | `/api/chats` | Alle Chats |
| POST | `/api/chats` | Neuen Chat erstellen |
| GET | `/api/chats/<id>` | Chat + Nachrichten |
| PATCH | `/api/chats/<id>` | Umbenennen `{title}` |
| DELETE | `/api/chats/<id>` | Löschen |
| POST | `/api/chats/<id>/messages` | Nachrichten hinzufügen `{messages: [{role, content}]}` |
| POST | `/api/chats/<id>/generate-title` | Titel via LLM generieren `{user_message, assistant_message}` |

### Knowledge
| Methode | Endpoint | Beschreibung |
|---------|----------|--------------|
| GET | `/api/knowledge` | Dateiliste |
| GET | `/api/knowledge/<filename>` | Dateiinhalt |

### ComfyUI
| Methode | Endpoint | Beschreibung |
|---------|----------|--------------|
| GET | `/api/comfy/models` | UNET-Modelle (Anima) |
| GET | `/api/comfy/image-models?type=` | Modelle nach Typ gefiltert |
| GET | `/api/comfy/all-checkpoints` | Alle Checkpoints + UNETs (für Workflow-Editor) |
| GET | `/api/comfy/all-loras` | Alle LoRAs (für Workflow-Editor) |
| POST | `/api/comfy/generate` | Direkter Generate-Endpoint (Legacy) |

### Workflow-Editor
| Methode | Endpoint | Beschreibung |
|---------|----------|--------------|
| GET | `/workflows` | Workflow-Editor Seite (`workflows.html`) |
| GET | `/api/workflows` | Liste aller JSONs aus `/workflows/` Ordner |
| GET | `/api/workflows/<n>` | Einzelnen Workflow-JSON laden |
| POST | `/api/workflows/run` | Workflow ausführen → SSE Stream |
| POST | `/api/workflows/prompt-suggest` | Prompt generieren `{message}` → `{prompt, negative_prompt}` |
| POST | `/api/workflows/extract-from-image` | Workflow aus PNG-Metadaten extrahieren |

### Sonstiges
| Methode | Endpoint | Beschreibung |
|---------|----------|--------------|
| GET | `/download/<filename>` | Datei-Download aus OUTPUT_DIR |

---

## Frontend-JS (`frontend/`)

### `app.js` — Globaler State & Init
```javascript
let history = [];          // LLM-Konversationshistorie (max. 20 Einträge)
let attachedFiles = [];    // Angehängte Dateien
let isLoading = false;     // Sendebutton-Lock
let currentChatId = null;  // Aktive Chat-ID
```

Initialisiert beim Start: Drag&Drop, Modal-Listener, API-Status-Abfragen, `loadKnowledge()`, `loadModels()`, `loadChatHistory()`.

**Keyboard-Shortcuts:**
| Shortcut | Funktion |
|----------|----------|
| `Ctrl+N` | Neuer Chat — außer wenn Fokus in Input/Textarea/Select |

**Sidebar-Resize:**
Der Handle (`#sidebar-resize-handle`) ist ein 6px breiter Streifen an der rechten Sidebar-Kante. Per `mousedown/mousemove/mouseup` wird `--sidebar-width` als CSS Custom Property auf `<aside class="sidebar">` gesetzt. Breite wird in `localStorage` unter `sidebarWidth` persistent gespeichert und beim nächsten Laden wiederhergestellt. Min: 180px, Max: 520px.

---

### `chat.js` — Chat-Logik
- `sendMessage()` — Hauptfunktion, handled Datei-Upload (`/chat`) und Text (`/smart_chat`)
- `smartSend()` — Sendet an `/smart_chat` mit Temperature, Context-Length, Image-Settings, `forced_action` und Research-Slider-Werten
- `handleSmartStream()` — SSE-Parser für alle Event-Typen: `step | source | search_done | document_done | image_preview | image_progress | image_done | content | done | error`. Der `appendThinking()`-Indikator bleibt jetzt stehen bis das **erste echte Event** eintrifft — kein "eingefroren"-Gefühl mehr
- `loadChat()` — Lädt Chat aus DB, erkennt Bild-Messages (`{"__type":"image"...}`) und rendert sie korrekt
- `saveMsgsToDB()` — Speichert Nachrichten in SQLite. Löst nach dem **ersten** Nachrichtenpaar automatisch `generateChatTitle()` aus (fire & forget)
- `generateChatTitle(chatId, userMsg, assistantMsg)` — Ruft `POST /api/chats/<id>/generate-title` auf, aktualisiert danach die Chat-History-Liste. Schlägt lautlos fehl ohne den Chat-Flow zu unterbrechen
- `exportChat(chatId)` — Lädt den kompletten Chat als `.md`-Datei herunter. Bild-Messages werden als `[Bild generiert: <prompt>]` Platzhalter dargestellt

**Chat-History-Item-Aktionen:**
| Button | Funktion |
|--------|----------|
| ⬇️ | Chat als `.md` exportieren |
| ✏️ | Chat umbenennen |
| 🗑️ | Chat löschen |

---

### `ui.js` — DOM & Rendering
- `formatText()` — Markdown → HTML (Code-Blöcke, Tabellen, Listen, Bold/Italic, Headings)
- `appendMessage()`, `appendDocumentMessage()`, `appendThinking()` — Message-Bubbles
- `highlightCode()` — Highlight.js Integration
- `toggleAccordion()`, `autoResize()` — UI-Helpers

---

### `models.js` — Einstellungen & Modelle
- `loadModels()` / `renderModels()` — LM Studio Modell-Liste mit Laden/Entladen/Nutzen
- `updateActiveModelBadge()` — Header-Badge
- `toggleThinkMode()` / `toggleResearchMode()` — Einstellungs-Toggles
- `loadPermissions()` / `togglePermission(permission)` / `updatePermissionBtn()` — Permissions sync mit Server
- `loadKnowledge()` / `viewKnowledge()` — Knowledge-Browser
- `openSystemPromptModal()` / `saveSystemPrompt()` / `resetSystemPrompt()` — System-Prompt Editor

---

### `comfy.js` — Bildgenerierung UI

**State (mit localStorage Persistenz):**
```javascript
let imageModelType = localStorage.getItem('imgModelType') || 'anima';
let imageModelName = localStorage.getItem('imgModelName') || '';
let imageTurbo     = false;
let imageRawPrompt = false;
let promptStyle    = localStorage.getItem('promptStyle') || 'danbooru';
```

**Funktionen:**
- `toggleImageGeneration()` — AN/AUS via API, graut Panel-Body aus wenn AUS
- `setImageModelType(type)` — Wechselt Typ, lädt gefilterte Modelle, setzt Auto-Prompt-Stil, persistiert in localStorage
- `selectImageModel(el)` — Liest `data-fullpath` Attribut (voller Pfad!), persistiert
- `toggleTurbo()` / `toggleRawPrompt()` — Button-Toggles
- `setPromptStyle(style)` — Setzt Prompt-Stil lokal + sendet an `/api/prompt-style`
- `loadImageModels()` — Holt `GET /api/comfy/image-models?type=`
- `appendImageMessage()` — Rendert Bild-Bubble mit Download-Link und Fullscreen
- `saveImageMsgToDB()` — Speichert als JSON-String in messages-Tabelle

---

## Sidebar

### Reihenfolge & Struktur

```
💬 Chats              ← [+] Neuer Chat im Header
⚡ Schnellaktionen
⚙️ Einstellungen      ← Reasoning, System Prompt, Custom Workflow, Temp-Slider, Context-Slider
🔐 Aktionen           ← Suche, Research (+ Slider), Dokumente, Knowledge, Bilder
🖼️ Bildgenerierung    ← Modell-Typ, Modell, Turbo, Raw Prompt, Prompt-Stil
📚 Knowledge
🤖 Modelle
```

Die Sidebar ist per Drag-Handle an der rechten Kante **stufenlos in der Breite veränderbar** (180–520px). Die gewählte Breite wird in `localStorage` gespeichert.

### Einstellungen

| Element | Funktion |
|---------|---------|
| 🧠 Reasoning AN/AUS | Zeigt `reasoning_content` des Modells als ausklappbaren Denkprozess |
| 🧠 System Prompt | Öffnet Editor für Custom-Systemprompt |
| ⚙️ Custom Workflow | AN/AUS — blendet "Editor öffnen"-Link ein |
| 🌡️ Temperature | 0.0 – 2.0, default 0.30 |
| 📐 Context | 512 – 32768 Tokens, default 8.192 |

### Aktionen (Permissions)

Steuert welche Actions das Modell ausführen darf. Beim Start werden alle Status vom Server geladen (`GET /api/permissions/status`).

| Element | State-Flag | Effekt wenn AUS |
|---------|-----------|----------------|
| 🔍 Suche AN/AUS | `search_enabled` | Intent-Prompt bereinigt, Fallback auf `chat` |
| 🔬 Research AN/AUS | `research_enabled` | Seiten werden nicht gescrapt |
| 📋 Ergebnisse | — | Slider: Anzahl SearXNG-Ergebnisse (3–15, default 8) |
| 🌐 Min. Seiten | — | Slider: Mindest-Seiten zum Scrapen (1–8, default 5) |
| 📄 Dokumente AN/AUS | `document_enabled` | Intent-Prompt bereinigt, Fallback auf `chat` |
| 📚 Knowledge AN/AUS | `knowledge_enabled` | Intent-Prompt bereinigt, Fallback auf `chat` |
| 🖼️ Bilder AN/AUS | `image_generation_enabled` | REGEL 4 aus System-Prompt entfernt, Intent-Prompt bereinigt |

Die Research-Slider-Werte werden bei jedem `smartSend()` als `research_max_results` und `research_min_pages` mitgeschickt und von `search_searxng()` tatsächlich genutzt.

### Bildgenerierung Panel

```
┌─────────────────────────────┐
│ 🖼️ Bildgenerierung    Aktiv ●│
├─────────────────────────────┤
│ MODELL-TYP                  │
│ [🌸 Anima] [🎨 Illustrious] │
│ [⚡ Z-Image]                │
│ MODELL                      │
│ [Suchfeld         ▾]        │
│ [⚡ Turbo] [✏️ Raw Prompt]  │
│ PROMPT-STIL                 │
│ [🏷️ Tags] [✨ Mixed] [💬 Natural] │
└─────────────────────────────┘
```

**Aktiv-Toggle:** Schaltet `image_generation_enabled`. Wenn AUS: REGEL 4 wird aus System-Prompt herausgeschnitten, `generate_image` aus Intent-Prompt entfernt.

---

## Input-Bereich

Der Input-Bereich enthält nach dem Refactoring nur noch das **Force Action Dropdown** — Temperature und Context wurden in die Einstellungs-Sidebar verschoben.

| Option | Effekt |
|--------|--------|
| 🤖 Auto | Normales Verhalten — `_detect_intent()` entscheidet |
| 💬 Chat | Erzwingt direkte Chat-Antwort, kein Preflight-Call |
| 🔍 Suche | Erzwingt Websuche, kein Preflight-Call |
| 📄 Dokument | Erzwingt Dokument-Erstellung, kein Preflight-Call |
| 📚 Knowledge | Erzwingt Knowledge-Schreiben, kein Preflight-Call |
| 🖼️ Bild | Erzwingt Bildgenerierung, kein Preflight-Call |

---

## Auto-Titel-Generierung

Nach dem **ersten** Nachrichtenpaar in einem neuen Chat wird automatisch `POST /api/chats/<id>/generate-title` aufgerufen. Das LLM generiert einen 3–5 Wörter langen deutschen Titel (max. 20 Tokens, Temperature 0.3). Der Call läuft fire & forget — schlägt er fehl, bleibt der Titel "Neuer Chat". Der Titel wird in der Chat-History sofort aktualisiert.

---

## Workflow-Editor (`/workflows`)

Separate Seite für Custom ComfyUI Workflows. Erreichbar über `/workflows` oder den "Editor öffnen" Link in den Einstellungen.

### Funktionsweise

JSONs (ComfyUI API-Format Export) in den `/workflows/` Ordner legen — oder direkt aus einem generierten PNG laden. Der Server erkennt sie automatisch via `WORKFLOWS_DIR.glob("*.json")`.

> **Hinweis:** Der Workflow-Editor ist für *custom* JSON-Dateien. Die eingebauten Workflows (Anima, Illustrious, Z-Image) in `workflows.py` sind für den Hauptchat und erscheinen nicht in der Editor-Sidebar.

### Workflow aus Bild laden

PNG wird an `/api/workflows/extract-from-image` geschickt. Der Server liest die PNG `tEXt`/`iTXt` Chunks durch und sucht nach Key `"workflow"` (primär) oder `"prompt"` (Fallback). ComfyUI bettet diesen Chunk automatisch in jedes generierte Bild ein. Kein Extra-Paket nötig — reines Python `struct`.

### Auto-Parser (`workflow_ui.js`)

Der Parser traced Node-Verbindungen (`["node_id", output_index]`) und erkennt:

| Node-Typ | Generiertes UI-Element |
|----------|----------------------|
| `CLIPTextEncode` | Textarea — Rolle (positiv/negativ) über KSampler-Verbindung |
| `KSampler` | Steps/CFG Slider, Sampler/Scheduler Dropdowns, Seed + 🎲 / ∞ |
| `EmptyLatentImage` / `EmptySD3LatentImage` | Aspect-Ratio Buttons + Custom W×H |
| `UNETLoader` / `CheckpointLoaderSimple` | Klickbares Dropdown mit allen verfügbaren Modellen |
| `LoraLoader` | Klickbares Dropdown mit allen LoRAs + Model/CLIP Strength Sliders |
| `FaceDetailer` | Positiver Prompt wird mit Haupt-Prompt synchronisiert (hidden) |

### Run-Ablauf

`/api/workflows/run` nutzt `comfy_generate_stream()`. SSE-Events: `image_preview → image_progress → image_done`. Bilder nach `EXPORT_IMG_DIR`.

---

## Bekannte TODOs

- [ ] **WebSocket Preview** — `AnimaLayerReplayPatcher` in Anima Turbo liefert möglicherweise keine JPEG-Previews
- [ ] `api_comfy_generate` Route nutzt noch Legacy-Code ohne richtigen Workflow-Dispatch

---

## Bekannte Stolperfallen

**Import-Reihenfolge:** Alle Module importieren Globals aus `state.py`, nicht aus `server.py`. Neue Module dürfen nie `server.py` importieren — das erzeugt circular imports.

**Python Backslash-Escaping in Pfaden:**
Alle Pfade in `workflows.py` müssen doppelte Backslashes haben: `"Anima\\\\anima-preview2.safetensors"` sonst werden `\a`, `\t` etc. als Escape-Sequenzen interpretiert.

**Modell/LoRA Pfade im Workflow-Editor:** Pfade nie als String in `onclick`-Attribute schreiben. Fix: `data-index` Attribut + Lookup im JS-Array (`allCheckpoints[i]`).

**Modellname beim Illustrious:** ComfyUI gibt Modelle mit vollem Pfad zurück (`Illustrious\model.safetensors`). Der volle Pfad muss 1:1 an ComfyUI zurückgegeben werden. In `comfy.js` wird der Pfad über `data-fullpath` Attribut im DOM gespeichert.

**Bild-History:** Bilder werden als JSON-String in der `messages`-Tabelle gespeichert (`{"__type":"image",...}`). Beim Laden eines Chats muss `loadChat()` diese Messages erkennen und `appendImageMessage()` aufrufen statt `formatText()`.

**LLM-History bei Bildern:** Der volle Base64-String wird NICHT ans LLM geschickt. Stattdessen wird `[Bild generiert: <prompt>]` als Platzhalter verwendet.

**Workflow-Editor CSS fehlt → JS-Fehler:** Fehlt `.wf-model-select` / `.wf-model-list` CSS in `workflows.html`, crasht der Modell-Block beim Rendern und alle nachfolgenden Sections erscheinen nicht. CSS muss vollständig in `workflows.html` inline sein.

**PNG Workflow-Extraktion:** ComfyUI speichert den Workflow im `tEXt` Chunk mit Key `"workflow"`. Neuere Versionen nutzen `iTXt`. Beide werden unterstützt. Fallback auf `"prompt"` Chunk falls kein `"workflow"` gefunden.

**Prompt-Stil nach Server-Neustart:** `state.prompt_style` wird nicht persistent gespeichert. `comfy.js` meldet beim `DOMContentLoaded` den in `localStorage` gespeicherten Stil automatisch an den Server — dadurch bleibt der Stil nach Seiten-Reload korrekt. Nach Server-Neustart ohne Browser-Reload würde der Default `"danbooru"` gelten bis der User die Seite neu lädt.

**Intent/LLM-Mismatch:** `enforce_action()` in `llm.py` fängt Fälle ab wo der Preflight eine Action erkennt, der Haupt-LLM aber eine andere zurückgibt. Wird geloggt als `[ActionMismatch]` in der Konsole.

**Sidebar-Resize und overflow:** Die Sidebar nutzt `position: relative` damit der Resize-Handle (`position: absolute; right: -3px`) korrekt positioniert wird ohne den Layout-Flow zu brechen.
