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
        """)
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
