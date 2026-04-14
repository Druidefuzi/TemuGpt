# ─── ROUTES/MUSIC.PY — Song Generator (ACE-Step + LM Studio) ─────────────────

import re
import json
import requests
from flask import Blueprint, request, jsonify, Response, stream_with_context, send_from_directory

from config import LM_STUDIO_URL
import state

music_bp = Blueprint("music", __name__)

ACE_STEP_URL = "http://localhost:8001"

_MUSIC_SYSTEM = """You are a music prompt generator for ACE-Step, an AI music generation model.
The user describes a song. Output ONLY a JSON object — no explanation, no text before or after.

Output format:
{
  "caption": "comma-separated style tags: genre, instruments, mood, tempo, vocal style",
  "lyrics": "[Verse 1]\\nline 1\\nline 2\\n\\n[Chorus]\\nline 1\\nline 2\\n\\n[Verse 2]\\nline 1\\nline 2\\n\\n[Chorus]\\nline 1\\nline 2\\n\\n[Bridge]\\nline 1\\nline 2\\n\\n[Chorus]\\nline 1\\nline 2"
}

Caption rules:
- 5-15 comma-separated tags
- Cover: genre, key instruments, mood/energy, tempo descriptor, vocal style
- Example: "indie pop, electric guitar, piano, upbeat, energetic, female vocals, catchy hooks, bright synths"

Lyrics rules:
- Use section markers: [Verse 1], [Chorus], [Bridge], [Outro] etc.
- Each line on its own line
- Sections separated by empty lines
- Match the mood and genre described
- If user says instrumental, return empty string "" for lyrics

Output ONLY the JSON, nothing else."""


@music_bp.route("/music")
def music_page():
    return send_from_directory("frontend", "music.html")


