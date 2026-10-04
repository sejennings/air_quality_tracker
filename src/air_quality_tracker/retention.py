"""Expire operational files only; historical data and models are outside this tree."""
from pathlib import Path
import time


def cleanup(root: Path, days: int = 30, now: float | None = None) -> int:
    if days < 1 or days > 30:
        raise ValueError("Retention must be between 1 and 30 days")
    if root.is_symlink() or any(p.is_symlink() for p in root.parents):
        raise ValueError("Operational root must not traverse symlinks")
    cutoff = (time.time() if now is None else now) - days * 86400
    removed = 0
    if not root.exists():
        return removed
    # Never traverse symlinks. Only these explicit operational namespaces expire.
    for category in ("scores", "logs", "collected"):
        folder = root / category
        if folder.is_symlink():
            raise ValueError(f"Operational directory is a symlink: {folder}")
        if not folder.exists():
            continue
        for path in folder.rglob("*"):
            if path.is_symlink() or any(p.is_symlink() for p in path.parents):
                continue
            if path.is_file() and path.stat().st_mtime <= cutoff:
                path.unlink()
                removed += 1
    return removed

