# ─── ROUTES/WORKFLOWS.PY — Workflow-Editor, PNG-Helpers, Prompt Critic ────────

import re
import json
import copy
import struct
import base64
from datetime import datetime
from flask import Blueprint, request, jsonify, Response, stream_with_context

from config import WORKFLOWS_DIR, EXPORT_IMG_DIR, REFERENCE_DIR, LM_STUDIO_URL
from comfy_backend import comfy_generate_stream, comfy_upload_image
from llm import (parse_json_response, resolve_all_wildcards, resolve_replace_wildcards,
                 strip_prepend_wildcards, apply_prepend_values,
                 read_prompt_skills, read_style_content, read_theme_content, read_character_content,
                 critique_prompt)
import state

workflows_bp = Blueprint("workflows", __name__)

_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}

_SLUG_STOP = {
    'masterpiece','best','quality','score','worst','low','high','blurry','jpeg',
    'artifacts','the','and','with','for','from','that','this','very','also',
    'rating','safe','nsfw','sfw','bad','good','great','amazing','beautiful',
    '1girl','1boy','2girls','2boys','1other','multiple','girls','boys','solo',
}


def prompt_to_slug(workflow: dict, max_words: int = 5) -> str:
    for node in workflow.values():
        if not isinstance(node, dict): continue
        if node.get("class_type") not in ("KSampler", "KSamplerAdvanced"): continue
        pos_id   = node["inputs"].get("positive")
        if isinstance(pos_id, list) and len(pos_id) == 2:
            pos_node = workflow.get(str(pos_id[0]), {})
            if pos_node.get("class_type") == "CLIPTextEncode":
                positive_text = pos_node.get("inputs", {}).get("text", "")
                tags  = [t.strip().lower() for t in positive_text.replace(",", " ").split()]
                words = []
                for t in tags:
                    t_clean = re.sub(r'[^a-z0-9]', '', t)
                    if t_clean and t_clean not in _SLUG_STOP and not t_clean.isdigit() and len(t_clean) > 2:
                        words.append(t_clean)
                    if len(words) >= max_words:
                        break
                return "_".join(words)
    return ""


# ─── PNG Helpers ──────────────────────────────────────────────────────────────

def _read_png_text_chunks(png_bytes: bytes) -> dict:
    """Liest alle tEXt/iTXt-Chunks aus einer PNG-Datei. Gibt {key: parsed_json} zurück."""
    if png_bytes[:8] != b'\x89PNG\r\n\x1a\n':
        return {}
    chunks = {}
    pos    = 8
    while pos < len(png_bytes):
        if pos + 8 > len(png_bytes): break
        length     = struct.unpack('>I', png_bytes[pos:pos+4])[0]
        chunk_type = png_bytes[pos+4:pos+8].decode('ascii', errors='ignore')
        chunk_data = png_bytes[pos+8:pos+8+length]
        pos       += 12 + length
        if chunk_type not in ('tEXt', 'iTXt'):
            continue
        null_pos = chunk_data.find(b'\x00')
        if null_pos == -1: continue
        key = chunk_data[:null_pos].decode('utf-8', errors='ignore')
        val = chunk_data[null_pos+1:]
        if chunk_type == 'iTXt':
            for _ in range(3):
                n = val.find(b'\x00')
                if n == -1: break
                val = val[n+1:]
        try:
            chunks[key] = json.loads(val.decode('utf-8'))
        except Exception:
            pass
    return chunks


def extract_workflow_from_bytes(png_bytes: bytes) -> dict | None:
    chunks = _read_png_text_chunks(png_bytes)
    return chunks.get('workflow') or chunks.get('prompt')


def extract_api_prompt_from_bytes(png_bytes: bytes) -> dict | None:
    chunks = _read_png_text_chunks(png_bytes)
    return chunks.get('prompt') or chunks.get('workflow')


def extract_positive_prompt_from_png(png_bytes: bytes) -> str:
    wf = extract_api_prompt_from_bytes(png_bytes)
    if not wf or not isinstance(wf, dict):
        return ""
    if any(isinstance(v, list) for v in wf.values()):
        return ""
    for node in wf.values():
        if not isinstance(node, dict): continue
        if node.get('class_type') not in ('KSampler', 'KSamplerAdvanced'): continue
        pos_ref  = node.get('inputs', {}).get('positive')
        if not isinstance(pos_ref, list) or not pos_ref: continue
        pos_node = wf.get(str(pos_ref[0]), {})
        if pos_node.get('class_type') == 'CLIPTextEncode':
            return pos_node.get('inputs', {}).get('text', '')[:500]
    return ""


