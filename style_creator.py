# ─── STYLE_CREATOR.PY — Creator Endpoints (Blueprint) ────────────────────────

import re
import json
import requests
from flask import Blueprint, request, jsonify, Response, stream_with_context, send_from_directory

from config import CHARACTERS_DIR, STYLES_DIR, THEMES_DIR, WILDCARDS_DIR, SORTS_DIR, LM_STUDIO_URL
import state

creator_bp = Blueprint("creator", __name__)


# ── Personality helper ─────────────────────────────────────────────────────────

def _get_personality_text(flag: str) -> str:
    """Load active personality text if personality_enabled AND the given flag is True.
    flag: 'personality_affects_prompt' | 'personality_affects_critic'
    Returns empty string if disabled or not found.
    """
    try:
        if not getattr(state, 'personality_enabled', True):
            return ""
        if not getattr(state, flag, True):
            return ""
        from config import PERSONALITY_DIR
        p_file = PERSONALITY_DIR / state.active_personality / "personality.txt"
        if p_file.exists():
            return p_file.read_text(encoding="utf-8").strip()
    except Exception as e:
        print(f"[Creator] Personality load error: {e}")
    return ""


# ── Generation Prompts ─────────────────────────────────────────────────────────

TEXT_PROMPTS = {
    "character": """You generate character description files for AI image generation.
Output ONLY a comma-separated list of tags describing the character's physical appearance and equipment.

INCLUDE ONLY:
- Gender, body type, build
- Hair: color, length, texture, style
- Eyes: color, shape, glow effects on the eyes themselves
- Skin tone, skin texture, skin material (e.g. exoskeleton, scales)
- Clothing, armor, outfit details
- Accessories, weapons, held objects
- Body modifications, transformations, creature features
- Facial expression

STRICTLY EXCLUDE (never output these):
- Poses, stances, actions, movement
- Background, environment, location, ground, ledge, fog, terrain
- Lighting conditions, shadows, ambient light, directional light
- Art style, rendering technique, medium, painting style
- Composition, perspective, depth of field, camera angle
- Mood, atmosphere, tension, scene description
- Quality tags (masterpiece, cinematic, matte painting, etc.)

Format: plain comma-separated tags only. No JSON, no explanation, no bullet points.
Example: 1girl, praying mantis hybrid, triangular insect head, serrated chitinous forearms, iridescent green and black exoskeleton, cracked armor plates on thorax, metallic joint reinforcement, glowing crimson compound eyes, mandibles slightly parted, organic-chitinous skin texture""",

    "style": """You generate visual style description files for AI image generation.
The user describes a visual style concept. You output ONLY a comma-separated list of prompt tags describing that style.
Cover: rendering technique, color palette, lighting style, texture, artistic movement or medium, mood, quality descriptors.
Format: plain comma-separated tags, no JSON, no explanation, no bullet points.
Example: watercolor painting, soft wet edges, transparent color washes, paper texture, loose brushwork, pastel tones, luminous light""",

    "theme": """You generate world/theme description files for AI image generation.
The user describes a setting or world concept. You output ONLY a comma-separated list of prompt tags describing that world.
Cover: setting type, era, architecture, environment, atmosphere, key objects/elements, color mood, world-specific details.
Format: plain comma-separated tags, no JSON, no explanation, no bullet points.
Example: cyberpunk city, neon-lit streets, rain-soaked, megacorporation dystopia, holographic signs, night atmosphere""",

    "sort": """You generate sorting instruction files for an AI-powered image categorizer.
The user describes what they want to sort images by. Output ONLY the instruction text — a precise, unambiguous classifier prompt for an LLM.

The instruction must follow this structure:
1. Role sentence: "You are a strict classifier."
2. Task: what to detect in an image prompt or filename
3. Rules: specific, unambiguous conditions (use bullet points)
4. Final line: Output ONLY the folder name — lowercase, underscores only, max 20 chars

Do NOT include preamble, explanation, or meta-commentary. Output the raw instruction text only.

Example:
You are a strict classifier.
Task:
Determine whether the prompt contains an artist tag.
Definition:
- An artist tag is the FIRST tag (before the first comma) and starts with "@"
Rules:
- Look ONLY at the first tag
- If it starts with "@", output the artist name without @
- Otherwise output: no_artist

Output ONLY the folder name (lowercase, underscores, max 20 chars).""",
}

