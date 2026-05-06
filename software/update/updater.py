"""应用更新检测与执行。"""
from __future__ import annotations

import logging
import re
from threading import Thread
from typing import Any, Callable, Optional

import software.network.http as http_client
from software.app.config import VELOPACK_FEED_URL
from software.app.version import __VERSION__, GITHUB_RELEASES_URL, GITHUB_RELEASE_TAG_URL
from software.logging.action_logger import log_action

try:
    from packaging import version
except ImportError:  # pragma: no cover
    version = None

try:  # pragma: no cover - 缺依赖时统一走 unknown
    import velopack
except Exception:  # pragma: no cover
    velopack = None


def _preview_release_notes(text: str, limit: int) -> str:
    if not text:
        return "暂无更新说明"
    text = re.sub(r"^#{1,6}\s*", "", str(text), flags=re.MULTILINE)
    text = re.sub(r"^---+\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"~~(.+?)~~", r"\1", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"(?<!\n)\*(.+?)\*", r"\1", text)
    text = re.sub(r"^\s*[\*\-]\s+", "- ", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    preview = text[:limit]
    if len(text) > limit:
        preview += "\n..."
    return preview


def _parse_version_text(value: str):
    if not version:
        return None
    try:
        return version.parse(str(value or "").strip())
    except Exception:
        return None


def _normalize_release_release_notes(asset: Any) -> str:
    markdown = str(getattr(asset, "NotesMarkdown", "") or "").strip()
    if markdown:
        return markdown
    html = str(getattr(asset, "NotesHtml", "") or "").strip()
    return html


def _safe_create_update_manager():
    if velopack is None:
        return None
    try:
        return velopack.UpdateManager(VELOPACK_FEED_URL)
    except Exception as exc:
        logging.info("当前环境未安装到 Velopack，跳过更新管理器初始化: %s", exc)
        return None


def _build_update_result_from_release(update_info: Any, current_version: str) -> dict[str, Any]:
    target_release = getattr(update_info, "TargetFullRelease", None)
    latest_version = str(getattr(target_release, "Version", "") or "").strip()
    release_notes = _normalize_release_release_notes(target_release)
    return {
        "has_update": True,
        "status": "outdated",
        "version": latest_version,
        "latest_version": latest_version,
        "release_notes": release_notes,
        "current_version": current_version,
        "_velopack_update": update_info,
    }


class UpdateManager:
    """Velopack 更新管理器。"""

    @staticmethod
    def check_updates() -> dict[str, Any]:
        current_version = str(__VERSION__ or "").strip()
        if not version:
            logging.warning("更新功能依赖 packaging 模块")
            return {"has_update": False, "status": "unknown", "current_version": current_version}

        manager = _safe_create_update_manager()
        if manager is None:
            return {"has_update": False, "status": "unknown", "current_version": current_version}

        try:
            installed_version = str(manager.get_current_version() or current_version).strip() or current_version
        except Exception:
            installed_version = current_version

        try:
            update_info = manager.check_for_updates()
        except Exception as exc:
            logging.warning("检查更新失败: %s", exc)
            return {"has_update": False, "status": "unknown", "current_version": installed_version}

        if update_info:
            return _build_update_result_from_release(update_info, installed_version)

        local_parsed = _parse_version_text(installed_version)
        current_parsed = _parse_version_text(current_version)
        if local_parsed is not None and current_parsed is not None and current_parsed > local_parsed:
            return {
                "has_update": False,
                "status": "preview",
                "current_version": current_version,
                "latest_version": installed_version,
            }
        return {"has_update": False, "status": "latest", "current_version": installed_version}

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

        result: list[dict[str, Any]] = []
        for release in releases:
            result.append(
                {
                    "version": str(release.get("tag_name", "")).lstrip("v"),
                    "name": release.get("name", ""),
                    "body": release.get("body", ""),
                    "published_at": release.get("published_at", ""),
                    "prerelease": bool(release.get("prerelease", False)),
                    "html_url": release.get("html_url", ""),
                }
            )
        return result

    @staticmethod
    def download_update(
        update_info: Any,
        *,
        progress_callback: Optional[Callable[[int, int, float], None]] = None,
    ) -> bool:
        manager = _safe_create_update_manager()
        if manager is None:
            raise RuntimeError("当前运行环境不支持 Velopack 更新")

        def _on_progress(percent: int) -> None:
            if progress_callback is None:
                return
            normalized = max(0, min(100, int(percent or 0)))
            progress_callback(normalized, 100, 0.0)

        manager.download_updates(update_info, _on_progress)
        return True

    @staticmethod
    def apply_downloaded_update(update_info: Any) -> None:
        manager = _safe_create_update_manager()
        if manager is None:
            raise RuntimeError("当前运行环境不支持 Velopack 更新")
        manager.wait_exit_then_apply_updates(update_info, silent=True, restart=True)


def show_update_notification(gui) -> None:
    """显示更新通知（如果 gui.update_info 存在）。"""
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
    manual_release_url = f"{GITHUB_RELEASE_TAG_URL}/v{info.get('version', '')}"
    msg = (
        f"检测到新版本 v{info['version']}\n"
        f"当前版本 v{info['current_version']}\n\n"
        f"发布说明:\n{release_notes_preview}\n\n"
        f"如果自动更新失败，可手动前往发布页下载安装：\n{manual_release_url}\n\n"
        f"是否要立即下载更新？"
    )

    if gui.show_confirm_dialog("检查到更新", msg):
        log_action(
            "UPDATE",
            "show_update_notification",
            "update_dialog",
            "update",
            result="accepted",
            payload={"version": info.get("version", "unknown")},
        )
        perform_update(gui)
    else:
        log_action(
            "UPDATE",
            "show_update_notification",
            "update_dialog",
            "update",
            result="declined",
            payload={"version": info.get("version", "unknown")},
        )


def perform_update(
    gui,
    *,
    on_progress: Optional[Callable[[int, int, float], None]] = None,
) -> None:
    """执行更新：下载 Velopack 更新包并等待应用安装。"""
    if not getattr(gui, "update_info", None):
        return

    update_payload = gui.update_info
    velopack_update = update_payload.get("_velopack_update")
    if velopack_update is None:
        gui.downloadFailed.emit("当前更新信息无效，请稍后重试")
        return

    gui._download_cancelled = False

    def update_progress(downloaded: int, total: int, speed: float = 0) -> None:
        try:
            gui._emit_download_progress(downloaded, total, speed)
        except Exception:
            logging.info("GUI 进度回调失败", exc_info=True)
        if on_progress is not None:
            try:
                on_progress(downloaded, total, speed)
            except Exception:
                logging.info("更新进度回调失败", exc_info=True)

    gui.downloadStarted.emit()

    def do_update() -> None:
        try:
            UpdateManager.download_update(velopack_update, progress_callback=update_progress)
            if getattr(gui, "_download_cancelled", False):
                return
            if on_progress is not None:
                on_progress(100, 100, 0.0)
            gui.downloadFinished.emit(update_payload)
        except Exception as exc:
            if not getattr(gui, "_download_cancelled", False):
                logging.error("更新过程中出错: %s", exc)
                gui.downloadFailed.emit(f"更新失败：{exc}")

    Thread(target=do_update, daemon=True, name="VelopackUpdateDownload").start()


__all__ = [
    "UpdateManager",
    "_preview_release_notes",
    "perform_update",
    "show_update_notification",
]