def apply_img2img_patch(wf: dict, comfy_filename: str, denoise: float) -> dict:
    wf = copy.deepcopy(wf)

    vae_ref = None
    for node_id, node in wf.items():
        if node.get("class_type") == "VAEDecode":
            vae_ref = node["inputs"].get("vae")
            break
    if vae_ref is None:
        for node_id, node in wf.items():
            if node.get("class_type") == "CheckpointLoaderSimple":
                vae_ref = [node_id, 2]
                break

    if vae_ref is None:
        print("[Img2Img] Kein VAE gefunden — Patch übersprungen")
        return wf

    latent_node_ids = set()
    for node_id, node in wf.items():
        if node.get("class_type") in ("KSampler", "KSamplerAdvanced"):
            latent_input = node["inputs"].get("latent_image")
            if isinstance(latent_input, list) and len(latent_input) == 2:
                ref_id = str(latent_input[0])
                if wf.get(ref_id, {}).get("class_type") == "EmptyLatentImage":
                    latent_node_ids.add(ref_id)
            node["inputs"]["denoise"] = denoise

    for lat_id in latent_node_ids:
        load_id = f"i2i_load_{lat_id}"
        enc_id  = f"i2i_enc_{lat_id}"
        wf[load_id] = {
            "class_type": "LoadImage",
            "inputs":     {"image": comfy_filename, "upload": "image"},
            "_meta":      {"title": "Img2Img Input"}
        }
        wf[enc_id] = {
            "class_type": "VAEEncode",
            "inputs":     {"pixels": [load_id, 0], "vae": vae_ref},
            "_meta":      {"title": "Img2Img VAEEncode"}
        }
        for node_id, node in wf.items():
            if node.get("class_type") in ("KSampler", "KSamplerAdvanced"):
                if isinstance(node["inputs"].get("latent_image"), list) and str(node["inputs"]["latent_image"][0]) == lat_id:
                    node["inputs"]["latent_image"] = [enc_id, 0]
        del wf[lat_id]
        print(f"[Img2Img] Node {lat_id} → LoadImage({comfy_filename}) + VAEEncode, denoise={denoise}")

    if not latent_node_ids:
        for node_id, node in wf.items():
            if node.get("class_type") not in ("KSampler", "KSamplerAdvanced"): continue
            latent_input = node["inputs"].get("latent_image")
            if not isinstance(latent_input, list): continue
            enc_id   = str(latent_input[0])
            enc_node = wf.get(enc_id, {})
            if enc_node.get("class_type") != "VAEEncode": continue
            pixels = enc_node["inputs"].get("pixels")
            if not isinstance(pixels, list): continue
            load_id   = str(pixels[0])
            load_node = wf.get(load_id, {})
            if load_node.get("class_type") == "LoadImage":
                load_node["inputs"]["image"] = comfy_filename
                node["inputs"]["denoise"]    = denoise
                print(f"[Img2Img] Existing LoadImage {load_id} → {comfy_filename}, denoise={denoise}")

    return wf


# ─── Routes ───────────────────────────────────────────────────────────────────

@workflows_bp.route("/api/workflows", methods=["GET"])
def list_workflows():
    result = []
    for f in sorted(WORKFLOWS_DIR.glob("*.json")):
        try:
            wf = json.loads(f.read_text(encoding="utf-8"))
            result.append({"name": f.name, "display_name": f.stem.replace("_", " "), "node_count": len(wf)})
        except Exception:
            pass
    return jsonify({"workflows": result})


@workflows_bp.route("/api/workflows/save", methods=["POST"])
def save_workflow():
    data     = request.get_json()
    name     = data.get("name", "").strip()
    workflow = data.get("workflow")
    if not name or not workflow:
        return jsonify({"ok": False, "error": "Name and workflow required"}), 400
    safe_name = re.sub(r'[<>:"/\\|?*]', '_', name)
    if not safe_name.endswith(".json"):
        safe_name += ".json"
    path = WORKFLOWS_DIR / safe_name
    try:
        path.write_text(json.dumps(workflow, indent=2), encoding="utf-8")
        print(f"[Workflow] Saved: {safe_name}")
        return jsonify({"ok": True, "filename": safe_name})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@workflows_bp.route("/api/workflows/prompt-suggest", methods=["POST"])
