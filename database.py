# ─── DATABASE.PY — SQLite + Knowledge-Dateien ─────────────────────────────────

import sqlite3
from pathlib import Path
from config import DB_PATH, KNOWLEDGE_DIR


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.executescript("""
                           CREATE TABLE IF NOT EXISTS chats (
                                                                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                                                                title   TEXT    NOT NULL DEFAULT 'Neuer Chat',
                                                                model   TEXT,
                                                                created TEXT    NOT NULL,
                                                                updated TEXT    NOT NULL
                           );
                           CREATE TABLE IF NOT EXISTS messages (
                                                                   id      INTEGER PRIMARY KEY AUTOINCREMENT,
                                                                   chat_id INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
                               role    TEXT    NOT NULL,
                               content TEXT    NOT NULL,
                               created TEXT    NOT NULL
                               );
                           CREATE TABLE IF NOT EXISTS config_settings (
                                                                          key           TEXT PRIMARY KEY,
                                                                          value         TEXT NOT NULL,
                                                                          default_value TEXT NOT NULL,
                                                                          label         TEXT NOT NULL,
                                                                          category      TEXT NOT NULL,
                                                                          description   TEXT DEFAULT ''
                           );
                           """)
        # Insert defaults if not yet present
        _defaults = [
            ("LM_STUDIO_URL", "http://localhost:1234/v1/chat/completions", "http://localhost:1234/v1/chat/completions", "Completions URL",  "LLM",     "Chat-Completions Endpoint"),
            ("LM_API",        "http://localhost:1234",                     "http://localhost:1234",                     "API Base URL",     "LLM",     "Basis-URL für Modell-Management"),
            ("COMFY_URL",     "http://127.0.0.1:8188",                     "http://127.0.0.1:8188",                     "ComfyUI URL",      "ComfyUI", "ComfyUI Server URL"),
            ("MODEL_DEFAULT", "huihui-qwen3-vl-4b-instruct-abliterated",   "huihui-qwen3-vl-4b-instruct-abliterated",   "Default Model",    "LLM",     "Fallback-Modell wenn keins geladen ist"),
        ]
        conn.executemany("""
                         INSERT OR IGNORE INTO config_settings (key, value, default_value, label, category, description)
            VALUES (?, ?, ?, ?, ?, ?)
                         """, _defaults)
    print("[DB] Datenbank initialisiert")


def read_knowledge() -> str:
    files_content = []
    allowed = {".html", ".css", ".js", ".txt", ".md", ".json"}
    for f in sorted(KNOWLEDGE_DIR.iterdir()):
        if f.is_file() and f.suffix.lower() in allowed:
            try:
                text = f.read_text(encoding="utf-8")
                files_content.append(f"### {f.name}\n```\n{text}\n```")
            except:
                pass
    if not files_content:
        return ""
    return "\n\n".join(files_content)


def write_knowledge(filename: str, content_text: str) -> bool:
    allowed = {".html", ".css", ".js", ".txt", ".md", ".json"}
    path = KNOWLEDGE_DIR / Path(filename).name
    if path.suffix.lower() not in allowed:
        return False
    path.write_text(content_text, encoding="utf-8")
    return True


def get_all_config_settings() -> list:
    with get_db() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM config_settings ORDER BY category, key"
        ).fetchall()]


def get_config_setting(key: str) -> str | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT value FROM config_settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None


def set_config_setting(key: str, value: str) -> bool:
    with get_db() as conn:
        r = conn.execute(
            "UPDATE config_settings SET value = ? WHERE key = ?", (value, key)
        )
        return r.rowcount > 0


def reset_config_setting(key: str) -> str | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT default_value FROM config_settings WHERE key = ?", (key,)
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE config_settings SET value = default_value WHERE key = ?", (key,)
        )
        return row["default_value"]