"""每日 SQLite 在线备份，保留最新 7 份。用 sqlite 的 backup API，运行中备份也是一致快照。"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

KEEP = 7
PREFIX = "tgrank-"


def make_backup(db_path: Path, backup_dir: Path, now: datetime, keep: int = KEEP) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    dst = backup_dir / f"{PREFIX}{now:%Y%m%d-%H%M%S}.db"
    tmp = dst.with_suffix(".db.part")
    src = sqlite3.connect(db_path)
    out = sqlite3.connect(tmp)
    try:
        src.backup(out)
    finally:
        out.close()
        src.close()
    tmp.replace(dst)  # 先写临时文件再改名，中途失败不会留下半截备份

    # 只清理自己生成的文件，用户手动放进来的不动
    ours = sorted(backup_dir.glob(f"{PREFIX}*.db"))
    for old in ours[:-keep]:
        old.unlink()
    return dst
