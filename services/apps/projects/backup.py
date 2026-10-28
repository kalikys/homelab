"""Online SQLite backup into /data/backups, keeps the newest 14. Run: docker exec projects python /app/backup.py"""
import sqlite3
from datetime import datetime
from pathlib import Path

SRC = Path("/data/projects.db")
DST = Path("/data/backups")
DST.mkdir(exist_ok=True)
target = DST / f"projects-{datetime.now():%Y%m%d-%H%M}.db"
with sqlite3.connect(SRC) as src, sqlite3.connect(target) as dst:
    src.backup(dst)
for old in sorted(DST.glob("projects-*.db"))[:-14]:
    old.unlink()
print(target)
