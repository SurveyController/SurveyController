from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from packaging.version import InvalidVersion, Version


ROOT_DIR = Path(__file__).resolve().parents[2]
VERSION_FILE = ROOT_DIR / "software" / "app" / "version.py"
RESULT_WAIT_SECONDS = 240
DEFAULT_FEED_URL = "https://dl.hungrym0.com/surveycontroller/win/stable/"
DEFAULT_CHANNEL = "stable"


@dataclass(frozen=True)
class FeedAsset:
    version: Version
    version_text: str
    asset_type: str
    file_name: str


def _run(command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None, timeout: int = 1800) -> None:
    result = subprocess.run(
        command,
        cwd=str(cwd or ROOT_DIR),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"命令失败: {' '.join(command)}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


def _set_version_text(version_text: str) -> None:
    content = VERSION_FILE.read_text(encoding="utf-8")
    original = '__VERSION__ = "'
    start = content.find(original)
    if start < 0:
        raise RuntimeError("找不到 __VERSION__")
    end = content.find('"', start + len(original))
    updated = f'{content[:start]}{original}{version_text}{content[end:]}'
    VERSION_FILE.write_text(updated, encoding="utf-8")


def _backup_version_file() -> str:
    return VERSION_FILE.read_text(encoding="utf-8")


def _restore_version_file(content: str) -> None:
    VERSION_FILE.write_text(content, encoding="utf-8")


def _build_release(version_text: str, release_dir: Path, output_dir: Path, channel: str) -> None:
    _run(
        [
            "powershell",
            "-ExecutionPolicy",
            "ByPass",
            "-File",
            str(ROOT_DIR / "Setup" / "build-release-installer.ps1"),
            "-OutputDir",
            str(output_dir),
            "-ReleaseDir",
            str(release_dir),
            "-Channel",
            channel,
            "-PackVersion",
            version_text,
            "-SkipSync",
            "-KeepFullVersions",
            "6",
        ],
        timeout=7200,
    )


def _normalize_feed_url(feed_url: str) -> str:
    normalized = feed_url.strip()
    if not normalized:
        raise ValueError("旧版 feed 地址不能为空")
    if not normalized.endswith("/"):
        normalized += "/"
    return normalized


def _download_file(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urlopen(url, timeout=120) as response:
            with target.open("wb") as file:
                shutil.copyfileobj(response, file)
    except (OSError, URLError) as exc:
        raise RuntimeError(f"下载失败: {url}\n{exc}") from exc


def _load_manifest(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"feed 格式不对: {path}")
    assets = payload.get("Assets")
    if not isinstance(assets, list):
        raise RuntimeError(f"feed 缺少 Assets: {path}")
    return payload


def _parse_feed_assets(manifest: dict) -> list[FeedAsset]:
    assets: list[FeedAsset] = []
    for raw_asset in manifest.get("Assets", []):
        if not isinstance(raw_asset, dict):
            continue
        version_text = str(raw_asset.get("Version") or "").strip()
        asset_type = str(raw_asset.get("Type") or "").strip()
        file_name = str(raw_asset.get("FileName") or "").strip()
        if not version_text or not asset_type or not file_name:
            continue
        try:
            version = Version(version_text)
        except InvalidVersion:
            continue
        assets.append(
            FeedAsset(
                version=version,
                version_text=version_text,
                asset_type=asset_type,
                file_name=file_name,
            )
        )
    return assets


def _resolve_old_version(assets: list[FeedAsset], requested_version: str) -> str:
    requested = requested_version.strip()
    if requested and requested.lower() != "auto":
        return requested

    full_assets = [asset for asset in assets if asset.asset_type.lower() == "full"]
    if not full_assets:
        raise RuntimeError("旧版 feed 里没有 Full 包，无法判断旧版本")
    return max(full_assets, key=lambda asset: asset.version).version_text


def _resolve_new_version(old_version: str, requested_version: str) -> str:
    requested = requested_version.strip()
    if requested and requested.lower() != "auto":
        return requested

    try:
        parsed = Version(old_version)
    except InvalidVersion as exc:
        raise RuntimeError(f"旧版本号不合法，无法自动生成候选新版: {old_version}") from exc

    release = list(parsed.release)
    while len(release) < 3:
        release.append(0)
    release[-1] += 1
    return ".".join(str(part) for part in release)


def _download_previous_release(feed_url: str, release_dir: Path, channel: str) -> tuple[str, Path]:
    normalized_feed_url = _normalize_feed_url(feed_url)
    release_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = release_dir / f"releases.{channel}.json"
    _download_file(f"{normalized_feed_url}releases.{channel}.json", manifest_path)
    manifest = _load_manifest(manifest_path)
    assets = _parse_feed_assets(manifest)
    old_version = _resolve_old_version(assets, "auto")

    for asset in assets:
        _download_file(f"{normalized_feed_url}{asset.file_name}", release_dir / asset.file_name)

    for extra_name in (f"assets.{channel}.json", f"RELEASES-{channel}"):
        try:
            _download_file(f"{normalized_feed_url}{extra_name}", release_dir / extra_name)
        except RuntimeError:
            pass

    setup_path = release_dir / f"SurveyController_v{old_version}_setup.exe"
    _download_file(f"{normalized_feed_url}{setup_path.name}", setup_path)
    return old_version, setup_path


def _wait_for_file(path: Path, *, timeout_seconds: int) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if path.exists():
            return
        time.sleep(2)
    raise TimeoutError(f"等待文件超时: {path}")


def _install_old_version(setup_path: Path, install_dir: Path, log_path: Path) -> None:
    _run(
        [
            str(setup_path),
            "--silent",
            "--log",
            str(log_path),
            "--installto",
            str(install_dir),
        ],
        timeout=900,
    )


def _resolve_installed_app_exe(install_dir: Path) -> Path:
    candidates = [
        install_dir / "SurveyController.exe",
        install_dir / "current" / "SurveyController.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"安装后的程序不存在: {candidates}")


def _launch_update_probe(
    app_exe: Path,
    feed_dir: Path,
    result_path: Path,
    expected_version: str,
    channel: str,
) -> subprocess.Popen[str]:
    env = os.environ.copy()
    env["SURVEYCONTROLLER_VELOPACK_FEED_URL"] = str(feed_dir)
    env["SURVEYCONTROLLER_VELOPACK_CHANNEL"] = channel
    env["SURVEYCONTROLLER_UPDATE_TEST_RESULT"] = str(result_path)
    env["SURVEYCONTROLLER_UPDATE_EXPECTED_VERSION"] = expected_version
    env["SURVEYCONTROLLER_UPDATE_TEST_MODE"] = "1"
    return subprocess.Popen(
        [
            str(app_exe),
            "--ci-update-probe",
        ],
        cwd=str(app_exe.parent),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )


def _read_result(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Velopack E2E update test.")
    parser.add_argument("--old-feed-url", default=DEFAULT_FEED_URL)
    parser.add_argument("--old-version", default="auto")
    parser.add_argument("--new-version", default="auto")
    parser.add_argument("--channel", default=DEFAULT_CHANNEL)
    args = parser.parse_args()

    backup = _backup_version_file()
    workspace = Path(tempfile.mkdtemp(prefix="surveycontroller-velopack-e2e-"))
    old_release_dir = workspace / "Releases-old"
    new_release_dir = workspace / "Releases-new"
    new_output_dir = workspace / "dist-new"
    install_dir = workspace / "InstallRoot"
    result_path = workspace / "probe-result.json"
    setup_log_path = workspace / "setup.log"

    try:
        downloaded_old_version, setup_path = _download_previous_release(
            args.old_feed_url,
            old_release_dir,
            args.channel,
        )
        old_version = _resolve_old_version(
            _parse_feed_assets(_load_manifest(old_release_dir / f"releases.{args.channel}.json")),
            args.old_version,
        )
        if old_version != downloaded_old_version:
            setup_path = old_release_dir / f"SurveyController_v{old_version}_setup.exe"
            _download_file(f"{_normalize_feed_url(args.old_feed_url)}{setup_path.name}", setup_path)

        new_version = _resolve_new_version(old_version, args.new_version)
        print(f"Velopack E2E: old={old_version}, new={new_version}, channel={args.channel}")
        _set_version_text(new_version)
        if new_release_dir.exists():
            shutil.rmtree(new_release_dir)
        shutil.copytree(old_release_dir, new_release_dir)
        _build_release(new_version, new_release_dir, new_output_dir, args.channel)

        if not setup_path.exists():
            raise FileNotFoundError(f"旧版安装器不存在: {setup_path}")
        _install_old_version(setup_path, install_dir, setup_log_path)

        app_exe = _resolve_installed_app_exe(install_dir)

        process = _launch_update_probe(app_exe, new_release_dir, result_path, new_version, args.channel)
        try:
            process.wait(timeout=90)
        except subprocess.TimeoutExpired:
            process.kill()
            raise TimeoutError("旧版探针进程未在 90 秒内结束")

        _wait_for_file(result_path, timeout_seconds=RESULT_WAIT_SECONDS)
        payload = _read_result(result_path)
        if payload.get("status") != "restarted":
            raise RuntimeError(f"更新未完成重启: {json.dumps(payload, ensure_ascii=False)}")
        if str(payload.get("version", "")).strip() != new_version:
            raise RuntimeError(f"更新后版本不对: {json.dumps(payload, ensure_ascii=False)}")
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    finally:
        _restore_version_file(backup)


if __name__ == "__main__":
    raise SystemExit(main())
