from __future__ import annotations

import logging
import re
import sys
import webbrowser
from typing import Any, Optional

import software.network.http as http_client
from software.app.version import (
    GITHUB_API_URL,
    GITHUB_RELEASES_PAGE_URL,
    GITHUB_RELEASES_URL,
    GITHUB_RELEASE_TAG_URL,
    __VERSION__,
)
from software.logging.action_logger import log_action

try:
    from packaging import version
except ImportError:
    version = None


def _preview_release_notes(text: str, limit: int) -> str:
    if not text:
        return "暂无更新说明"
    text = re.sub(r"^#{1,6}\s*", "", str(text), flags=re.MULTILINE)
    text = re.sub(r"^---+\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"~~(.+?)~~", r"\1", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"(?<!\n)\*(.+?)\*", r"\1", text)
    text = re.sub(r"^\s*[\*\-]\s+", "- ", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    preview = text[:limit]
    return preview + ("\n..." if len(text) > limit else "")


def _parse_version_text(value: str):
    if not version:
        return None
    try:
        return version.parse(str(value or "").strip())
    except Exception:
        return None


def _fetch_latest_github_release() -> Optional[dict[str, Any]]:
    try:
        response = http_client.get(
            GITHUB_API_URL,
            headers={"Accept": "application/vnd.github.v3+json"},
            timeout=(10, 30),
        )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else None
    except Exception as exc:
        logging.warning("获取最新发行版失败: %s", exc)
        return None


def _build_remote_version_result(
    current_version: str,
    latest_version: str,
    *,
    release_notes: str = "",
    release_url: str = "",
) -> dict[str, Any]:
    latest_parsed = _parse_version_text(latest_version)
    current_parsed = _parse_version_text(current_version)
    base = {
        "has_update": False,
        "current_version": current_version,
        "latest_version": latest_version,
        "release_notes": release_notes,
    }
    if latest_parsed is None or current_parsed is None:
        return {**base, "status": "unknown"}
    if latest_parsed > current_parsed:
        return {
            **base,
            "has_update": True,
            "status": "outdated",
            "version": latest_version,
            "manual_only": True,
            "manual_release_url": release_url or f"{GITHUB_RELEASE_TAG_URL}/v{latest_version}",
        }
    return {**base, "status": "preview" if current_parsed > latest_parsed else "latest"}


def _build_github_update_result(current_version: str) -> dict[str, Any]:
    github_release = _fetch_latest_github_release()
    if not github_release:
        return {"has_update": False, "status": "unknown", "current_version": current_version}
    latest_version = str(github_release.get("tag_name", "")).lstrip("v").strip()
    return _build_remote_version_result(
        current_version,
        latest_version,
        release_notes=str(github_release.get("body", "") or "").strip(),
        release_url=str(github_release.get("html_url", "") or "").strip(),
    )


class UpdateManager:
    @staticmethod
    def check_updates() -> dict[str, Any]:
        current_version = str(__VERSION__ or "").strip()
        if sys.platform != "win32":
            return {"has_update": False, "status": "unsupported", "current_version": current_version}
        if not version:
            logging.warning("更新功能依赖 packaging 模块")
            return {"has_update": False, "status": "unknown", "current_version": current_version}
        return _build_github_update_result(current_version)

    @staticmethod
    def get_all_releases() -> list[dict[str, Any]]:
        try:
            response = http_client.get(
                GITHUB_RELEASES_URL,
                headers={"Accept": "application/vnd.github.v3+json"},
                timeout=(10, 30),
            )
            response.raise_for_status()
            releases = response.json()
        except Exception as exc:
            logging.warning("获取发行版列表失败: %s", exc)
            return []
        if not isinstance(releases, list):
            return []
        return [
            {
                "version": str(release.get("tag_name", "")).lstrip("v"),
                "name": release.get("name", ""),
                "body": release.get("body", ""),
                "published_at": release.get("published_at", ""),
                "prerelease": bool(release.get("prerelease", False)),
                "html_url": release.get("html_url", ""),
            }
            for release in releases
            if isinstance(release, dict)
        ]


def show_update_notification(gui) -> None:
    if not getattr(gui, "update_info", None):
        return
    info = gui.update_info
    log_action(
        "UPDATE",
        "show_update_notification",
        "update_dialog",
        "update",
        result="shown",
        payload={"version": info.get("version", "unknown")},
    )
    release_notes_preview = _preview_release_notes(info.get("release_notes", ""), 300)
    release_url = str(info.get("manual_release_url", "") or "").strip() or GITHUB_RELEASES_PAGE_URL
    message = (
        f"检测到新版本 v{info.get('version', '未知')}\n"
        f"当前版本 v{info.get('current_version', '未知')}\n\n"
        f"发布说明:\n{release_notes_preview}\n\n"
        f"请前往发布页下载安装：\n{release_url}\n\n是否现在打开发布页？"
    )
    if gui.show_confirm_dialog("检查到更新", message):
        log_action(
            "UPDATE",
            "show_update_notification",
            "update_dialog",
            "update",
            result="accepted",
            payload={"version": info.get("version", "unknown")},
        )
        webbrowser.open(release_url)
    else:
        log_action(
            "UPDATE",
            "show_update_notification",
            "update_dialog",
            "update",
            result="declined",
            payload={"version": info.get("version", "unknown")},
        )


__all__ = ["UpdateManager", "_preview_release_notes", "show_update_notification"]
