from __future__ import annotations

import ntpath
import os
import re

_WINDOWS_DRIVE_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")


def is_windows_absolute_path(path: str) -> bool:
    
    normalized = str(path or "").strip()
    return bool(_WINDOWS_DRIVE_ABSOLUTE_RE.match(normalized)) or normalized.startswith(("\\\\", "//"))


def normalize_filesystem_path(path: str) -> str:
    
    raw_path = str(path or "").strip()
    expanded = os.path.expanduser(raw_path) if raw_path.startswith("~") else raw_path
    if is_windows_absolute_path(expanded):
        return ntpath.normpath(expanded)
    return os.path.abspath(expanded)


__all__ = ["is_windows_absolute_path", "normalize_filesystem_path"]