def workflow_prompt_suggest():
    from prompts import PROMPT_STYLES
    data      = request.get_json()
    user_msg  = data.get("message", "").strip()
    image_b64 = data.get("image_b64", "").strip()

    if not user_msg and not image_b64:
        return jsonify({"error": "No input"}), 400

    style_prompt   = PROMPT_STYLES.get(state.prompt_style, PROMPT_STYLES["danbooru"])
    prepend_values = []

    if user_msg:
        clean_msg = resolve_replace_wildcards(user_msg)
        clean_msg, prepend_values = strip_prepend_wildcards(clean_msg)
    else:
        clean_msg = "Generate a prompt based on this image."

    skills = read_prompt_skills(state.prompt_style)
    if skills:
        style_prompt += f"\n\n--- REFERENCE MATERIAL ---\n{skills}\n--- END REFERENCE ---"

    for label, getter, key in [
        ("CHARACTER (use this as the primary subject)", read_character_content, "character"),
        ("VISUAL STYLE (incorporate into prompt)",      read_style_content,     "style"),
        ("THEME (incorporate into prompt)",             read_theme_content,     "theme"),
    ]:
        name    = data.get(key) or None
        content = getter(name) if name else ""
        if content:
            style_prompt += f"\n\n--- {label} ---\n{content}\n--- END {key.upper()} ---"
            print(f"[WorkflowPrompt] {key} injected: {name}")

    # Personality-Constraints injizieren
    if getattr(state, 'personality_enabled', True) and getattr(state, 'personality_affects_prompt', True):
        try:
            from config import PERSONALITY_DIR
            p_file = PERSONALITY_DIR / state.active_personality / "personality.txt"
            if p_file.exists():
                personality = p_file.read_text(encoding="utf-8").strip()
                if personality:
                    style_prompt += (
                            "\n\n--- PERSONALITY CONSTRAINTS ---\n"
                            + personality
                            + "\nThese constraints MUST be reflected in the generated prompt. "
                              "If the personality restricts subject matter, those restrictions apply here too.\n"
                              "--- END PERSONALITY CONSTRAINTS ---"
                    )
        except Exception:
            pass

    def build_user_content():
        if image_b64:
            return [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                {"type": "text", "text": clean_msg}
            ]
        return clean_msg

    def generate():
        import re as _re
        full_text = ""
        try:
            resp = state  # just a placeholder for linting
            import requests as _req
            resp = _req.post(LM_STUDIO_URL, json={
                "model":       state.active_model["name"],
                "messages":    [
                    {"role": "system", "content": style_prompt},
                    {"role": "user",   "content": build_user_content()}
                ],
                "temperature": 0.4,
                "max_tokens":  800,
                "stream":      True
            }, stream=True, timeout=60)
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line: continue
                line = line.decode("utf-8")
                if line.startswith("data: "): line = line[6:]
                if line == "[DONE]": break
                try:
                    chunk = json.loads(line)
                    delta = chunk["choices"][0].get("delta", {})
                    if delta.get("content"):
                        full_text += delta["content"]
                        yield "data: " + json.dumps({"type": "token", "text": delta["content"]}) + "\n\n"
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue

            clean    = _re.sub(r'<think>.*?</think>', '', full_text, flags=_re.DOTALL).strip()
            parsed   = parse_json_response(clean)
            final_p  = apply_prepend_values(parsed.get("prompt", ""), prepend_values)
            yield "data: " + json.dumps({
                "type":            "done",
                "prompt":          final_p,
                "negative_prompt": parsed.get("negative_prompt", "")
            }) + "\n\n"
        except Exception as e:
            yield "data: " + json.dumps({"type": "error", "text": str(e)}) + "\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream", headers=_SSE_HEADERS)


@workflows_bp.route("/api/workflows/extract-from-image", methods=["POST"])
def extract_workflow_from_image():
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    file = request.files['file']
    if not file.filename.lower().endswith('.png'):
        return jsonify({"error": "Only PNG files supported"}), 400
    try:
        wf = extract_workflow_from_bytes(file.read())
        if wf is not None:
            return jsonify({"workflow": wf, "source": "workflow"})
        return jsonify({"error": "No workflow found in this image"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@workflows_bp.route("/api/workflows/critique-prompt", methods=["POST"])
def api_critique_prompt():
    data   = request.get_json()
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "no prompt"}), 400
    result = critique_prompt(prompt)
    return jsonify(result)


@workflows_bp.route("/api/workflows/<path:name>", methods=["GET"])
def get_workflow(name):
    if not name.endswith(".json") or "/" in name or "\\" in name:
        return jsonify({"error": "Invalid name"}), 400
    path = WORKFLOWS_DIR / name
    if not path.exists():
        return jsonify({"error": "Not found"}), 404
    return jsonify({"workflow": json.loads(path.read_text(encoding="utf-8"))})


