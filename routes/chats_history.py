# ─── ROUTES/CHATS_HISTORY.PY — Chat History API ───────────────────────────────

from datetime import datetime
from flask import Blueprint, request, jsonify
from database import get_db

chats_history_bp = Blueprint("chats_history", __name__)


@chats_history_bp.route("/api/chats", methods=["GET"])
def list_chats():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, title, model, created, updated FROM chats ORDER BY updated DESC"
        ).fetchall()
    return jsonify({"chats": [dict(r) for r in rows]})


@chats_history_bp.route("/api/chats", methods=["POST"])
def create_chat():
    data  = request.get_json() or {}
    title = data.get("title", "Neuer Chat").strip() or "Neuer Chat"
    model = data.get("model", "")
    now   = datetime.utcnow().isoformat()
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO chats (title, model, created, updated) VALUES (?, ?, ?, ?)",
            (title, model, now, now)
        )
        chat_id = cur.lastrowid
        row = conn.execute("SELECT * FROM chats WHERE id = ?", (chat_id,)).fetchone()
    return jsonify(dict(row)), 201


@chats_history_bp.route("/api/chats/<int:chat_id>", methods=["GET"])
def get_chat(chat_id):
    with get_db() as conn:
        chat = conn.execute("SELECT * FROM chats WHERE id = ?", (chat_id,)).fetchone()
        if not chat:
            return jsonify({"error": "Not found"}), 404
        messages = conn.execute(
            "SELECT * FROM messages WHERE chat_id = ? ORDER BY id", (chat_id,)
        ).fetchall()
    return jsonify({"chat": dict(chat), "messages": [dict(m) for m in messages]})


@chats_history_bp.route("/api/chats/<int:chat_id>", methods=["PATCH"])
def rename_chat(chat_id):
    data  = request.get_json() or {}
    title = data.get("title", "").strip()
    if not title:
        return jsonify({"error": "Title required"}), 400
    now = datetime.utcnow().isoformat()
    with get_db() as conn:
        conn.execute(
            "UPDATE chats SET title = ?, updated = ? WHERE id = ?", (title, now, chat_id)
        )
    return jsonify({"ok": True})


@chats_history_bp.route("/api/chats/<int:chat_id>", methods=["DELETE"])
def delete_chat(chat_id):
    with get_db() as conn:
        conn.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
    return jsonify({"ok": True})


@chats_history_bp.route("/api/chats/<int:chat_id>/messages", methods=["POST"])
def add_message(chat_id):
    data = request.get_json() or {}
    now  = datetime.utcnow().isoformat()
    msgs = data.get("messages")
    if msgs:
        # Array format: { messages: [{role, content}, ...] }
        with get_db() as conn:
            for m in msgs:
                conn.execute(
                    "INSERT INTO messages (chat_id, role, content, created) VALUES (?, ?, ?, ?)",
                    (chat_id, m.get("role", "user"), m.get("content", ""), now)
                )
            conn.execute("UPDATE chats SET updated = ? WHERE id = ?", (now, chat_id))
        return jsonify({"ok": True}), 201
    # Single format: { role, content }
    role    = data.get("role", "user")
    content = data.get("content", "")
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO messages (chat_id, role, content, created) VALUES (?, ?, ?, ?)",
            (chat_id, role, content, now)
        )
        conn.execute("UPDATE chats SET updated = ? WHERE id = ?", (now, chat_id))
    return jsonify({"ok": True, "id": cur.lastrowid}), 201


@chats_history_bp.route("/api/chats/<int:chat_id>/generate-title", methods=["POST"])
def generate_title(chat_id):
    import requests as _req
    import state
    from config import LM_STUDIO_URL
    with get_db() as conn:
        messages = conn.execute(
            "SELECT role, content FROM messages WHERE chat_id = ? ORDER BY id LIMIT 4",
            (chat_id,)
        ).fetchall()
    if not messages:
        return jsonify({"error": "No messages"}), 400
    context = "\n".join(f"{m['role']}: {m['content'][:200]}" for m in messages)
    try:
        resp = _req.post(LM_STUDIO_URL, json={
            "model":       state.active_model["name"],
            "messages":    [
                {"role": "system",  "content": "Generate a short chat title (max 5 words, no quotes) based on the conversation. Output only the title."},
                {"role": "user",    "content": context}
            ],
            "temperature": 0.3,
            "max_tokens":  20,
            "stream":      False
        }, timeout=15)
        title = resp.json()["choices"][0]["message"]["content"].strip().strip('"\'')
        now   = datetime.utcnow().isoformat()
        with get_db() as conn:
            conn.execute("UPDATE chats SET title = ?, updated = ? WHERE id = ?", (title, now, chat_id))
        return jsonify({"ok": True, "title": title})
    except Exception as e:
        return jsonify({"error": str(e)}), 500