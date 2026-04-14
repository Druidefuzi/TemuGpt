# ─── ROUTES/CHAT.PY — Chat, SmartChat, StreamThink ───────────────────────────

import json
import re
import requests
from urllib.parse import urlparse
from flask import Blueprint, request, jsonify, Response, stream_with_context

from config import LM_STUDIO_URL
from database import write_knowledge
from documents import save_document
from search import search_searxng, fetch_page, format_search_results
from llm import (parse_json_response, enforce_action, call_llm, build_messages,
                 think, _detect_intent, generate_danbooru_prompt, stream_generator,
                 resolve_all_wildcards)
from comfy_backend import comfy_get_models_by_type, comfy_generate_stream
from workflows import build_workflow
import state

chat_bp = Blueprint("chat", __name__)

_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


# ─── Blocking chat (file uploads) ─────────────────────────────────────────────

@chat_bp.route("/chat", methods=["POST"])
def chat():
    message  = request.form.get("message", "")
    history  = json.loads(request.form.get("history", "[]"))
    files    = request.files.getlist("files")
    messages = build_messages(message=message, history=history, files=files)

    thinking = None
    if state.thinking_enabled and message and len(message) > 15:
        thinking = think(message, history)

    try:
        llm_text, llm_reasoning = call_llm(messages)
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "LM Studio not reachable. Is the server running?"}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    parsed = parse_json_response(llm_text)

    if parsed.get("action") == "write_knowledge":
        filename     = parsed.get("filename", "notes.txt")
        file_content = parsed.get("content", "")
        msg          = parsed.get("message", f"{filename} updated.")

        if not file_content and parsed.get("inhalt"):
            file_content = _inhalt_to_text(parsed["inhalt"])

        if not file_content:
            chat_msg = parsed.get("message", "")
            reply    = chat_msg if chat_msg else "❌ No content to save."
            return jsonify({"action": "chat", "message": reply, "thinking": thinking, "reasoning": llm_reasoning})

        ok = write_knowledge(filename, file_content)
        return jsonify({
            "action":    "chat",
            "message":   f"{'✅' if ok else '❌'} **{filename}** {'saved' if ok else 'save failed'} — {msg}",
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
            "content": f"Here are the search results:\n\n{search_text}\n\nPlease answer the original question based on these results. Reply in the user's language using the chat JSON format."
        })
        try:
            llm_text2, _ = call_llm(messages)
            parsed = parse_json_response(llm_text2)
            if parsed.get("action") == "chat":
                parsed["message"] = f"🔍 *Searched: {query}*\n\n" + parsed.get("message", "")
        except Exception as e:
            return jsonify({"action": "chat", "message": f"Search ok but response error: {e}"}), 500

    if parsed.get("action") == "create_document":
        try:
            path, filename = save_document(parsed)
            return jsonify({
                "action":       "create_document",
                "message":      f"✅ **{parsed.get('titel', filename)}** created!",
                "filename":     filename,
                "download_url": f"/download/{filename}",
                "thinking":     thinking,
                "reasoning":    llm_reasoning
            })
        except Exception as e:
            return jsonify({"action": "chat", "message": f"Creation error: {e}"}), 500

    return jsonify({
        "action":    "chat",
        "message":   parsed.get("message", llm_text),
        "thinking":  thinking,
        "reasoning": llm_reasoning
    })


# ─── Smart streaming chat ──────────────────────────────────────────────────────

