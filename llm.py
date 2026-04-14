# ─── LLM.PY — LLM-Calls & Hilfsfunktionen ────────────────────────────────────

import re
import json
import requests
from config import LM_STUDIO_URL, SKILLS_DIR, WILDCARDS_DIR, STYLES_DIR, THEMES_DIR, CHARACTERS_DIR
import state
import random
from prompts import SYSTEM_PROMPT, PROMPT_STYLES, THINKING_PROMPT, INTENT_PROMPT, get_system_prompt
from database import read_knowledge
from documents import read_file_content


# ─── HELPERS ──────────────────────────────────────────────────────────────────

# Wildcard file cache: {"artists": ["line1", ...], "colors": ["red", ...]}
_wildcard_cache = {}

def _load_wildcard(name: str) -> list:
    """Load a wildcard list, searching prepend/ then replace/. Cached."""
    if name in _wildcard_cache:
        return _wildcard_cache[name]
    for folder in ("prepend", "replace"):
        path = WILDCARDS_DIR / folder / f"{name}.txt"
        if path.exists():
            try:
                lines = [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
                _wildcard_cache[name] = lines
                print(f"[Wildcard] Loaded '{name}' from {folder}/ ({len(lines)} entries)")
                return lines
            except Exception as e:
                print(f"[Wildcard] Error loading {path}: {e}")
    print(f"[Wildcard] '{name}.txt' not found in prepend/ or replace/")
    _wildcard_cache[name] = []
    return []


def _wildcard_type(name: str) -> str:
    """Return 'prepend', 'replace', or 'unknown' based on folder location."""
    if (WILDCARDS_DIR / "prepend" / f"{name}.txt").exists():
        return "prepend"
    if (WILDCARDS_DIR / "replace" / f"{name}.txt").exists():
        return "replace"
    return "unknown"


def _pick_random(name: str) -> str:
    """Pick a random line from a wildcard file."""
    entries = _load_wildcard(name)
    if not entries:
        return ""
    chosen = random.choice(entries)
    print(f"[Wildcard] {name} -> '{chosen}'")
    return chosen


def _find_wildcards(text: str) -> list:
    """Find all {WILDCARD:name} patterns. Returns list of names."""
    return re.findall(r'\{WILDCARD:(\w+)\}', text, re.IGNORECASE)


def resolve_replace_wildcards(text: str, max_depth: int = 5) -> str:
    """Resolve 'replace/' wildcards in-place BEFORE LLM.
    Loops until no more wildcards remain (supports wildcards inside wildcards).
    Max depth prevents infinite recursion."""
    for depth in range(max_depth):
        found = [n for n in _find_wildcards(text) if _wildcard_type(n) == "replace"]
        if not found:
            break
        for name in found:
            value = _pick_random(name)
            pattern = re.compile(r'\{WILDCARD:' + re.escape(name) + r'\}', re.IGNORECASE)
            text = pattern.sub(value, text, count=1)
    return text


def strip_prepend_wildcards(text: str) -> tuple:
    """Strip 'prepend/' wildcards BEFORE LLM.
    Returns (cleaned_text, [resolved_values])."""
    prepend_values = []
    for name in _find_wildcards(text):
        if _wildcard_type(name) == "prepend":
            value = _pick_random(name)
            if value:
                prepend_values.append(value)
            pattern = re.compile(r',?\s*\{WILDCARD:' + re.escape(name) + r'\}\s*,?', re.IGNORECASE)
            text = pattern.sub(',', text)
    text = text.strip().strip(',').strip()
    return text, prepend_values


def apply_prepend_values(prompt: str, values: list) -> str:
    """Prepend resolved values to prompt AFTER LLM generation."""
    if not values:
        return prompt
    prefix = ", ".join(values)
    return f"{prefix}, {prompt}"


def resolve_all_wildcards(text: str, max_depth: int = 5) -> str:
    """Resolve ALL wildcards in-place (for raw prompts / workflow nodes).
    Loops until no more wildcards remain (supports nested wildcards)."""
    for depth in range(max_depth):
        found = _find_wildcards(text)
        if not found:
            break
        for name in found:
            value = _pick_random(name)
            pattern = re.compile(r'\{WILDCARD:' + re.escape(name) + r'\}', re.IGNORECASE)
            text = pattern.sub(value, text, count=1)
    return text


def read_prompt_skills(style: str) -> str:
    """Reads all text files from skills/image_prompt/<style>/ + shared/.
    Returns combined content as a single string, or empty string."""
    allowed = {".txt", ".md", ".html", ".json"}
    blocks = []

    for folder in ("shared", style):
        skill_dir = SKILLS_DIR / folder
        if not skill_dir.exists():
            continue
        for f in sorted(skill_dir.iterdir()):
            if f.is_file() and f.suffix.lower() in allowed:
                try:
                    content = f.read_text(encoding="utf-8").strip()
                    if content:
                        blocks.append(f"--- {folder}/{f.name} ---\n{content}")
                except Exception as e:
                    print(f"[Skills] Error reading {f}: {e}")

    if blocks:
        result = "\n\n".join(blocks)
        print(f"[Skills] Loaded {len(blocks)} files for style '{style}' ({len(result)} chars)")
        return result
    return ""

def enforce_action(parsed: dict, expected: str) -> dict:
    """Stellt sicher dass die geparste LLM-Action mit dem Intent übereinstimmt.
    Wenn das Modell eine andere Action zurückgibt, wird sie korrigiert und geloggt."""
    actual = parsed.get("action")
    if actual != expected:
        print(f"[ActionMismatch] Erwartet='{expected}' | LLM='{actual}' → erzwinge '{expected}'")
        parsed["action"] = expected
    return parsed


def parse_json_response(text: str) -> dict:
    try:
        return json.loads(text.strip())
    except:
        pass
    match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except:
            pass
    start, end = text.find('{'), text.rfind('}')
    if start != -1 and end != -1:
        try:
            return json.loads(text[start:end + 1])
        except:
            pass
    return {"action": "chat", "message": text}


# ─── CORE LLM CALL ────────────────────────────────────────────────────────────

def call_llm(messages, temperature=0.3, max_tokens=4096, context_length=None):
    """Non-streaming LLM call, gibt (text, reasoning) zurück."""
    payload = {
        "model":       state.active_model["name"],
        "messages":    messages,
        "temperature": temperature,
        "max_tokens":  max_tokens,
        "stream":      False
    }
    if context_length:
        payload["context_length"] = context_length
    resp = requests.post(LM_STUDIO_URL, json=payload, timeout=300)
    resp.raise_for_status()
    msg = resp.json()["choices"][0]["message"]
    return msg.get("content", ""), msg.get("reasoning_content", None)


def build_messages(message=None, history=None, files=None, action=None):
    """Baut die messages-Liste für den LLM-Call zusammen.
    action: Wenn gesetzt, wird Knowledge nur bei 'chat' und 'write_knowledge' geladen."""
    system = state.custom_system_prompt if state.custom_system_prompt is not None else get_system_prompt()

    if not state.image_generation_enabled and state.custom_system_prompt is None:
        system = re.sub(r"REGEL 4.*?Mindestens 20-30 Tags\.\n\n", "", system, flags=re.DOTALL)
        system = system.replace("REGEL 5 -", "REGEL 4 -")

    # Knowledge nur laden wenn relevant (chat, write_knowledge, oder action unbekannt)
    if action in (None, "chat", "write_knowledge"):
        knowledge = read_knowledge()
        if knowledge:
            system += f"\n\n--- DEIN KNOWLEDGE-ORDNER (aktueller Inhalt) ---\n{knowledge}\n--- ENDE KNOWLEDGE ---"

    messages = [{"role": "system", "content": system}]
    if history:
        messages.extend(history)

    if files or message:
        user_content = []
        for f in (files or []):
            if f.filename:
                result = read_file_content(f)
                if result["type"] == "image":
                    user_content.append({"type": "image_url", "image_url": {"url": f"data:{result['mime']};base64,{result['b64']}"}})
                else:
                    user_content.append({"type": "text", "text": result["content"]})
        if message:
            user_content.append({"type": "text", "text": message})

        if len(user_content) == 1 and user_content[0].get("type") == "text":
            messages.append({"role": "user", "content": user_content[0]["text"]})
        elif user_content:
            messages.append({"role": "user", "content": user_content})

    return messages


# ─── THINK ────────────────────────────────────────────────────────────────────

def think(message: str, history: list) -> dict:
    """Lässt das LLM intern über die Anfrage nachdenken."""
    think_messages = [
        {"role": "system", "content": THINKING_PROMPT},
        {"role": "user",   "content": f"Analysiere diese Anfrage: {message}"}
    ]
    try:
        resp = requests.post(LM_STUDIO_URL, json={
            "model":       state.active_model["name"],
            "messages":    think_messages,
            "temperature": 0.2,
            "max_tokens":  1024
        }, timeout=120)
        resp.raise_for_status()
        text   = resp.json()["choices"][0]["message"].get("content", "")
        parsed = parse_json_response(text)
        if parsed and "schritte" in parsed:
            return parsed
    except:
        pass
    return None


# ─── INTENT DETECTION ─────────────────────────────────────────────────────────

def _detect_intent(messages: list, forced_action: str = None) -> dict:
    """Schneller Call um nur die Action zu erkennen.
    forced_action überspringt den LLM-Call komplett."""

    # Forced action — direkt zurückgeben ohne LLM-Call
    if forced_action and forced_action != "auto":
        print(f"[Intent] Forced: {forced_action}")
        return {"action": forced_action}

    last_user = ""
    for m in reversed(messages):
        if m["role"] == "user":
            last_user = m["content"] if isinstance(m["content"], str) else str(m["content"])
            break

    recent_history = [m for m in messages if m["role"] in ("user", "assistant")][-4:]
    history_text   = ""
    for m in recent_history[:-1]:
        role    = "User" if m["role"] == "user" else "Assistant"
        content = m["content"] if isinstance(m["content"], str) else str(m["content"])
        history_text += f"{role}: {content[:200]}\n"

    context = f"Bisheriger Gesprächsverlauf:\n{history_text}\n" if history_text else ""

    active_intent_prompt = INTENT_PROMPT
    if not state.image_generation_enabled:
        active_intent_prompt = re.sub(r'- "generate_image".*?\n', "", active_intent_prompt)
    if not state.search_enabled:
        active_intent_prompt = re.sub(r'- "search".*?\n', "", active_intent_prompt)
    if not state.document_enabled:
        active_intent_prompt = re.sub(r'- "create_document".*?\n', "", active_intent_prompt)
    if not state.knowledge_enabled:
        active_intent_prompt = re.sub(r'- "write_knowledge".*?\n', "", active_intent_prompt)

    intent_messages = [
        {"role": "system", "content": active_intent_prompt},
        {"role": "user",   "content": f"{context}Aktuelle Nachricht: {last_user}"}
    ]
    try:
        resp = requests.post(LM_STUDIO_URL, json={
            "model":       state.active_model["name"],
            "messages":    intent_messages,
            "temperature": 0.0,
            "max_tokens":  200,
            "stream":      False
        }, timeout=15)
        resp.raise_for_status()
        text   = resp.json()["choices"][0]["message"].get("content", "")
        text   = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
        print(f"[Intent] Raw: {text[:200]}")
        parsed = parse_json_response(text)

        # Fallback auf chat wenn erkannte Action deaktiviert ist
        action = parsed.get("action", "chat")
        if action == "search"          and not state.search_enabled:   parsed["action"] = "chat"
        if action == "create_document" and not state.document_enabled:  parsed["action"] = "chat"
        if action == "write_knowledge" and not state.knowledge_enabled: parsed["action"] = "chat"
        if action == "generate_image"  and not state.image_generation_enabled: parsed["action"] = "chat"

        print(f"[Intent] Action: {parsed.get('action')} | Prompt: {str(parsed.get('prompt',''))[:80]}")
        return parsed
    except Exception as e:
        print(f"[Intent] Fehler: {e}")
        return {"action": "chat"}


# ─── PROMPT GENERATION ────────────────────────────────────────────────────────

def read_style_content(style_name: str) -> str:
    """Liest eine Style-Datei aus /styles/."""
    if not style_name:
        return ""
    path = STYLES_DIR / f"{style_name}.txt"
    try:
        content = path.read_text(encoding="utf-8").strip()
        if content:
            print(f"[Style] Loaded '{style_name}' ({len(content)} chars)")
        return content
    except Exception:
        return ""


def read_theme_content(theme_name: str) -> str:
    """Liest eine Theme-Datei aus /themes/."""
    if not theme_name:
        return ""
    path = THEMES_DIR / f"{theme_name}.txt"
    try:
        content = path.read_text(encoding="utf-8").strip()
        if content:
            print(f"[Theme] Loaded '{theme_name}' ({len(content)} chars)")
        return content
    except Exception:
        return ""


def read_character_content(character_name: str) -> str:
    """Liest eine Character-Datei aus /characters/."""
    if not character_name:
        return ""
    path = CHARACTERS_DIR / f"{character_name}.txt"
    try:
        content = path.read_text(encoding="utf-8").strip()
        if content:
            print(f"[Character] Loaded '{character_name}' ({len(content)} chars)")
        return content
    except Exception:
        return ""


def generate_danbooru_prompt(user_message: str) -> dict:
    """Generates an image prompt in the active style. Loads style-specific skills.
    Wildcards: replace/ resolved before LLM, prepend/ stripped before + prepended after."""
    style_prompt = PROMPT_STYLES.get(state.prompt_style, PROMPT_STYLES["danbooru"])

    # 1. Resolve replace/ wildcards (LLM needs to see the actual values)
    clean_message = resolve_replace_wildcards(user_message)

    # 2. Strip prepend/ wildcards (LLM doesn't need to see these)
    clean_message, prepend_values = strip_prepend_wildcards(clean_message)

    # Skills laden (style-spezifisch + shared)
    skills = read_prompt_skills(state.prompt_style)
    if skills:
        style_prompt += f"\n\n--- REFERENCE MATERIAL (use as guidance for better prompts) ---\n{skills}\n--- END REFERENCE ---"

    # Character zuerst injizieren (Basis des Bildes)
    character_content = read_character_content(getattr(state, 'active_image_character', None))
    if character_content:
        style_prompt += f"\n\n--- CHARACTER (use this as the primary subject of the image) ---\n{character_content}\n--- END CHARACTER ---"

    # Style-Datei injizieren wenn aktiv
    style_content = read_style_content(getattr(state, 'active_image_style', None))
    if style_content:
        style_prompt += f"\n\n--- VISUAL STYLE (incorporate this style into the generated prompt) ---\n{style_content}\n--- END STYLE ---"

    # Theme-Datei injizieren wenn aktiv
    theme_content = read_theme_content(getattr(state, 'active_image_theme', None))
    if theme_content:
        style_prompt += f"\n\n--- THEME (incorporate this theme/world into the generated prompt) ---\n{theme_content}\n--- END THEME ---"

    # Personality-Constraints injizieren (betrifft auch Prompt-Inhalt)
    if getattr(state, 'personality_enabled', True) and getattr(state, 'personality_affects_prompt', True):
        try:
            from config import PERSONALITY_DIR
            p_file = PERSONALITY_DIR / state.active_personality / "personality.txt"
            if p_file.exists():
                personality = p_file.read_text(encoding="utf-8").strip()
                if personality:
                    style_prompt += (
                        f"\n\n--- PERSONALITY CONSTRAINTS ---\n"
                        f"{personality}\n"
                        f"These constraints MUST be reflected in the generated prompt. "
                        f"If the personality restricts subject matter, those restrictions apply here too.\n"
                        f"--- END PERSONALITY CONSTRAINTS ---"
                    )
        except Exception:
            pass

    print(f"[Prompt] Style: {state.prompt_style} | Character: {getattr(state, 'active_image_character', None) or 'none'} | ImageStyle: {getattr(state, 'active_image_style', None) or 'default'} | Theme: {getattr(state, 'active_image_theme', None) or 'none'} | Skills: {'yes' if skills else 'none'} | Prepend: {prepend_values or 'none'}")
    try:
        resp = requests.post(LM_STUDIO_URL, json={
            "model":       state.active_model["name"],
            "messages":    [
                {"role": "system", "content": style_prompt},
                {"role": "user",   "content": clean_message}
            ],
            "temperature": 0.4,
            "max_tokens":  1000,
            "stream":      False
        }, timeout=30)
        resp.raise_for_status()
        text   = resp.json()["choices"][0]["message"].get("content", "")
        text   = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
        print(f"[Prompt] Raw: {text[:200]}")
        parsed = parse_json_response(text)
        if parsed.get("prompt"):
            # 3. Prepend values after LLM generation
            parsed["prompt"] = apply_prepend_values(parsed["prompt"], prepend_values)
            print(f"[Prompt] ✅ ({state.prompt_style}): {parsed['prompt'][:80]}")
            return parsed
    except Exception as e:
        print(f"[Prompt] Error: {e}")
    fallback = {
        "prompt":          f"masterpiece, best quality, score_7, {clean_message}",
        "negative_prompt": "worst quality, low quality, score_1, score_2, score_3, blurry",
        "aspect_ratio":    "3:4 (Golden Ratio)"
    }
    fallback["prompt"] = apply_prepend_values(fallback["prompt"], prepend_values)
    return fallback


# ─── STREAM GENERATOR ─────────────────────────────────────────────────────────

def stream_generator(messages, temperature=0.3, context_length=None):
    """Streamt die Chat-Antwort als SSE."""
    import json as _json
    yield "data: " + _json.dumps({"type": "meta", "mode": "chat", "think_enabled": state.thinking_enabled}) + "\n\n"

    payload = {
        "model":       state.active_model["name"],
        "messages":    messages,
        "temperature": temperature,
        "max_tokens":  4096,
        "stream":      True
    }
    if context_length:
        payload["context_length"] = context_length

    try:
        resp = requests.post(LM_STUDIO_URL, json=payload, stream=True, timeout=300)
        resp.raise_for_status()

        for line in resp.iter_lines():
            if not line:
                continue
            line = line.decode("utf-8")
            if line.startswith("data: "):
                line = line[6:]
            if line == "[DONE]":
                yield "data: " + _json.dumps({"type": "done"}) + "\n\n"
                break
            try:
                chunk = _json.loads(line)
                delta = chunk["choices"][0].get("delta", {})
                if delta.get("reasoning_content"):
                    yield "data: " + _json.dumps({"type": "reasoning", "text": delta["reasoning_content"]}) + "\n\n"
                if delta.get("content"):
                    yield "data: " + _json.dumps({"type": "content", "text": delta["content"]}) + "\n\n"
            except (json.JSONDecodeError, KeyError, IndexError):
                continue

    except requests.exceptions.ConnectionError:
        yield "data: " + _json.dumps({"type": "error", "text": "LM Studio nicht erreichbar!"}) + "\n\n"
    except Exception as e:
        yield "data: " + _json.dumps({"type": "error", "text": str(e)}) + "\n\n"

def critique_prompt(positive_prompt: str) -> dict:
    """Critiques a positive prompt. Returns score, issues, improved_prompt."""
    from prompts import PROMPT_CRITIC_PROMPT
    try:
        try:
            from config import PERSONALITY_DIR
            personality_on = getattr(state, 'personality_enabled', True)
            affects_critic = getattr(state, 'personality_affects_critic', True)
            if personality_on and affects_critic:
                p_file = PERSONALITY_DIR / state.active_personality / "personality.txt"
                personality = p_file.read_text(encoding="utf-8").strip() if p_file.exists() else ""
            else:
                personality = ""
        except Exception:
            personality = ""
        system = PROMPT_CRITIC_PROMPT
        if personality:
            system = f"{PROMPT_CRITIC_PROMPT}\n\nYour personality while giving feedback: {personality}"
        text, _ = call_llm([
            {"role": "system", "content": system},
            {"role": "user",   "content": positive_prompt}
        ], temperature=0.2, max_tokens=600)
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
        parsed = parse_json_response(text)
        if "score" in parsed:
            print(f"[Critic] Score: {parsed['score']}/10 | Issues: {len(parsed.get('issues', []))}")
            return parsed
    except Exception as e:
        print(f"[Critic] Error: {e}")
    return {"score": None, "issues": [], "improved_prompt": positive_prompt}