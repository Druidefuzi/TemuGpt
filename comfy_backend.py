# ─── COMFY_BACKEND.PY — ComfyUI Kommunikation ────────────────────────────────

import struct
import random
import base64
import json
import requests
from config import COMFY_URL


def comfy_get_models_by_type(model_type: str) -> list:
    """Holt verfügbare Modelle von ComfyUI gefiltert nach Typ."""
    try:
        t = model_type.lower()
        if t == "anima":
            resp = requests.get(f"{COMFY_URL}/object_info/UNETLoader", timeout=5)
            resp.raise_for_status()
            all_models = resp.json().get("UNETLoader", {}).get("input", {}).get("required", {}).get("unet_name", [None])[0] or []
            return [m for m in all_models if "anima" in m.lower()]

        elif t == "zimage":
            resp = requests.get(f"{COMFY_URL}/object_info/UNETLoader", timeout=5)
            resp.raise_for_status()
            all_models = resp.json().get("UNETLoader", {}).get("input", {}).get("required", {}).get("unet_name", [None])[0] or []
            print(f"[ComfyUI] Z-Image UNETs ({len(all_models)}): {all_models[:5]}")
            return [m for m in all_models if "zimage" in m.lower()]

        elif t == "illustrious":
            resp = requests.get(f"{COMFY_URL}/object_info/CheckpointLoaderSimple", timeout=5)
            resp.raise_for_status()
            all_models = resp.json().get("CheckpointLoaderSimple", {}).get("input", {}).get("required", {}).get("ckpt_name", [None])[0] or []
            print(f"[ComfyUI] Alle Checkpoints ({len(all_models)}): {all_models[:5]}")
            return all_models

    except Exception as e:
        print(f"[ComfyUI] Modelle abrufen fehlgeschlagen ({model_type}): {e}")
    return []


def comfy_get_models() -> list:
    """Legacy-Alias."""
    return comfy_get_models_by_type("anima")


def comfy_upload_image(image_b64: str) -> str:
    """Lädt ein Base64-Bild in ComfyUI hoch. Gibt den zugewiesenen Dateinamen zurück."""
    import io
    from PIL import Image as PILImage

    image_data = base64.b64decode(image_b64)
    img = PILImage.open(io.BytesIO(image_data)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    resp = requests.post(
        f"{COMFY_URL}/upload/image",
        files={"image": ("i2i_input.png", buf, "image/png")},
        data={"overwrite": "true"},
        timeout=15
    )
    resp.raise_for_status()
    result = resp.json()
    name = result.get("name", "i2i_input.png")
    subfolder = result.get("subfolder", "")
    return f"{subfolder}/{name}" if subfolder else name


def comfy_generate_stream(workflow: dict, model_type: str = "anima"):
    """Generator: Sendet Workflow an ComfyUI, streamt Previews + Progress via WebSocket.
    Yieldet dicts: image_preview | image_progress | image_final | error
    """
    try:
        import websocket
    except ImportError:
        yield {"type": "error", "text": "websocket-client nicht installiert: pip install websocket-client"}
        return

    client_id = f"office-{random.randint(10000, 99999)}"

    try:
        resp = requests.post(f"{COMFY_URL}/prompt",
                             json={"prompt": workflow, "client_id": client_id}, timeout=10)
        resp.raise_for_status()
        prompt_id = resp.json()["prompt_id"]
        print(f"[ComfyUI] Job gestartet: {prompt_id} (type={model_type}, client={client_id})")
    except Exception as e:
        yield {"type": "error", "text": f"ComfyUI nicht erreichbar: {e}"}
        return

    ws_url = f"ws://127.0.0.1:8188/ws?clientId={client_id}"
    try:
        ws = websocket.create_connection(ws_url, timeout=300)
        print("[ComfyUI] WebSocket verbunden")
    except Exception as e:
        yield {"type": "error", "text": f"WebSocket fehlgeschlagen: {e}"}
        return

    try:
        while True:
            msg = ws.recv()

            # Binär = Preview-JPEG
            if isinstance(msg, bytes) and len(msg) > 8:
                event_type = struct.unpack_from(">I", msg, 0)[0]
                if event_type == 1:  # PREVIEW_IMAGE
                    yield {"type": "image_preview", "b64": base64.b64encode(msg[8:]).decode("utf-8")}
                continue

            try:
                data = json.loads(msg)
            except Exception:
                continue

            msg_type = data.get("type", "")

            if msg_type == "progress":
                val     = data["data"].get("value", 0)
                max_val = data["data"].get("max", 1)
                pct     = int(val / max_val * 100) if max_val else 0
                yield {"type": "image_progress", "value": val, "max": max_val, "pct": pct}

            elif msg_type == "execution_success":
                if data["data"].get("prompt_id") == prompt_id:
                    print(f"[ComfyUI] Fertig: {prompt_id}")
                    try:
                        hist    = requests.get(f"{COMFY_URL}/history/{prompt_id}", timeout=10).json()
                        outputs = hist.get(prompt_id, {}).get("outputs", {})
                        for node_out in outputs.values():
                            for img_info in node_out.get("images", []):
                                img_resp = requests.get(f"{COMFY_URL}/view", params={
                                    "filename":  img_info["filename"],
                                    "type":      img_info.get("type", "output"),
                                    "subfolder": img_info.get("subfolder", "")
                                }, timeout=15)
                                img_resp.raise_for_status()
                                img_bytes = img_resp.content
                                yield {
                                    "type":      "image_final",
                                    "b64":       base64.b64encode(img_bytes).decode("utf-8"),
                                    "filename":  img_info["filename"],
                                    "img_bytes": img_bytes
                                }
                                return
                    except Exception as e:
                        yield {"type": "error", "text": f"Finales Bild laden fehlgeschlagen: {e}"}
                        return

            elif msg_type == "execution_error":
                if data["data"].get("prompt_id") == prompt_id:
                    yield {"type": "error", "text": data["data"].get("exception_message", "ComfyUI Fehler")}
                    return

    except Exception as e:
        yield {"type": "error", "text": f"WebSocket Fehler: {e}"}
    finally:
        try:
            ws.close()
        except Exception:
            pass