@chat_bp.route("/smart_chat", methods=["POST"])
def smart_chat():
    data                 = request.json
    message              = data.get("message", "")
    history              = data.get("history", [])
    temperature          = float(data.get("temperature", 0.3))
    context_length       = int(data.get("context_length", 8192))
    forced_action        = data.get("forced_action", "auto")
    research_max_results = int(data.get("research_max_results", 8))
    research_min_pages   = int(data.get("research_min_pages", 5))

    messages = build_messages(message=message, history=history, action="detect_intent")
    intent   = _detect_intent(messages, forced_action=forced_action)
    action   = intent.get("action", "chat")
    messages = build_messages(message=message, history=history, action=action)

    # ── Dokument ─────────────────────────────────────────────────────────────
    if action == "create_document":
        def doc_generator():
            yield "data: " + json.dumps({"type": "step", "text": "📋 Generating document...", "status": "active"}) + "\n\n"
            try:
                llm_text, _ = call_llm(messages, temperature=temperature, max_tokens=4096, context_length=context_length)
                doc_data     = enforce_action(parse_json_response(llm_text), "create_document")
                if not doc_data.get("inhalt") and not doc_data.get("tabellen"):
                    yield "data: " + json.dumps({"type": "step", "text": "❌ LLM did not generate a document", "status": "error"}) + "\n\n"
                    yield "data: " + json.dumps({"type": "done"}) + "\n\n"
                    return
                yield "data: " + json.dumps({"type": "step", "text": "💾 Saving file...", "status": "active"}) + "\n\n"
                path, filename = save_document(doc_data)
                yield "data: " + json.dumps({
                    "type":         "document_done",
                    "message":      f"✅ **{doc_data.get('titel', filename)}** created!",
                    "filename":     filename,
                    "download_url": f"/download/{filename}"
                }) + "\n\n"
            except Exception as e:
                yield "data: " + json.dumps({"type": "step", "text": f"❌ Error: {e}", "status": "error"}) + "\n\n"
                yield "data: " + json.dumps({"type": "done"}) + "\n\n"

        return Response(stream_with_context(doc_generator()), mimetype="text/event-stream", headers=_SSE_HEADERS)

    # ── Suche ─────────────────────────────────────────────────────────────────
    if action == "search":
        def search_generator():
            query = intent.get("query", message)
            yield "data: " + json.dumps({"type": "step", "text": f"🔍 Searching: {query}", "status": "active"}) + "\n\n"
            try:
                results = search_searxng(query, max_results=research_max_results)
            except Exception as e:
                yield "data: " + json.dumps({"type": "step", "text": f"❌ Search failed: {e}", "status": "error"}) + "\n\n"
                yield "data: " + json.dumps({"type": "search_done", "query": query, "message": "Search failed."}) + "\n\n"
                return

            yield "data: " + json.dumps({"type": "step", "text": f"✅ {len(results)} results found", "status": "done"}) + "\n\n"

            if state.research_enabled and results:
                yield "data: " + json.dumps({"type": "step", "text": "📄 Reading pages...", "status": "active"}) + "\n\n"
                successful = 0
                for r in results:
                    if successful >= research_min_pages: break
                    if r["url"]:
                        content = fetch_page(r["url"], query=query)
                        if content:
                            r["full_content"] = content
                            successful += 1
                            try:
                                host = urlparse(r["url"]).netloc.replace("www.", "")
                            except Exception:
                                host = r["url"][:40]
                            yield "data: " + json.dumps({"type": "source", "title": r["title"][:50], "host": host, "url": r["url"]}) + "\n\n"
                yield "data: " + json.dumps({"type": "step", "text": f"📄 {successful} pages read", "status": "done"}) + "\n\n"

            yield "data: " + json.dumps({"type": "step", "text": "🧠 Analyzing results...", "status": "active"}) + "\n\n"
            search_text = format_search_results(query, results)
            msgs = messages.copy()
            msgs.append({"role": "assistant", "content": json.dumps(intent)})
            msgs.append({"role": "user", "content": f"Here are the search results with page contents:\n\n{search_text}\n\nPlease answer the original question in detail based on these results. Reply in the user's language using the chat JSON format."})

            yield "data: " + json.dumps({"type": "search_stream_start", "query": query}) + "\n\n"

            payload = {
                "model": state.active_model["name"],
                "messages": msgs,
                "temperature": temperature,
                "max_tokens": 4096,
                "stream": True
            }
            if context_length:
                payload["context_length"] = context_length

            full_text = ""
            try:
                resp = requests.post(LM_STUDIO_URL, json=payload, stream=True, timeout=300)
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line: continue
                    line = line.decode("utf-8")
                    if line.startswith("data: "): line = line[6:]
                    if line == "[DONE]": break
                    try:
                        chunk = json.loads(line)
                        delta = chunk["choices"][0].get("delta", {})
                        if delta.get("reasoning_content"):
                            yield "data: " + json.dumps({"type": "reasoning", "text": delta["reasoning_content"]}) + "\n\n"
                        if delta.get("content"):
                            full_text += delta["content"]
                            yield "data: " + json.dumps({"type": "content", "text": delta["content"]}) + "\n\n"
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
                parsed = parse_json_response(full_text)
                reply  = parsed.get("message", full_text)
                yield "data: " + json.dumps({"type": "search_done", "query": query, "message": reply}) + "\n\n"
            except requests.exceptions.ConnectionError:
                yield "data: " + json.dumps({"type": "search_done", "query": query, "message": "❌ LM Studio not reachable!"}) + "\n\n"
            except Exception as e:
                yield "data: " + json.dumps({"type": "search_done", "query": query, "message": f"Search ok but response error: {e}"}) + "\n\n"

        return Response(stream_with_context(search_generator()), mimetype="text/event-stream", headers=_SSE_HEADERS)

    # ── Knowledge schreiben ───────────────────────────────────────────────────
    if action == "write_knowledge":
        try:
            llm_text, _ = call_llm(messages, temperature=temperature, max_tokens=4096, context_length=context_length)
            wk_data      = enforce_action(parse_json_response(llm_text), "write_knowledge")
            filename     = wk_data.get("filename", "notes.txt")
            file_content = wk_data.get("content", "")
            msg          = wk_data.get("message", f"{filename} updated.")

            if not file_content and wk_data.get("inhalt"):
                print("[Knowledge] Fallback: 'inhalt' → Plain Text")
                file_content = _inhalt_to_text(wk_data["inhalt"])

            if not file_content:
                chat_msg = wk_data.get("message", "")
                if chat_msg:
                    return jsonify({"mode": "chat", "message": chat_msg})
                return jsonify({"mode": "chat", "message": "❌ No content to save."})

            ok = write_knowledge(filename, file_content)
            return jsonify({"mode": "chat", "message": f"{'✅' if ok else '❌'} **{filename}** {'saved' if ok else 'save failed'} — {msg}"})
        except Exception as e:
            return jsonify({"mode": "chat", "message": f"Error: {e}"})

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
            from config import EXPORT_IMG_DIR as _EXPORT
            if img_raw_prompt:
                final_prompt   = resolve_all_wildcards(img_prompt)
                final_negative = negative_prompt
                final_ratio    = aspect_ratio
                yield "data: " + json.dumps({"type": "step", "text": f"✏️ Raw: {final_prompt[:80]}{'…' if len(final_prompt) > 80 else ''}", "status": "done"}) + "\n\n"
            else:
                yield "data: " + json.dumps({"type": "step", "text": "🏷️ Generating prompt...", "status": "active"}) + "\n\n"
                danbooru       = generate_danbooru_prompt(message)
                final_prompt   = danbooru.get("prompt", img_prompt)
                final_negative = danbooru.get("negative_prompt", negative_prompt)
                final_ratio    = danbooru.get("aspect_ratio", aspect_ratio)
                yield "data: " + json.dumps({"type": "step", "text": f"✏️ {final_prompt[:80]}{'…' if len(final_prompt) > 80 else ''}", "status": "done"}) + "\n\n"

            model_name = img_model_name or (comfy_get_models_by_type(img_model_type) or [""])[0]
            short_name = model_name.split("\\")[-1].split("/")[-1]
            turbo_tag  = " ⚡Turbo" if img_turbo else ""
            type_label = {"anima": "🌸 Anima", "illustrious": "🎨 Illustrious", "zimage": "⚡ Z-Image"}.get(img_model_type, img_model_type) + turbo_tag
            yield "data: " + json.dumps({"type": "step", "text": f"{type_label} · {short_name}", "status": "done"}) + "\n\n"
            yield "data: " + json.dumps({"type": "step", "text": "🖼️ Generating image...", "status": "active"}) + "\n\n"

            try:
                if img_model_type == "anima":
                    final_negative = ""
                workflow = build_workflow(img_model_type, final_prompt, final_negative, final_ratio, model_name, turbo=img_turbo)
            except Exception as we:
                yield "data: " + json.dumps({"type": "step", "text": f"❌ Workflow error: {we}", "status": "error"}) + "\n\n"
                yield "data: " + json.dumps({"type": "done"}) + "\n\n"
                return

            # Slug via LLM
            img_slug = ""
            try:
                actual_prompt = ""
                for node in workflow.values():
                    if isinstance(node, dict) and node.get("class_type") in ("KSampler", "KSamplerAdvanced"):
                        pos_id = node["inputs"].get("positive")
                        if isinstance(pos_id, list):
                            pos_node = workflow.get(str(pos_id[0]), {})
                            if pos_node.get("class_type") == "CLIPTextEncode":
                                actual_prompt = pos_node.get("inputs", {}).get("text", "")[:300]
                                break
                slug_resp = requests.post(LM_STUDIO_URL, json={
                    "model":       state.active_model["name"],
                    "messages":    [
                        {"role": "system", "content": "You generate short image filenames. Output ONLY 3-5 lowercase English words separated by underscores, no extension, no punctuation, no explanation."},
                        {"role": "user",   "content": f"Prompt: {actual_prompt}"}
                    ],
                    "temperature": 0.2,
                    "max_tokens":  20,
                    "stream":      False
                }, timeout=10)
                raw      = slug_resp.json()["choices"][0]["message"].get("content", "").strip()
                raw      = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
                img_slug = re.sub(r'[^a-z0-9_]', '', raw.lower().replace(" ", "_").replace("-", "_"))[:60]
            except Exception:
                pass

            try:
                instance_id = state.active_model["name"]
                unload_resp = requests.post(f"http://localhost:1234/api/v1/models/unload", json={"instance_id": instance_id}, timeout=10)
                if unload_resp.ok:
                    yield "data: " + json.dumps({"type": "step", "text": "🧹 LLM unloaded (VRAM free)", "status": "done"}) + "\n\n"
            except Exception:
                pass

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
                        name      = f"{ts}_{img_slug}.png" if img_slug else f"{ts}_{event['filename']}"
                        save_path = _EXPORT / name
                        save_path.write_bytes(event["img_bytes"])
                    except Exception as se:
                        print(f"[Image] Save failed: {se}")
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

        return Response(stream_with_context(img_generator()), mimetype="text/event-stream", headers=_SSE_HEADERS)

    # ── Normaler Chat Stream ──────────────────────────────────────────────────
    return Response(
        stream_with_context(stream_generator(messages, temperature=temperature, context_length=context_length)),
        mimetype="text/event-stream",
        headers=_SSE_HEADERS
    )