@workflows_bp.route("/api/workflows/run", methods=["POST"])
def run_custom_workflow():
    data = request.get_json()
    if not data or "workflow" not in data:
        return jsonify({"error": "No workflow provided"}), 400

    def run_generator():
        wf = data["workflow"]
        for node_id, node in wf.items():
            if isinstance(node, dict) and node.get("class_type") in ("CLIPTextEncode", "CLIPTextEncodeSDXL"):
                inputs = node.get("inputs", {})
                if isinstance(inputs.get("text"), str):
                    inputs["text"] = resolve_all_wildcards(inputs["text"])

        img2img = data.get("img2img")
        if img2img and img2img.get("image_b64"):
            try:
                yield "data: " + json.dumps({"type": "step", "text": "📤 Uploading image to ComfyUI...", "status": "active"}) + "\n\n"
                comfy_filename = comfy_upload_image(img2img["image_b64"])
                denoise        = float(img2img.get("denoise", 0.75))
                wf             = apply_img2img_patch(wf, comfy_filename, denoise)
                print(f"[WorkflowRun] Img2Img active — file={comfy_filename}, denoise={denoise}")
            except Exception as e:
                yield "data: " + json.dumps({"type": "step", "text": f"❌ Img2Img Upload fehlgeschlagen: {e}", "status": "error"}) + "\n\n"
                yield "data: " + json.dumps({"type": "done"}) + "\n\n"
                return

        yield "data: " + json.dumps({"type": "step", "text": "⚙️ Starting workflow...", "status": "active"}) + "\n\n"
        for event in comfy_generate_stream(wf):
            etype = event.get("type")
            if etype == "image_preview":
                yield "data: " + json.dumps({"type": "image_preview", "b64": event["b64"]}) + "\n\n"
            elif etype == "image_progress":
                yield "data: " + json.dumps({"type": "image_progress", "value": event["value"], "max": event["max"], "pct": event["pct"]}) + "\n\n"
            elif etype == "image_final":
                try:
                    ts        = datetime.now().strftime("%Y%m%d_%H%M%S")
                    slug      = prompt_to_slug(wf)
                    name      = f"{ts}_{slug}.png" if slug else f"{ts}_{event['filename']}"
                    artist_mode = data.get("artist_mode")
                    if artist_mode and artist_mode.get("artist_name"):
                        model_type  = re.sub(r'[^a-zA-Z0-9_]', '', artist_mode.get("model_type", "illustrious"))
                        artist_name = artist_mode["artist_name"].strip().strip("/\\")
                        if ".." not in artist_name:
                            artist_dir = REFERENCE_DIR / model_type / artist_name
                            artist_dir.mkdir(parents=True, exist_ok=True)
                            safe = re.sub(r'[^a-zA-Z0-9_\-@]', '_', artist_name)
                            save_path = artist_dir / f"{ts}_{safe}.png"
                        else:
                            save_path = EXPORT_IMG_DIR / name
                    else:
                        save_path = EXPORT_IMG_DIR / name
                    save_path.write_bytes(event["img_bytes"])
                except Exception as se:
                    print(f"[WorkflowRun] Save failed: {se}")
                yield "data: " + json.dumps({"type": "image_done", "image_b64": event["b64"], "filename": save_path.name}) + "\n\n"

                refiner = data.get("refiner")
                if refiner and refiner.get("workflow"):
                    yield from _run_refiner(refiner, wf, event, slug)
                return
            elif etype == "error":
                yield "data: " + json.dumps({"type": "step", "text": f"❌ {event.get('text')}", "status": "error"}) + "\n\n"
                yield "data: " + json.dumps({"type": "done"}) + "\n\n"
                return

    return Response(stream_with_context(run_generator()), mimetype="text/event-stream", headers=_SSE_HEADERS)


