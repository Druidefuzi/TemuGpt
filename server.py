"""
LM Studio Office Assistant - Flask Backend
==========================================
Starten: python server.py
Browser: http://localhost:5000
"""

from flask import Flask, request, jsonify, send_from_directory, send_file, Response, stream_with_context
import requests
import json
import re
import base64
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

# ─── Eigene Module ─────────────────────────────────────────────────────────────
from config import (LM_API, COMFY_URL, OUTPUT_DIR, EXPORT_IMG_DIR,
                    KNOWLEDGE_DIR, WORKFLOWS_DIR, MODEL_DEFAULT)
import state
from prompts import SYSTEM_PROMPT, PROMPT_STYLES
from database import get_db, init_db, read_knowledge, write_knowledge
from documents import save_document
from search import search_searxng, fetch_page, format_search_results
from llm import (parse_json_response, enforce_action, call_llm, build_messages,
                 think, _detect_intent, generate_danbooru_prompt, stream_generator)
from comfy_backend import comfy_get_models, comfy_get_models_by_type, comfy_generate_stream
from workflows import build_workflow

app = Flask(__name__, static_folder="frontend")


# ─── INIT ──────────────────────────────────────────────────────────────────────

def _init_active_model():
    """Beim Start: holt das erste geladene Modell aus LM Studio."""
    try:
        resp = requests.get(f"{LM_API}/api/v1/models", timeout=3)
        if resp.ok:
            for m in resp.json().get("models", []):
                if m.get("loaded_instances"):
                    state.active_model["name"] = m["key"]
                    print(f"[Init] Aktives Modell: {m['display_name']} ({m['key']})")
                    return
        print(f"[Init] Kein geladenes Modell gefunden, nutze Default: {MODEL_DEFAULT}")
    except:
        print(f"[Init] LM Studio nicht erreichbar, nutze Default: {MODEL_DEFAULT}")


# ─── ROUTES — Seiten ───────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("frontend", "index.html")

@app.route("/workflows")
def workflows_page():
    return send_from_directory("frontend", "workflows.html")

@app.route("/download/<filename>")
def download(filename):
    safe = re.sub(r'[<>:"/\\|?*]', '_', filename)
    path = OUTPUT_DIR / safe
    if path.exists():
        return send_file(path, as_attachment=True)
    return "Datei nicht gefunden", 404


# ─── ROUTES — Chat ─────────────────────────────────────────────────────────────

@app.route("/chat", methods=["POST"])
def chat():
    """Blocking endpoint für File-Uploads."""
    message     = request.form.get("message", "")
    history     = json.loads(request.form.get("history", "[]"))
    files       = request.files.getlist("files")
    messages    = build_messages(message=message, history=history, files=files)

    thinking = None
    if state.thinking_enabled and message and len(message) > 15:
        thinking = think(message, history)

    try:
        llm_text, llm_reasoning = call_llm(messages)
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "LM Studio nicht erreichbar. Server gestartet?"}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    parsed = parse_json_response(llm_text)

    if parsed.get("action") == "write_knowledge":
        filename     = parsed.get("filename", "notes.txt")
        file_content = parsed.get("content", "")
        msg          = parsed.get("message", f"{filename} wurde aktualisiert.")
        ok           = write_knowledge(filename, file_content)
        return jsonify({
            "action":    "chat",
            "message":   f"{'✅' if ok else '❌'} **{filename}** {'gespeichert' if ok else 'Fehler beim Speichern'} — {msg}",
            "thinking":  thinking,
            "reasoning": llm_reasoning
        })

    if parsed.get("action") == "search":
        query       = parsed.get("query", message)
        results     = search_searxng(query)
        search_text = format_search_results(query, results)
        messages.append({"role": "assistant", "content": llm_text})
        messages.append({
            "role":    "user",
            "content": f"Hier sind die Suchergebnisse:\n\n{search_text}\n\nBitte beantworte nun die ursprüngliche Frage basierend auf diesen Ergebnissen. Antworte im chat-JSON-Format."
        })
        try:
            llm_text2, _ = call_llm(messages)
            parsed = parse_json_response(llm_text2)
            if parsed.get("action") == "chat":
                parsed["message"] = f"🔍 *Gesucht nach: {query}*\n\n" + parsed.get("message", "")
        except Exception as e:
            return jsonify({"action": "chat", "message": f"Suche ok, aber Fehler bei Antwort: {e}"}), 500

    if parsed.get("action") == "create_document":
        try:
            path, filename = save_document(parsed)
            return jsonify({
                "action":       "create_document",
                "message":      f"✅ **{parsed.get('titel', filename)}** wurde erstellt!",
                "filename":     filename,
                "download_url": f"/download/{filename}",
                "thinking":     thinking,
                "reasoning":    llm_reasoning
            })
        except Exception as e:
            return jsonify({"action": "chat", "message": f"Fehler beim Erstellen: {e}"}), 500

    return jsonify({
        "action":    "chat",
        "message":   parsed.get("message", llm_text),
        "thinking":  thinking,
        "reasoning": llm_reasoning
    })


