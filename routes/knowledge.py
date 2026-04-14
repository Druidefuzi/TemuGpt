# ─── ROUTES/KNOWLEDGE.PY — Knowledge-Dateien & Prompt Skills ─────────────────

from datetime import datetime
from flask import Blueprint, request

from config import KNOWLEDGE_DIR, SKILLS_DIR

knowledge_bp = Blueprint("knowledge", __name__)


@knowledge_bp.route("/api/knowledge", methods=["GET"])
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
    return {"files": files, "dir": str(KNOWLEDGE_DIR)}


@knowledge_bp.route("/api/knowledge/<filename>", methods=["GET"])
def get_knowledge_file(filename):
    path = KNOWLEDGE_DIR / filename
    if path.exists():
        return path.read_text(encoding="utf-8"), 200, {"Content-Type": "text/plain; charset=utf-8"}
    return "Not found", 404


@knowledge_bp.route("/api/skills", methods=["GET"])
def list_skills():
    allowed = {".txt", ".md", ".html", ".json"}
    result  = {}
    for folder in ("shared", "danbooru", "mixed", "natural"):
        skill_dir = SKILLS_DIR / folder
        files     = []
        if skill_dir.exists():
            for f in sorted(skill_dir.iterdir()):
                if f.is_file() and f.suffix.lower() in allowed:
                    files.append({
                        "name":     f.name,
                        "size":     f.stat().st_size,
                        "modified": datetime.fromtimestamp(f.stat().st_mtime).strftime("%d.%m %H:%M")
                    })
        result[folder] = files
    return {"skills": result, "dir": str(SKILLS_DIR)}


@knowledge_bp.route("/api/skills/<style>/<filename>", methods=["GET"])
def get_skill_file(style, filename):
    if style not in ("shared", "danbooru", "mixed", "natural"):
        return "Invalid style", 400
    path = SKILLS_DIR / style / filename
    if path.exists():
        return path.read_text(encoding="utf-8"), 200, {"Content-Type": "text/plain; charset=utf-8"}
    return "Not found", 404