IMAGE_PROMPTS = {
    "character": """Analyze this image and extract ONLY the character's physical appearance and equipment as prompt tags.

INCLUDE ONLY:
- Gender, body type, build
- Hair: color, length, texture, style
- Eyes: color, shape, glow effects on the eyes themselves
- Skin tone, skin texture, skin material (exoskeleton, scales, etc.)
- Clothing, armor, outfit details
- Accessories, weapons, held objects
- Body modifications, transformations, creature features
- Facial expression

STRICTLY EXCLUDE:
- Poses, stances, actions, movement
- Background, environment, location, setting
- Lighting, shadows, atmosphere, fog, mood
- Art style, rendering technique, composition, depth of field
- Quality or production tags

Format: plain comma-separated tags only. No JSON, no explanation.""",

    "style": """Analyze the visual style of this image and extract it as AI image generation prompt tags.
Output ONLY a comma-separated list of prompt tags describing the rendering technique, art style, color palette, lighting, texture, medium, and mood.
Ignore the subject matter — focus purely on HOW it looks, not WHAT it shows.
Format: plain comma-separated tags, no JSON, no explanation, no bullet points.""",

    "theme": """Analyze the setting, world and atmosphere of this image and extract it as AI image generation prompt tags.
Output ONLY a comma-separated list of prompt tags describing the environment, era, architecture, atmosphere, lighting mood, world-specific elements and color palette.
Focus on the world/setting, not the characters or art style.
Format: plain comma-separated tags, no JSON, no explanation, no bullet points.""",
}


def _wildcard_text_prompt(wc_type: str) -> str:
    return f"""You generate wildcard value lists for AI image prompt randomization.
The user describes what kind of values they want. You output ONLY a plain list of values, one per line.
Each value should be 3-8 comma-separated prompt tags — specific, vivid, and directly usable in an image generation prompt.
Do NOT write single words or two-word phrases. Each line must be a descriptive tag cluster.
For 'replace' wildcards: descriptive tag clusters that substitute a concept (e.g. for creatures: full description with features, textures, colors).
For 'prepend' wildcards: style prefix tag clusters that work at the start of a prompt.
This is a '{wc_type}' wildcard. Output 15-25 values, one per line, no numbers, no bullets, no explanation, no empty lines.
Example for 'human insect hybrid' replace wildcard:
human with giant beetle shell, iridescent carapace, compound eyes, chitinous arms
woman with dragonfly wings, multifaceted blue eyes, translucent wing membranes, slender iridescent body
man fused with praying mantis, elongated spiked forearms, triangular insect head, green exoskeleton"""


def _wildcard_image_prompt(wc_type: str) -> str:
    return f"""Analyze this image and generate a wildcard value list based on it for AI image prompt randomization.
Output ONLY a plain list of 15-25 values, one per line. Each value should be 3-8 comma-separated prompt tags.
Generate variations inspired by what you see in the image — similar concepts, related ideas, different versions.
This is a '{wc_type}' wildcard. No numbers, no bullets, no explanation, no empty lines."""


# ── Critic Prompts ─────────────────────────────────────────────────────────────