def _run_refiner(refiner: dict, main_wf: dict, main_event: dict, slug: str):
    """Generator: führt den Refiner-Workflow aus und yieldet SSE-Events."""
    try:
        yield "data: " + json.dumps({"type": "step", "text": "✨ Refiner läuft...", "status": "active"}) + "\n\n"

        rf_name = refiner["workflow"]
        if not rf_name.endswith(".json") or "/" in rf_name or "\\" in rf_name:
            raise ValueError("Invalid refiner workflow name")
        rf_path = WORKFLOWS_DIR / rf_name
        if not rf_path.exists():
            raise FileNotFoundError(f"Refiner workflow not found: {rf_name}")
        rf_wf = json.loads(rf_path.read_text(encoding="utf-8"))

        # Prompts aus Haupt-Workflow extrahieren
        main_positive = main_negative = ""
        for node_id, node in main_wf.items():
            if node.get("class_type") not in ("KSampler", "KSamplerAdvanced"): continue
            pos_id = str(node["inputs"].get("positive", [None])[0])
            neg_id = str(node["inputs"].get("negative", [None])[0])
            if main_wf.get(pos_id, {}).get("class_type") == "CLIPTextEncode":
                main_positive = main_wf[pos_id]["inputs"].get("text", "")
            if main_wf.get(neg_id, {}).get("class_type") == "CLIPTextEncode":
                main_negative = main_wf[neg_id]["inputs"].get("text", "")
            break

        # Prompts in Refiner injizieren
        if main_positive or main_negative:
            for rf_node_id, rf_node in rf_wf.items():
                if rf_node.get("class_type") not in ("KSampler", "KSamplerAdvanced"): continue
                rf_pos_id = str(rf_node["inputs"].get("positive", [None])[0])
                rf_neg_id = str(rf_node["inputs"].get("negative", [None])[0])
                if main_positive and rf_wf.get(rf_pos_id, {}).get("class_type") == "CLIPTextEncode":
                    rf_wf[rf_pos_id]["inputs"]["text"] = main_positive
                if main_negative and rf_wf.get(rf_neg_id, {}).get("class_type") == "CLIPTextEncode":
                    rf_wf[rf_neg_id]["inputs"]["text"] = main_negative
                break
            for rf_node in rf_wf.values():
                if rf_node.get("class_type") == "FaceDetailer" and main_positive:
                    fd_pos_id = str(rf_node["inputs"].get("positive", [None])[0])
                    if rf_wf.get(fd_pos_id, {}).get("class_type") == "CLIPTextEncode":
                        rf_wf[fd_pos_id]["inputs"]["text"] = main_positive

        rf_b64      = base64.b64encode(main_event["img_bytes"]).decode("utf-8")
        rf_comfy_fn = comfy_upload_image(rf_b64)
        rf_denoise  = float(refiner.get("denoise", 0.5))
        rf_wf       = apply_img2img_patch(rf_wf, rf_comfy_fn, rf_denoise)

        rf_model = refiner.get("model")
        if rf_model:
            for node in rf_wf.values():
                if isinstance(node, dict):
                    ct = node.get("class_type", "")
                    if ct == "CheckpointLoaderSimple":
                        node["inputs"]["ckpt_name"] = rf_model; break
                    elif ct == "UNETLoader":
                        node["inputs"]["unet_name"] = rf_model; break

        for node in rf_wf.values():
            if isinstance(node, dict) and node.get("class_type") in ("CLIPTextEncode", "CLIPTextEncodeSDXL"):
                if isinstance(node.get("inputs", {}).get("text"), str):
                    node["inputs"]["text"] = resolve_all_wildcards(node["inputs"]["text"])

        rf_name_out = ""
        for rf_event in comfy_generate_stream(rf_wf):
            rf_etype = rf_event.get("type")
            if rf_etype == "image_preview":
                yield "data: " + json.dumps({"type": "image_preview", "b64": rf_event["b64"]}) + "\n\n"
            elif rf_etype == "image_progress":
                yield "data: " + json.dumps({"type": "image_progress", "value": rf_event["value"], "max": rf_event["max"], "pct": rf_event["pct"]}) + "\n\n"
            elif rf_etype == "image_final":
                try:
                    rf_ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
                    rf_slug     = prompt_to_slug(rf_wf) or slug
                    rf_name_out = f"{rf_ts}_{rf_slug}_refined.png"
                    rf_save     = EXPORT_IMG_DIR / rf_name_out
                    rf_save.write_bytes(rf_event["img_bytes"])
                    print(f"[Refiner] Saved: {rf_save}")
                except Exception as rse:
                    print(f"[Refiner] Save failed: {rse}")
                yield "data: " + json.dumps({"type": "refiner_done", "image_b64": rf_event["b64"], "filename": rf_name_out}) + "\n\n"
                break
            elif rf_etype == "error":
                yield "data: " + json.dumps({"type": "step", "text": f"⚠️ Refiner: {rf_event.get('text')}", "status": "error"}) + "\n\n"
                break
    except Exception as e:
        yield "data: " + json.dumps({"type": "step", "text": f"⚠️ Refiner fehlgeschlagen: {e}", "status": "error"}) + "\n\n"