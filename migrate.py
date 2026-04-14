"""
migrate.py — Verschiebt bestehende Daten in die neue data/ Struktur.
Einmalig ausführen: python migrate.py
"""

import shutil
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"

MOVES = [
    (ROOT / "exportImg",   DATA / "exportImg"),
    (ROOT / "knowledge",   DATA / "knowledge"),
    (ROOT / "skills",      DATA / "skills"),
    (ROOT / "wildcards",   DATA / "wildcards"),
    (ROOT / "workflows",   DATA / "workflows"),
    (ROOT / "styles",      DATA / "styles"),
    (ROOT / "themes",      DATA / "themes"),
    (ROOT / "characters",  DATA / "characters"),
    (ROOT / "chats.db",    DATA / "chats.db"),
]

DATA.mkdir(exist_ok=True)

for src, dst in MOVES:
    if not src.exists():
        print(f"  skip  {src.name} (nicht vorhanden)")
        continue
    if dst.exists():
        print(f"  skip  {src.name} → Ziel existiert bereits")
        continue
    shutil.move(str(src), str(dst))
    print(f"  moved {src.name} → data/{dst.name}")

print("\n✅ Migration abgeschlossen.")
print("   Starte danach: python server.py")