CRITIC_PROMPTS = {
    "character": """You are a strict quality checker for AI image generation character files.
A character file must contain ONLY physical appearance and equipment tags — nothing else.
Character files do NOT define poses, scenes, or environments. That is intentional and correct.

Analyze the given comma-separated tag list and respond ONLY with this JSON:
{
  "score": 7,
  "issues": ["Missing skin tone or material tag", "Contains lighting tag (rim light) — belongs in style file"],
  "improved": "1girl, athletic build, short silver hair, undercut, sharp blue eyes, pale skin, black tactical bodysuit, reinforced shoulder pads, fingerless gloves, katana at hip, cybernetic left arm, determined expression"
}

FORBIDDEN tags (must be flagged and removed):
- Pose, stance, action, movement (standing, looking, holding, reaching, crouching)
- Background, environment, location (forest, city, room, outdoor, on a cliff)
- Lighting (sunlight, shadow, dramatic lighting, rim light, backlit)
- Art style, rendering (watercolor, oil painting, anime style, 3D render)
- Composition, camera angle (close-up, wide shot, from above, portrait)
- Mood, atmosphere (tense, peaceful, mysterious, eerie)
- Quality tags (masterpiece, best quality, detailed, cinematic)
- Scene visibility or framing (visible from waist up, full body shot, character is visible)

REQUIRED coverage (flag if missing):
- Gender + body type
- Hair (color, length, style)
- Eyes (color, shape)
- Clothing / armor / outfit
- Skin tone or material

NOTE: Do NOT flag issues about the character not having a background or pose — character files are
intentionally appearance-only. The improved output must also be appearance-only tags.

score: 1-10 | issues: 1-4 specific problems | improved: full corrected appearance tag list
Output ONLY the JSON.""",

    "style": """You are a strict quality checker for AI image generation style files.
A style file must describe HOW an image looks — not WHAT it shows.

Analyze the comma-separated tag list and respond ONLY with this JSON:
{
  "score": 6,
  "issues": ["Contains character reference (warrior) — belongs in character file", "Missing lighting style tag"],
  "improved": "oil painting, impasto texture, warm earth tones, directional candlelight, painterly brushwork, chiaroscuro, baroque influence, rich color saturation"
}

FORBIDDEN (must be flagged):
- Subject matter (person, character, animal, object)
- Specific locations or environments
- Actions, poses, expressions
- Narrative or story elements

REQUIRED for a good style file:
- Rendering technique or medium
- Color palette or tone
- Lighting style
- Texture descriptors
- At least one artistic movement or reference

score: 1-10 | issues: 1-4 specific problems | improved: full corrected style tag list
Output ONLY the JSON.""",

    "theme": """You are a strict quality checker for AI image generation theme/world files.
A theme file must describe a world or setting — not characters or art style.

Analyze the comma-separated tag list and respond ONLY with this JSON:
{
  "score": 5,
  "issues": ["Contains art style tag (watercolor) — belongs in style file", "Missing era or architectural detail"],
  "improved": "ancient roman city, marble colonnades, open-air forum, midday mediterranean sun, dusty stone streets, terracotta rooftops, distant aqueduct, bustling market atmosphere, warm golden light"
}

FORBIDDEN (must be flagged):
- Character descriptions (girl, warrior, armor)
- Art style or rendering technique
- Camera angles or composition
- Quality tags

REQUIRED for a good theme file:
- Setting type or era
- Architecture or environmental elements
- Atmosphere or mood of the world
- Color palette of the environment
- At least 2-3 world-specific unique elements

score: 1-10 | issues: 1-4 specific problems | improved: full corrected theme tag list
Output ONLY the JSON.""",

    "wildcard": """You are a strict quality checker for AI image generation wildcard files.
A wildcard file contains one value per line. Each line = one replaceable prompt chunk.

Analyze the wildcard list and respond ONLY with this JSON:
{
  "score": 7,
  "issues": ["Specific issue 1"],
  "improved": "line 1 value\\nline 2 value\\nline 3 value"
}

Rules to check:
- Each line must have 3-8 comma-separated tags (flag single words or too-long lines)
- Values must be specific and vivid — not generic
- No duplicate concepts
- No empty lines
- No numbered lists or bullet points
- All values must serve the same conceptual purpose (same wildcard type)
- Minimum 10 values, ideally 15-25

score: 1-10 | issues: 1-4 specific problems | improved: corrected full list (newline-separated)
Output ONLY the JSON.""",

    "sort": """You are a strict quality checker for AI image sort instruction files.
A sort instruction must be a precise, unambiguous classifier prompt for an LLM.

Analyze the instruction text and respond ONLY with this JSON:
{
  "score": 7,
  "issues": ["Missing explicit output format specification"],
  "improved": "corrected full instruction text"
}

Requirements (flag if missing or weak):
- Clear role sentence at the start ("You are a strict classifier.")
- Explicit task description
- Specific, unambiguous rules with no edge-case ambiguity
- Final line must be: Output ONLY the folder name — lowercase, underscores, max 20 chars
- If categories are finite, they must all be listed
- Output must be a single token/slug — no free-form text

score: 1-10 | issues: 1-4 specific problems | improved: full corrected instruction
Output ONLY the JSON."""
}


# ── Routes ─────────────────────────────────────────────────────────────────────

@creator_bp.route("/creator")
def creator_page():
    return send_from_directory("frontend", "creator.html")


@creator_bp.route("/api/creator/generate", methods=["POST"])
def creator_generate():
    data      = request.get_json()
    mode      = data.get("mode", "character")
    desc      = data.get("description", "").strip()
    image_b64 = data.get("image_b64", "").strip()
    wc_type   = data.get("wildcard_type", "replace")

    if not desc and not image_b64:
        return jsonify({"error": "No input"}), 400

    if mode == "wildcard":
        system_prompt = _wildcard_image_prompt(wc_type) if image_b64 else _wildcard_text_prompt(wc_type)
    elif mode == "sort":
        system_prompt = TEXT_PROMPTS["sort"]
        image_b64 = ""
    else:
        system_prompt = (IMAGE_PROMPTS if image_b64 else TEXT_PROMPTS).get(mode, TEXT_PROMPTS["character"])

    # ── Personality injection for creative generation ──────────────────────────
    if mode in ("character", "style", "theme", "wildcard"):
        personality = _get_personality_text("personality_affects_prompt")
        if personality:
            system_prompt += (
                f"\n\n--- CREATIVE DIRECTION (use this as tonal/stylistic inspiration "
                f"when interpreting ambiguous concepts, not as content to include) ---\n"
                f"{personality}\n--- END CREATIVE DIRECTION ---"
            )

    user_text = desc if desc else "Analyze this image."

    def build_messages():
        if image_b64:
            return [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                    {"type": "text", "text": user_text}
                ]}
            ]
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_text}
        ]

    def generate():
        payload = {
            "model":       state.active_model["name"],
            "messages":    build_messages(),
            "temperature": 0.5,
            "max_tokens":  600,
            "stream":      True
        }
        try:
            resp = requests.post(LM_STUDIO_URL, json=payload, stream=True, timeout=60)
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                line = line.decode("utf-8")
                if line.startswith("data: "):
                    line = line[6:]
                if line == "[DONE]":
                    yield "data: " + json.dumps({"type": "done"}) + "\n\n"
                    break
                try:
                    chunk = json.loads(line)
                    delta = chunk["choices"][0].get("delta", {})
                    if delta.get("content"):
                        yield "data: " + json.dumps({"type": "token", "text": delta["content"]}) + "\n\n"
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
        except Exception as e:
            yield "data: " + json.dumps({"type": "error", "text": str(e)}) + "\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@creator_bp.route("/api/creator/critique", methods=["POST"])
