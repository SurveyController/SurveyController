from __future__ import annotations

import os
import sys

from software.app.path_utils import normalize_filesystem_path


def _get_repo_root() -> str:
    return os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )


def get_runtime_directory() -> str:
    
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        if os.path.basename(exe_dir).lower() == "lib":
            return os.path.dirname(exe_dir)
        return exe_dir
    return _get_repo_root()


def get_bundle_resource_root() -> str:
    
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return normalize_filesystem_path(meipass)
        return os.path.dirname(sys.executable)
    return _get_repo_root()


def get_assets_directory() -> str:
    
    bundle_root = get_bundle_resource_root()
    candidates = [os.path.join(bundle_root, "assets")]

    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        exe_assets = os.path.join(exe_dir, "assets")
        internal_assets = os.path.join(exe_dir, "_internal", "assets")
        for path in (exe_assets, internal_assets):
            if path not in candidates:
                candidates.append(path)

    for path in candidates:
        if os.path.isdir(path):
            return path

    return os.path.join(bundle_root, "assets")


def get_resource_path(relative_path: str) -> str:
    
    return os.path.normpath(os.path.join(get_bundle_resource_root(), relative_path))


__all__ = [
    "get_runtime_directory",
    "get_bundle_resource_root",
    "get_assets_directory",
    "get_resource_path",
]
