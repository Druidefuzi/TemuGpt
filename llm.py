# ─── LLM.PY — LLM-Calls & Hilfsfunktionen ────────────────────────────────────

import re
import json
import requests
from config import LM_STUDIO_URL
import state
from prompts import SYSTEM_PROMPT, PROMPT_STYLES, THINKING_PROMPT, INTENT_PROMPT
from database import read_knowledge
from documents import read_file_content


# ─── HELPERS ──────────────────────────────────────────────────────────────────

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


def build_messages(message=None, history=None, files=None):
    """Baut die messages-Liste für den LLM-Call zusammen."""
    knowledge = read_knowledge()
    system    = state.custom_system_prompt if state.custom_system_prompt is not None else SYSTEM_PROMPT

    if not state.image_generation_enabled and state.custom_system_prompt is None:
        system = re.sub(r"REGEL 4.*?Mindestens 20-30 Tags\.\n\n", "", system, flags=re.DOTALL)
        system = system.replace("REGEL 5 -", "REGEL 4 -")

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

def _detect_intent(messages: list) -> dict:
    """Schneller Call um nur die Action zu erkennen."""
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
        print(f"[Intent] Action: {parsed.get('action')} | Prompt: {str(parsed.get('prompt',''))[:80]}")
        return parsed
    except Exception as e:
        print(f"[Intent] Fehler: {e}")
        return {"action": "chat"}


# ─── PROMPT GENERATION ────────────────────────────────────────────────────────

def generate_danbooru_prompt(user_message: str) -> dict:
    """Generiert einen Bild-Prompt im gewählten Stil."""
    style_prompt = PROMPT_STYLES.get(state.prompt_style, PROMPT_STYLES["danbooru"])
    print(f"[Prompt] Stil: {state.prompt_style}")
    try:
        resp = requests.post(LM_STUDIO_URL, json={
            "model":       state.active_model["name"],
            "messages":    [
                {"role": "system", "content": style_prompt},
                {"role": "user",   "content": user_message}
            ],
            "temperature": 0.4,
            "max_tokens":  400,
            "stream":      False
        }, timeout=30)
        resp.raise_for_status()
        text   = resp.json()["choices"][0]["message"].get("content", "")
        text   = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
        print(f"[Prompt] Raw: {text[:200]}")
        parsed = parse_json_response(text)
        if parsed.get("prompt"):
            print(f"[Prompt] ✅ ({state.prompt_style}): {parsed['prompt'][:80]}")
            return parsed
    except Exception as e:
        print(f"[Prompt] Fehler: {e}")
    return {
        "prompt":          f"masterpiece, best quality, score_7, {user_message}",
        "negative_prompt": "worst quality, low quality, score_1, score_2, score_3, blurry",
        "aspect_ratio":    "3:4 (Golden Ratio)"
    }


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