def creator_critique():
    data    = request.get_json()
    mode    = data.get("mode", "character")
    content = data.get("content", "").strip()
    if not content:
        return jsonify({"error": "No content"}), 400

    system_prompt = CRITIC_PROMPTS.get(mode)
    if not system_prompt:
        return jsonify({"error": "Unknown mode"}), 400

    # ── Personality tone injection for critic ──────────────────────────────────
    personality = _get_personality_text("personality_affects_critic")
    if personality:
        system_prompt += f"\n\nDeliver your feedback in this personality and tone:\n{personality}"

    try:
        resp = requests.post(LM_STUDIO_URL, json={
            "model":       state.active_model["name"],
            "messages":    [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": content}
            ],
            "temperature": 0.1,
            "max_tokens":  800,
            "stream":      False
        }, timeout=60)
        resp.raise_for_status()
        import re as _re
        text   = resp.json()["choices"][0]["message"].get("content", "")
        text   = _re.sub(r'<think>.*?</think>', '', text, flags=_re.DOTALL).strip()
        try:
            result = json.loads(text)
        except Exception:
            start, end = text.find('{'), text.rfind('}')
            result = json.loads(text[start:end+1]) if start != -1 else {}
        print(f"[Critic] Mode={mode} Score={result.get('score')}/10 Issues={len(result.get('issues', []))}")
        return jsonify(result)
    except Exception as e:
        print(f"[Critic] Error: {e}")
        return jsonify({"error": str(e)}), 500


_USER_AVATAR_TEMPLATE = (
    "masterpiece, best quality, score_7, minimalist app icon, "
    "{subject}, "
    "dark elegant background, #0f0f17, soft vignette, clean design, "
    "vector art, flat illustration, digital art, modern aesthetic, "
    "no clutter, isolated on black, high contrast, stylized, anime style, "
    "cute character, friendly expression, tech theme, minimalist icon design"
)


@creator_bp.route("/api/creator/user-avatar-prompt", methods=["POST"])
def user_avatar_prompt():
    subject = (request.get_json() or {}).get("subject", "").strip()
    if not subject:
        return jsonify({"error": "No subject"}), 400
    prompt = _USER_AVATAR_TEMPLATE.format(subject=subject)
    return jsonify({"prompt": prompt})


@creator_bp.route("/api/creator/save-user-avatar", methods=["POST"])
def save_user_avatar():
    import base64
    from pathlib import Path
    img_b64 = (request.get_json() or {}).get("image_b64", "").strip()
    if not img_b64:
        return jsonify({"error": "No image"}), 400
    dest = Path("frontend/assets/user.png")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(base64.b64decode(img_b64))
    print("[Creator] User avatar saved → frontend/assets/user.png")
    return jsonify({"ok": True})


@creator_bp.route("/api/creator/save", methods=["POST"])
def creator_save():
    data    = request.get_json()
    mode    = data.get("mode", "character")
    name    = data.get("name", "").strip()
    content = data.get("content", "").strip()
    wc_type = data.get("wildcard_type", "replace")

    if not name or not content:
        return jsonify({"error": "Name and content required"}), 400

    safe_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', name).strip('_')
    if not safe_name:
        return jsonify({"error": "Invalid filename"}), 400

    folder_map = {
        "character": CHARACTERS_DIR,
        "style":     STYLES_DIR,
        "theme":     THEMES_DIR,
        "wildcard":  WILDCARDS_DIR / wc_type,
        "sort":      SORTS_DIR,
    }
    folder = folder_map.get(mode)
    if not folder:
        return jsonify({"error": "Invalid mode"}), 400

    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{safe_name}.txt"
    path.write_text(content, encoding="utf-8")
    print(f"[Creator] Saved {mode}: {path}")
    return jsonify({"ok": True, "filename": f"{safe_name}.txt", "path": str(path)})