@music_bp.route("/api/music/generate-prompt", methods=["POST"])
def generate_music_prompt():
    """LM Studio generates caption + lyrics from user description. Streaming SSE."""
    data = request.get_json() or {}
    desc = data.get("description", "").strip()
    if not desc:
        return jsonify({"error": "No description"}), 400

    def stream():
        # Inject personality into system prompt if enabled
        system = _MUSIC_SYSTEM
        if getattr(state, 'personality_affects_music', True) and getattr(state, 'personality_enabled', True):
            try:
                from config import PERSONALITY_DIR
                p_file = PERSONALITY_DIR / state.active_personality / "personality.txt"
                if p_file.exists():
                    personality = p_file.read_text(encoding="utf-8").strip()
                    if personality:
                        system += f"\n\nPersonality context (use this to shape the mood, tone and lyrical style of the song):\n{personality}"
            except Exception:
                pass
        try:
            resp = requests.post(LM_STUDIO_URL, json={
                "model":       state.active_model["name"],
                "messages":    [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": desc}
                ],
                "temperature": 0.7,
                "max_tokens":  800,
                "stream":      True
            }, stream=True, timeout=60)
            resp.raise_for_status()
            full = ""
            for line in resp.iter_lines():
                if not line:
                    continue
                line = line.decode("utf-8")
                if line.startswith("data: "):
                    line = line[6:]
                if line == "[DONE]":
                    # Parse and send final result
                    clean = re.sub(r"<think>.*?</think>", "", full, flags=re.DOTALL).strip()
                    try:
                        parsed = json.loads(clean)
                    except Exception:
                        s, e = clean.find("{"), clean.rfind("}")
                        parsed = json.loads(clean[s:e+1]) if s != -1 else {}
                    yield "data: " + json.dumps({"type": "done", "caption": parsed.get("caption", ""), "lyrics": parsed.get("lyrics", "")}) + "\n\n"
                    break
                try:
                    chunk = json.loads(line)
                    delta = chunk["choices"][0].get("delta", {})
                    if delta.get("content"):
                        full += delta["content"]
                        yield "data: " + json.dumps({"type": "token", "text": delta["content"]}) + "\n\n"
                except Exception:
                    continue
        except Exception as e:
            yield "data: " + json.dumps({"type": "error", "text": str(e)}) + "\n\n"

    return Response(stream_with_context(stream()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@music_bp.route("/api/music/reference-audio", methods=["POST"])
def generate_reference_audio():
    """Generate a short reference audio clip via Kokoro using the active personality voice."""
    try:
        # Get TTS settings
        tts_url   = getattr(state, 'tts_url', 'http://localhost:8880')
        tts_voice = getattr(state, 'tts_voice', 'af_bella')

        # Try personality-specific voice first
        try:
            from config import PERSONALITY_DIR
            tts_file = PERSONALITY_DIR / state.active_personality / "tts_voice.txt"
            if tts_file.exists():
                v = tts_file.read_text(encoding="utf-8").strip()
                if v:
                    tts_voice = v
        except Exception:
            pass

        # Generate a short neutral sentence for reference
        sample_text = "A gentle melody flows through the air, carrying a sense of warmth and calm."

        resp = requests.post(
            f"{tts_url}/v1/audio/speech",
            json={"model": "kokoro", "voice": tts_voice, "input": sample_text, "response_format": "mp3"},
            timeout=30
        )
        resp.raise_for_status()

        import base64
        audio_b64 = base64.b64encode(resp.content).decode("utf-8")
        print(f"[Music] Reference audio generated: voice={tts_voice} ({len(resp.content)} bytes)")
        return jsonify({"ok": True, "audio_b64": audio_b64, "voice": tts_voice})
    except Exception as e:
        print(f"[Music] Reference audio error: {e}")
        return jsonify({"error": str(e)}), 500


@music_bp.route("/api/music/create", methods=["POST"])
def create_music_task():
    """Submit generation task to ACE-Step. Returns task_id."""
    data          = request.get_json() or {}
    caption       = data.get("caption", "").strip()
    lyrics        = data.get("lyrics", "").strip()
    duration      = int(data.get("duration", 120))
    seed          = int(data.get("seed", -1))
    ref_audio_b64 = data.get("reference_audio_b64", "").strip()

    if not caption:
        return jsonify({"error": "No caption"}), 400

    try:
        if ref_audio_b64:
            import base64
            import io
            audio_bytes = base64.b64decode(ref_audio_b64)
            files = {"reference_audio": ("reference.mp3", io.BytesIO(audio_bytes), "audio/mpeg")}
            data  = {
                "caption":  caption,
                "lyrics":   lyrics,
                "duration": str(duration),
                "seed":     str(seed),
            }
            resp = requests.post(f"{ACE_STEP_URL}/release_task", data=data, files=files, timeout=15)
        else:
            resp = requests.post(f"{ACE_STEP_URL}/release_task", json={
                "caption":  caption,
                "lyrics":   lyrics,
                "duration": duration,
                "seed":     seed,
            }, timeout=15)
        resp.raise_for_status()
        d = resp.json()
        task_id = d.get("data", {}).get("task_id") or d.get("task_id")
        if not task_id:
            return jsonify({"error": "No task_id in response", "raw": d}), 500
        print(f"[Music] Task created: {task_id} | caption: {caption[:60]}")
        return jsonify({"ok": True, "task_id": task_id})
    except Exception as e:
        print(f"[Music] Create task error: {e}")
        return jsonify({"error": str(e)}), 500


@music_bp.route("/api/music/status", methods=["POST"])
def music_status():
    """Poll ACE-Step for task result."""
    data    = request.get_json() or {}
    task_id = data.get("task_id", "").strip()
    if not task_id:
        return jsonify({"error": "No task_id"}), 400

    try:
        resp = requests.post(f"{ACE_STEP_URL}/query_result",
                             json={"task_id_list": [task_id]}, timeout=10)
        resp.raise_for_status()
        d = resp.json()

        # data is a list of task objects
        result_data = d.get("data", [])
        task_data   = {}
        if isinstance(result_data, list) and result_data:
            task_data = result_data[0]
        elif isinstance(result_data, dict):
            task_data = result_data.get(task_id, {})

        # status: 0=pending, 1=completed, 2=failed
        status_code = task_data.get("status", 0)
        error       = task_data.get("error")

        if status_code == 2:
            return jsonify({"status": "failed", "error": error or "Generation failed"})
        if status_code != 1:
            return jsonify({"status": "pending"})

        # Parse result JSON string to get audio path
        result_str = task_data.get("result", "")
        audio_url  = None
        if result_str:
            try:
                result_list = json.loads(result_str)
                if isinstance(result_list, list) and result_list:
                    audio_url = result_list[0].get("file", "")
                elif isinstance(result_list, dict):
                    audio_url = result_list.get("file", "")
            except Exception:
                pass

        if not audio_url:
            return jsonify({"status": "failed", "error": "No audio path in result"})

        # Proxy the audio download from ACE-Step
        audio_resp = requests.get(f"{ACE_STEP_URL}{audio_url}", timeout=30)
        audio_resp.raise_for_status()

        import base64
        audio_b64 = base64.b64encode(audio_resp.content).decode("utf-8")
        # Detect format from URL or content-type
        fmt = "wav"
        if ".mp3" in audio_url or "mp3" in audio_resp.headers.get("content-type", ""):
            fmt = "mp3"

        print(f"[Music] Audio downloaded: {len(audio_resp.content)} bytes ({fmt})")
        return jsonify({"status": "completed", "audio_b64": audio_b64, "format": fmt})

    except Exception as e:
        return jsonify({"error": str(e)}), 500