@app.route("/smart_chat", methods=["POST"])
def smart_chat():
    data           = request.json
    message        = data.get("message", "")
    history        = data.get("history", [])
    temperature    = float(data.get("temperature", 0.3))
    context_length = int(data.get("context_length", 8192))
    forced_action  = data.get("forced_action", "auto")
    messages       = build_messages(message=message, history=history)

    intent = _detect_intent(messages, forced_action=forced_action)
    action = intent.get("action", "chat")

    # ── Dokument erstellen ────────────────────────────────────────────────────
    if action == "create_document":
        def doc_generator():
            yield "data: " + json.dumps({"type": "step", "text": "📋 Dokument wird generiert...", "status": "active"}) + "\n\n"
            try:
                llm_text, _ = call_llm(messages, temperature=temperature, max_tokens=4096, context_length=context_length)
                doc_data = enforce_action(parse_json_response(llm_text), "create_document")
                if not doc_data.get("inhalt") and not doc_data.get("tabellen"):
                    yield "data: " + json.dumps({"type": "step", "text": "❌ LLM hat kein Dokument generiert", "status": "error"}) + "\n\n"
                    yield "data: " + json.dumps({"type": "done"}) + "\n\n"
                    return
                yield "data: " + json.dumps({"type": "step", "text": "💾 Speichere Datei...", "status": "active"}) + "\n\n"
                path, filename = save_document(doc_data)
                yield "data: " + json.dumps({
                    "type":         "document_done",
                    "message":      f"✅ **{doc_data.get('titel', filename)}** wurde erstellt!",
                    "filename":     filename,
                    "download_url": f"/download/{filename}"
                }) + "\n\n"
            except Exception as e:
                yield "data: " + json.dumps({"type": "step", "text": f"❌ Fehler: {e}", "status": "error"}) + "\n\n"
                yield "data: " + json.dumps({"type": "done"}) + "\n\n"

        return Response(stream_with_context(doc_generator()), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ── Suche ─────────────────────────────────────────────────────────────────
    if action == "search":
        def search_generator():
            query = intent.get("query", message)
            yield "data: " + json.dumps({"type": "step", "text": f"🔍 Durchsuche Internet nach: {query}", "status": "active"}) + "\n\n"
            try:
                resp = requests.get("http://localhost:8888/search",
                                    params={"q": query, "format": "json", "language": "de-DE"}, timeout=10)
                resp.raise_for_status()
                raw_results = resp.json().get("results", [])
            except Exception as e:
                yield "data: " + json.dumps({"type": "step", "text": f"❌ Suche fehlgeschlagen: {e}", "status": "error"}) + "\n\n"
                yield "data: " + json.dumps({"type": "search_done", "message": "Die Suche ist leider fehlgeschlagen."}) + "\n\n"
                return

            results = [{"title": r.get("title",""), "snippet": r.get("content",""), "url": r.get("url","")}
                       for r in raw_results[:8]]
            yield "data: " + json.dumps({"type": "step", "text": f"✅ {len(results)} Ergebnisse gefunden", "status": "done"}) + "\n\n"

            if state.research_enabled and results:
                yield "data: " + json.dumps({"type": "step", "text": "📄 Lese Seiteninhalte...", "status": "active"}) + "\n\n"
                successful = 0
                for r in results:
                    if successful >= 5: break
                    if r["url"]:
                        content = fetch_page(r["url"], query=query)
                        if content:
                            r["full_content"] = content
                            successful += 1
                            try:
                                host = urlparse(r["url"]).netloc.replace("www.", "")
                            except:
                                host = r["url"][:40]
                            yield "data: " + json.dumps({"type": "source", "title": r["title"][:50], "host": host, "url": r["url"]}) + "\n\n"
                yield "data: " + json.dumps({"type": "step", "text": f"📄 {successful} Seiten gelesen", "status": "done"}) + "\n\n"

            yield "data: " + json.dumps({"type": "step", "text": "🧠 Analysiere Ergebnisse...", "status": "active"}) + "\n\n"
            search_text = format_search_results(query, results)
            msgs = messages.copy()
            msgs.append({"role": "assistant", "content": json.dumps(intent)})
            msgs.append({"role": "user", "content": f"Hier sind die Suchergebnisse mit Seiteninhalten:\n\n{search_text}\n\nBitte beantworte die ursprüngliche Frage detailliert basierend auf diesen Inhalten. Antworte im chat-JSON-Format."})
            yield "data: " + json.dumps({"type": "step", "text": "✍️ Formuliere Antwort...", "status": "active"}) + "\n\n"
            try:
                llm_text, _ = call_llm(msgs, temperature=temperature, context_length=context_length)
                parsed = parse_json_response(llm_text)
                reply  = f"🔍 *Gesucht nach: {query}*\n\n" + parsed.get("message", llm_text)
            except Exception as e:
                reply = f"Suche ok, aber Fehler: {e}"
            yield "data: " + json.dumps({"type": "search_done", "message": reply}) + "\n\n"

        return Response(stream_with_context(search_generator()), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ── Knowledge schreiben ───────────────────────────────────────────────────
    if action == "write_knowledge":
        try:
            llm_text, _ = call_llm(messages, temperature=temperature, max_tokens=4096, context_length=context_length)
            wk_data      = enforce_action(parse_json_response(llm_text), "write_knowledge")
            filename     = wk_data.get("filename", "notes.txt")
            file_content = wk_data.get("content", "")
            msg          = wk_data.get("message", f"{filename} wurde aktualisiert.")
            if not file_content:
                return jsonify({"mode": "chat", "message": "❌ Kein Inhalt zum Speichern generiert."})
            ok = write_knowledge(filename, file_content)
            return jsonify({"mode": "chat", "message": f"{'✅' if ok else '❌'} **{filename}** {'gespeichert' if ok else 'Fehler beim Speichern'} — {msg}"})
        except Exception as e:
            return jsonify({"mode": "chat", "message": f"Fehler: {e}"})

    # ── Bild generieren ───────────────────────────────────────────────────────
    if action == "generate_image":
        img_prompt      = intent.get("prompt", message)
        negative_prompt = intent.get("negative_prompt", "worst quality, low quality, score_1, score_2, blurry, jpeg artifacts")
        aspect_ratio    = intent.get("aspect_ratio", "3:4 (Golden Ratio)")
        img_model_type  = data.get("image_model_type", "anima")
        img_model_name  = data.get("image_model_name", "")
        img_turbo       = bool(data.get("image_turbo", False))
        img_raw_prompt  = bool(data.get("image_raw_prompt", False))

        def img_generator():
            if img_raw_prompt:
                final_prompt   = img_prompt
                final_negative = negative_prompt
                final_ratio    = aspect_ratio
                yield "data: " + json.dumps({"type": "step", "text": f"✏️ Raw: {final_prompt[:80]}{'…' if len(final_prompt) > 80 else ''}", "status": "done"}) + "\n\n"
            else:
                yield "data: " + json.dumps({"type": "step", "text": "🏷️ Generiere Prompt...", "status": "active"}) + "\n\n"
                danbooru       = generate_danbooru_prompt(message)
                final_prompt   = danbooru.get("prompt", img_prompt)
                final_negative = danbooru.get("negative_prompt", negative_prompt)
                final_ratio    = danbooru.get("aspect_ratio", aspect_ratio)
                yield "data: " + json.dumps({"type": "step", "text": f"✏️ {final_prompt[:80]}{'…' if len(final_prompt) > 80 else ''}", "status": "done"}) + "\n\n"

            model_name = img_model_name
            if not model_name:
                available  = comfy_get_models_by_type(img_model_type)
                model_name = available[0] if available else ""
            short_name = model_name.split("\\")[-1].split("/")[-1]
            turbo_tag  = " ⚡Turbo" if img_turbo else ""
            type_label = {"anima": "🌸 Anima", "illustrious": "🎨 Illustrious", "zimage": "⚡ Z-Image"}.get(img_model_type, img_model_type) + turbo_tag
            yield "data: " + json.dumps({"type": "step", "text": f"{type_label} · {short_name}", "status": "done"}) + "\n\n"

            try:
                instance_id  = state.active_model["name"]
                unload_resp  = requests.post(f"{LM_API}/api/v1/models/unload", json={"instance_id": instance_id}, timeout=10)
                if unload_resp.ok:
                    print(f"[Image] LLM '{instance_id}' entladen")
                    yield "data: " + json.dumps({"type": "step", "text": "🧹 LLM entladen (VRAM frei)", "status": "done"}) + "\n\n"
            except Exception as ue:
                print(f"[Image] Entladen fehlgeschlagen: {ue}")

            yield "data: " + json.dumps({"type": "step", "text": "🖼️ Generiere Bild...", "status": "active"}) + "\n\n"

            try:
                workflow = build_workflow(img_model_type, final_prompt, final_negative, final_ratio, model_name, turbo=img_turbo)
            except Exception as we:
                yield "data: " + json.dumps({"type": "step", "text": f"❌ Workflow Fehler: {we}", "status": "error"}) + "\n\n"
                yield "data: " + json.dumps({"type": "done"}) + "\n\n"
                return

            for event in comfy_generate_stream(workflow, img_model_type):
                etype = event.get("type")
                if etype == "image_preview":
                    yield "data: " + json.dumps({"type": "image_preview", "b64": event["b64"]}) + "\n\n"
                elif etype == "image_progress":
                    yield "data: " + json.dumps({"type": "image_progress", "value": event["value"], "max": event["max"], "pct": event["pct"]}) + "\n\n"
                elif etype == "image_final":
                    try:
                        from datetime import datetime as dt
                        ts        = dt.now().strftime("%Y%m%d_%H%M%S")
                        save_path = EXPORT_IMG_DIR / f"{ts}_{event['filename']}"
                        save_path.write_bytes(event["img_bytes"])
                        print(f"[Image] Gespeichert: {save_path}")
                    except Exception as se:
                        print(f"[Image] Speichern fehlgeschlagen: {se}")
                    yield "data: " + json.dumps({
                        "type":       "image_done",
                        "image_b64":  event["b64"],
                        "filename":   event["filename"],
                        "model":      short_name,
                        "model_type": img_model_type,
                        "prompt":     img_prompt
                    }) + "\n\n"
                    return
                elif etype == "error":
                    yield "data: " + json.dumps({"type": "step", "text": f"❌ {event.get('text')}", "status": "error"}) + "\n\n"
                    yield "data: " + json.dumps({"type": "done"}) + "\n\n"
                    return

        return Response(stream_with_context(img_generator()), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ── Normaler Chat Stream ──────────────────────────────────────────────────
    return Response(
        stream_with_context(stream_generator(messages, temperature=temperature, context_length=context_length)),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@app.route("/stream-think", methods=["POST"])
def stream_think():
    """Streamt den Fake-Think Prozess als SSE."""
    data    = request.json
    message = data.get("message", "")

    if not state.thinking_enabled or not message or len(message) <= 15:
        return Response("data: " + '{"type": "skip"}' + "\n\n", mimetype="text/event-stream")

    from prompts import THINKING_PROMPT
    from config  import LM_STUDIO_URL

    think_messages = [
        {"role": "system", "content": THINKING_PROMPT},
        {"role": "user",   "content": f"Analysiere diese Anfrage: {message}"}
    ]

    def generate():
        try:
            resp = requests.post(LM_STUDIO_URL, json={
                "model":       state.active_model["name"],
                "messages":    think_messages,
                "temperature": 0.2,
                "max_tokens":  1024,
                "stream":      True
            }, stream=True, timeout=120)
            resp.raise_for_status()
            full = ""
            for line in resp.iter_lines():
                if not line: continue
                line = line.decode("utf-8")
                if line.startswith("data: "): line = line[6:]
                if line == "[DONE]":
                    parsed = parse_json_response(full)
                    yield "data: " + json.dumps({"type": "think_done", "parsed": parsed}) + "\n\n"
                    break
                try:
                    chunk = json.loads(line)
                    delta = chunk["choices"][0].get("delta", {})
                    if delta.get("content"):
                        full += delta["content"]
                        yield "data: " + json.dumps({"type": "think_token", "text": delta["content"]}) + "\n\n"
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
        except Exception as e:
            yield "data: " + json.dumps({"type": "error", "text": str(e)}) + "\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ─── ROUTES — Modelle ──────────────────────────────────────────────────────────

@app.route("/api/models", methods=["GET"])
def list_models():
    try:
        resp = requests.get(f"{LM_API}/api/v1/models", timeout=5)
        if not resp.ok:
            return jsonify({"models": [], "active": state.active_model["name"], "loaded_ids": []})
        models_raw = resp.json().get("models", [])
    except Exception as e:
        print(f"[Models] Fehler: {e}")
        return jsonify({"models": [], "active": state.active_model["name"], "loaded_ids": []})

    available  = []
    loaded_ids = []
    for m in models_raw:
        key              = m.get("key", "")
        loaded_instances = m.get("loaded_instances", [])
        is_loaded        = len(loaded_instances) > 0
        instance_id      = loaded_instances[0]["id"] if loaded_instances else None
        if is_loaded: loaded_ids.append(key)
        available.append({
            "id":          key,
            "name":        m.get("display_name", key),
            "folder":      m.get("publisher", ""),
            "load_id":     key,
            "instance_id": instance_id,
            "size_gb":     round(m.get("size_bytes", 0) / 1e9, 1),
            "loaded":      is_loaded,
            "active":      state.active_model["name"] == key,
            "type":        m.get("type", "llm"),
        })
    available.sort(key=lambda x: (not x["loaded"], x["name"]))
    return jsonify({"models": available, "active": state.active_model["name"], "loaded_ids": loaded_ids})


@app.route("/api/models/load", methods=["POST"])
def load_model():
    data         = request.json
    load_id      = data.get("load_id", "")
    display_name = data.get("name", load_id)
    gpu_offload  = data.get("gpu_offload", 1)
    if not load_id:
        return jsonify({"ok": False, "error": "Kein load_id angegeben"}), 400
    try:
        resp = requests.post(f"{LM_API}/api/v1/models/load", json={
            "model": load_id, "flash_attention": True, "offload_kv_cache_to_gpu": True
        }, timeout=60)
        if resp.ok:
            instance_id = resp.json().get("instance_id", load_id)
            state.active_model["name"] = instance_id
            print(f"[Model] Geladen: {display_name} (GPU: {gpu_offload*100:.0f}%)")
            return jsonify({"ok": True, "active": instance_id})
        return jsonify({"ok": False, "error": resp.text}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/models/unload", methods=["POST"])
def unload_model():
    data        = request.json
    instance_id = data.get("instance_id", "")
    try:
        resp = requests.post(f"{LM_API}/api/v1/models/unload", json={"instance_id": instance_id}, timeout=30)
        if resp.ok:
            if state.active_model["name"] == instance_id:
                state.active_model["name"] = MODEL_DEFAULT
            return jsonify({"ok": True})
        return jsonify({"ok": False, "error": resp.text}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/models/active", methods=["GET"])
def get_active_model():
    return jsonify({"active": state.active_model["name"]})

@app.route("/api/models/active", methods=["POST"])
def set_active_model():
    data     = request.json
    model_id = data.get("id", "")
    if not model_id:
        return jsonify({"ok": False, "error": "Kein Modell-ID"}), 400
    state.active_model["name"] = model_id
    print(f"[Model] Aktives Modell: {model_id}")
    return jsonify({"ok": True, "active": model_id})


# ─── ROUTES — Einstellungen ────────────────────────────────────────────────────

@app.route("/api/thinking/toggle",  methods=["POST"])
def toggle_thinking():
    state.thinking_enabled = not state.thinking_enabled
    return jsonify({"enabled": state.thinking_enabled})

@app.route("/api/thinking/status",  methods=["GET"])
def thinking_status():
    return jsonify({"enabled": state.thinking_enabled})

@app.route("/api/research/toggle",  methods=["POST"])
def toggle_research():
    state.research_enabled = not state.research_enabled
    print(f"[Research] Modus: {'AN' if state.research_enabled else 'AUS'}")
    return jsonify({"enabled": state.research_enabled})

@app.route("/api/research/status",  methods=["GET"])
def research_status():
    return jsonify({"enabled": state.research_enabled})

@app.route("/api/image-generation/toggle", methods=["POST"])
def toggle_image_generation():
    state.image_generation_enabled = not state.image_generation_enabled
    print(f"[ImageGen] {'AN' if state.image_generation_enabled else 'AUS'}")
    return jsonify({"enabled": state.image_generation_enabled})

@app.route("/api/image-generation/status", methods=["GET"])
def image_generation_status():
    return jsonify({"enabled": state.image_generation_enabled})

@app.route("/api/permissions/toggle", methods=["POST"])
def toggle_permission():
    data       = request.json
    permission = data.get("permission", "")
    flag_map   = {
        "search":    "search_enabled",
        "document":  "document_enabled",
        "knowledge": "knowledge_enabled",
        "image":     "image_generation_enabled",
    }
    if permission not in flag_map:
        return jsonify({"ok": False, "error": "Unbekannte Permission"}), 400
    attr = flag_map[permission]
    new_val = not getattr(state, attr)
    setattr(state, attr, new_val)
    print(f"[Permission] {permission}: {'AN' if new_val else 'AUS'}")
    return jsonify({"permission": permission, "enabled": new_val})

@app.route("/api/permissions/status", methods=["GET"])
def permissions_status():
    return jsonify({
        "search":    state.search_enabled,
        "document":  state.document_enabled,
        "knowledge": state.knowledge_enabled,
        "image":     state.image_generation_enabled,
    })

@app.route("/api/system-prompt", methods=["GET"])
def get_system_prompt():
    return jsonify({"prompt": state.custom_system_prompt if state.custom_system_prompt is not None else SYSTEM_PROMPT})

@app.route("/api/system-prompt", methods=["POST"])
def set_system_prompt():
    data = request.json
    state.custom_system_prompt = data.get("prompt", "").strip() or None
    print(f"[SystemPrompt] Geändert ({len(state.custom_system_prompt or '')} Zeichen)")
    return jsonify({"ok": True})

@app.route("/api/system-prompt/reset", methods=["POST"])
def reset_system_prompt():
    state.custom_system_prompt = None
    print("[SystemPrompt] Auf Default zurückgesetzt")
    return jsonify({"ok": True, "prompt": SYSTEM_PROMPT})

@app.route("/api/prompt-style", methods=["GET", "POST"])
def prompt_style_endpoint():
    if request.method == "POST":
        new_style = request.json.get("style", "danbooru")
        if new_style in PROMPT_STYLES:
            state.prompt_style = new_style
            print(f"[PromptStyle] Geändert: {state.prompt_style}")
        return jsonify({"style": state.prompt_style})
    return jsonify({"style": state.prompt_style})


# ─── ROUTES — Knowledge ────────────────────────────────────────────────────────

@app.route("/api/knowledge", methods=["GET"])
def list_knowledge():
    files   = []
    allowed = {".html", ".css", ".js", ".txt", ".md", ".json"}
    for f in sorted(KNOWLEDGE_DIR.iterdir()):
        if f.is_file() and f.suffix.lower() in allowed:
            files.append({
                "name":     f.name,
                "size":     f.stat().st_size,
                "modified": datetime.fromtimestamp(f.stat().st_mtime).strftime("%d.%m %H:%M")
            })
    return jsonify({"files": files, "dir": str(KNOWLEDGE_DIR)})

@app.route("/api/knowledge/<filename>", methods=["GET"])
def get_knowledge_file(filename):
    path = KNOWLEDGE_DIR / Path(filename).name
    if path.exists():
        return path.read_text(encoding="utf-8"), 200, {"Content-Type": "text/plain; charset=utf-8"}
    return "Nicht gefunden", 404


# ─── ROUTES — Chat-History ─────────────────────────────────────────────────────

@app.route("/api/chats", methods=["GET"])
def list_chats():
    with get_db() as conn:
        chats = conn.execute(
            "SELECT id, title, model, created, updated FROM chats ORDER BY updated DESC"
        ).fetchall()
    return jsonify({"chats": [dict(c) for c in chats]})

@app.route("/api/chats", methods=["POST"])
def create_chat():
    now = datetime.now().isoformat()
    with get_db() as conn:
        cur     = conn.execute(
            "INSERT INTO chats (title, model, created, updated) VALUES (?, ?, ?, ?)",
            ("Neuer Chat", state.active_model["name"], now, now)
        )
        chat_id = cur.lastrowid
    return jsonify({"id": chat_id, "title": "Neuer Chat"})

@app.route("/api/chats/<int:chat_id>", methods=["GET"])
def get_chat(chat_id):
    with get_db() as conn:
        chat     = conn.execute("SELECT * FROM chats WHERE id=?", (chat_id,)).fetchone()
        if not chat:
            return jsonify({"error": "Chat nicht gefunden"}), 404
        messages = conn.execute(
            "SELECT role, content, created FROM messages WHERE chat_id=? ORDER BY id",
            (chat_id,)
        ).fetchall()
    return jsonify({"chat": dict(chat), "messages": [dict(m) for m in messages]})

@app.route("/api/chats/<int:chat_id>", methods=["PATCH"])
def rename_chat(chat_id):
    title = request.json.get("title", "").strip()
    if not title:
        return jsonify({"error": "Kein Titel"}), 400
    now = datetime.now().isoformat()
    with get_db() as conn:
        conn.execute("UPDATE chats SET title=?, updated=? WHERE id=?", (title, now, chat_id))
    return jsonify({"ok": True})

@app.route("/api/chats/<int:chat_id>", methods=["DELETE"])
def delete_chat(chat_id):
    with get_db() as conn:
        conn.execute("DELETE FROM chats WHERE id=?", (chat_id,))
    return jsonify({"ok": True})

@app.route("/api/chats/<int:chat_id>/messages", methods=["POST"])
def add_messages(chat_id):
    data = request.json
    msgs = data.get("messages", [])
    now  = datetime.now().isoformat()
    with get_db() as conn:
        chat = conn.execute("SELECT * FROM chats WHERE id=?", (chat_id,)).fetchone()
        if not chat:
            return jsonify({"error": "Chat nicht gefunden"}), 404
        for m in msgs:
            conn.execute(
                "INSERT INTO messages (chat_id, role, content, created) VALUES (?, ?, ?, ?)",
                (chat_id, m["role"], m["content"], now)
            )
        if chat["title"] == "Neuer Chat":
            first_user = next((m["content"] for m in msgs if m["role"] == "user"), None)
            if first_user:
                title = first_user[:50] + ("..." if len(first_user) > 50 else "")
                conn.execute("UPDATE chats SET title=?, updated=? WHERE id=?", (title, now, chat_id))
            else:
                conn.execute("UPDATE chats SET updated=? WHERE id=?", (now, chat_id))
        else:
            conn.execute("UPDATE chats SET updated=? WHERE id=?", (now, chat_id))
    return jsonify({"ok": True})


# ─── ROUTES — ComfyUI ──────────────────────────────────────────────────────────

@app.route("/api/comfy/generate", methods=["POST"])
def api_comfy_generate():
    data         = request.json
    prompt_text  = data.get("prompt", "")
    aspect_ratio = data.get("aspect_ratio", "3:4 (Golden Ratio)")
    if not prompt_text:
        return jsonify({"ok": False, "error": "Kein Prompt angegeben"}), 400

    def generate():
        yield "data: " + json.dumps({"type": "step", "text": "🎨 Verbinde mit ComfyUI...", "status": "active"}) + "\n\n"
        models = comfy_get_models()
        if not models:
            yield "data: " + json.dumps({"type": "step", "text": "⚠️ Keine Modelle gefunden", "status": "done"}) + "\n\n"
        else:
            yield "data: " + json.dumps({"type": "step", "text": f"🤖 Modell: {models[0].split(chr(92))[-1].split('/')[-1]}", "status": "done"}) + "\n\n"
        yield "data: " + json.dumps({"type": "step", "text": "🖼️ Generiere Bild...", "status": "active"}) + "\n\n"
        # Legacy — nutzt comfy_generate_stream direkt mit leerem Workflow
        yield "data: " + json.dumps({"type": "done"}) + "\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.route("/api/comfy/models",          methods=["GET"])
def api_comfy_models():
    return jsonify({"models": comfy_get_models()})

@app.route("/api/comfy/image-models",    methods=["GET"])
def api_comfy_image_models():
    model_type = request.args.get("type", "anima")
    return jsonify({"models": comfy_get_models_by_type(model_type), "type": model_type})

@app.route("/api/comfy/all-checkpoints", methods=["GET"])
def api_comfy_all_checkpoints():
    try:
        checkpoints, unets = [], []
        r = requests.get(f"{COMFY_URL}/object_info/CheckpointLoaderSimple", timeout=5)
        if r.ok:
            checkpoints = r.json().get("CheckpointLoaderSimple",{}).get("input",{}).get("required",{}).get("ckpt_name",[None])[0] or []
        r2 = requests.get(f"{COMFY_URL}/object_info/UNETLoader", timeout=5)
        if r2.ok:
            unets = r2.json().get("UNETLoader",{}).get("input",{}).get("required",{}).get("unet_name",[None])[0] or []
        return jsonify({"checkpoints": checkpoints, "unets": unets})
    except Exception as e:
        return jsonify({"checkpoints": [], "unets": [], "error": str(e)})

@app.route("/api/comfy/all-loras",       methods=["GET"])
def api_comfy_all_loras():
    try:
        r = requests.get(f"{COMFY_URL}/object_info/LoraLoader", timeout=5)
        if r.ok:
            loras = r.json().get("LoraLoader",{}).get("input",{}).get("required",{}).get("lora_name",[None])[0] or []
            return jsonify({"loras": loras})
        return jsonify({"loras": []})
    except Exception as e:
        return jsonify({"loras": [], "error": str(e)})


# ─── ROUTES — Workflow-Editor ──────────────────────────────────────────────────

@app.route("/api/workflows", methods=["GET"])
def list_workflows():
    result = []
    for f in sorted(WORKFLOWS_DIR.glob("*.json")):
        try:
            wf = json.loads(f.read_text(encoding="utf-8"))
            result.append({"name": f.name, "display_name": f.stem.replace("_", " "), "node_count": len(wf)})
        except Exception:
            pass
    return jsonify({"workflows": result})

@app.route("/api/workflows/<path:name>", methods=["GET"])
def get_workflow(name):
    if not name.endswith(".json") or "/" in name or "\\" in name:
        return jsonify({"error": "Ungültiger Name"}), 400
    path = WORKFLOWS_DIR / name
    if not path.exists():
        return jsonify({"error": "Nicht gefunden"}), 404
    return jsonify({"workflow": json.loads(path.read_text(encoding="utf-8"))})

@app.route("/api/workflows/prompt-suggest", methods=["POST"])
def workflow_prompt_suggest():
    data    = request.get_json()
    user_msg = data.get("message", "")
    if not user_msg:
        return jsonify({"error": "Keine Eingabe"}), 400
    result = generate_danbooru_prompt(user_msg)
    return jsonify({"prompt": result.get("prompt", ""), "negative_prompt": result.get("negative_prompt", "")})

@app.route("/api/workflows/extract-from-image", methods=["POST"])
def extract_workflow_from_image():
    """Liest ComfyUI Workflow aus PNG-Metadaten (tEXt Chunk)."""
    import struct
    if 'file' not in request.files:
        return jsonify({"error": "Keine Datei"}), 400
    file = request.files['file']
    if not file.filename.lower().endswith('.png'):
        return jsonify({"error": "Nur PNG-Dateien unterstützt"}), 400
    try:
        data = file.read()
        if data[:8] != b'\x89PNG\r\n\x1a\n':
            return jsonify({"error": "Keine gültige PNG-Datei"}), 400
        pos          = 8
        found_prompt = None
        while pos < len(data):
            if pos + 8 > len(data): break
            length     = struct.unpack('>I', data[pos:pos+4])[0]
            chunk_type = data[pos+4:pos+8].decode('ascii', errors='ignore')
            chunk_data = data[pos+8:pos+8+length]
            pos       += 12 + length
            if chunk_type in ('tEXt', 'iTXt'):
                null_pos = chunk_data.find(b'\x00')
                if null_pos == -1: continue
                key = chunk_data[:null_pos].decode('utf-8', errors='ignore')
                val = chunk_data[null_pos+1:]
                if chunk_type == 'iTXt':
                    for _ in range(3):
                        n = val.find(b'\x00')
                        if n == -1: break
                        val = val[n+1:]
                if key == 'workflow':
                    try:
                        return jsonify({"workflow": json.loads(val.decode('utf-8')), "source": "workflow"})
                    except Exception as e:
                        return jsonify({"error": f"Workflow JSON ungültig: {e}"}), 400
                elif key == 'prompt' and found_prompt is None:
                    try:
                        found_prompt = json.loads(val.decode('utf-8'))
                    except:
                        pass
        if found_prompt:
            return jsonify({"workflow": found_prompt, "source": "prompt"})
        return jsonify({"error": "Kein Workflow in diesem Bild gefunden"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/workflows/run", methods=["POST"])
def run_custom_workflow():
    data = request.get_json()
    if not data or "workflow" not in data:
        return jsonify({"error": "Kein Workflow übergeben"}), 400

    def run_generator():
        yield "data: " + json.dumps({"type": "step", "text": "⚙️ Workflow wird gestartet...", "status": "active"}) + "\n\n"
        for event in comfy_generate_stream(data["workflow"]):
            etype = event.get("type")
            if etype == "image_preview":
                yield "data: " + json.dumps({"type": "image_preview", "b64": event["b64"]}) + "\n\n"
            elif etype == "image_progress":
                yield "data: " + json.dumps({"type": "image_progress", "value": event["value"], "max": event["max"], "pct": event["pct"]}) + "\n\n"
            elif etype == "image_final":
                try:
                    ts        = datetime.now().strftime("%Y%m%d_%H%M%S")
                    save_path = EXPORT_IMG_DIR / f"{ts}_{event['filename']}"
                    save_path.write_bytes(event["img_bytes"])
                except Exception as se:
                    print(f"[WorkflowRun] Speichern fehlgeschlagen: {se}")
                yield "data: " + json.dumps({"type": "image_done", "image_b64": event["b64"], "filename": event["filename"]}) + "\n\n"
                return
            elif etype == "error":
                yield "data: " + json.dumps({"type": "step", "text": f"❌ {event.get('text')}", "status": "error"}) + "\n\n"
                yield "data: " + json.dumps({"type": "done"}) + "\n\n"
                return

    return Response(stream_with_context(run_generator()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ─── START ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    _init_active_model()
    print("\n🚀 LM Studio Office Assistant")
    print(f"   Aktives Modell: {state.active_model['name']}")
    print(f"   Browser öffnen: http://localhost:5000")
    print(f"   Dateien gespeichert in: {OUTPUT_DIR}\n")
    app.run(debug=False, host="0.0.0.0", port=5000)