# ─── Stream Think ─────────────────────────────────────────────────────────────

@chat_bp.route("/stream-think", methods=["POST"])
def stream_think():
    data    = request.json
    message = data.get("message", "")

    if not state.thinking_enabled or not message or len(message) <= 15:
        return Response("data: " + '{"type": "skip"}' + "\n\n", mimetype="text/event-stream")

    from prompts import THINKING_PROMPT

    think_messages = [
        {"role": "system", "content": THINKING_PROMPT},
        {"role": "user",   "content": f"Analyze this request: {message}"}
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

    return Response(stream_with_context(generate()), mimetype="text/event-stream", headers=_SSE_HEADERS)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _inhalt_to_text(inhalt: list) -> str:
    """Konvertiert LLM-Document-Format (inhalt) zu Plain Text."""
    lines = []
    for block in inhalt:
        typ = block.get("typ", "")
        if typ in ("ueberschrift1", "ueberschrift2", "ueberschrift3"):
            prefix = "#" * (1 + int(typ[-1]) - 1) if typ[-1].isdigit() else "#"
            lines.append(f"{prefix} {block.get('text', '')}")
        elif typ == "aufzaehlung":
            for punkt in block.get("punkte", []):
                lines.append(f"- {punkt}")
        elif typ == "absatz":
            lines.append(block.get("text", ""))
        else:
            lines.append(block.get("text", str(block)))
        lines.append("")
    return "\n".join(lines).strip()
