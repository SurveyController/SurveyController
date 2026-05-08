#!/usr/bin/env python
"""裁剪 Velopack feed，只保留最近 N 个 Full 版本及其有效 Delta。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from packaging.version import Version, InvalidVersion
except ImportError as exc:  # pragma: no cover
    raise SystemExit(f"缺少 packaging 依赖：{exc}")


@dataclass(frozen=True)
class AssetRecord:
    raw: dict[str, Any]
    version_text: str
    parsed_version: Version
    asset_type: str
    file_name: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Trim Velopack feed history.")
    parser.add_argument("--release-dir", required=True, help="Releases 目录")
    parser.add_argument("--channel", default="stable", help="更新通道")
    parser.add_argument("--keep-full", type=int, default=6, help="保留的 Full 版本数")
    return parser.parse_args()


def _normalize_version(value: Any) -> str:
    return str(value or "").strip()


def _parse_version(value: str) -> Version | None:
    try:
        return Version(value)
    except InvalidVersion:
        return None


def _load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"manifest 格式不对：{path}")
    assets = payload.get("Assets")
    if not isinstance(assets, list):
        raise ValueError(f"manifest 缺少 Assets 列表：{path}")
    return payload


def _build_records(assets: list[dict[str, Any]]) -> list[AssetRecord]:
    records: list[AssetRecord] = []
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        version_text = _normalize_version(asset.get("Version"))
        asset_type = _normalize_version(asset.get("Type"))
        file_name = _normalize_version(asset.get("FileName"))
        if not version_text or not asset_type or not file_name:
            continue
        parsed = _parse_version(version_text)
        if parsed is None:
            continue
        records.append(
            AssetRecord(
                raw=asset,
                version_text=version_text,
                parsed_version=parsed,
                asset_type=asset_type,
                file_name=file_name,
            )
        )
    return records


def _pick_kept_full_versions(records: list[AssetRecord], keep_full: int) -> list[Version]:
    full_versions = sorted(
        {record.parsed_version for record in records if record.asset_type.lower() == "full"},
        reverse=True,
    )
    return full_versions[: max(keep_full, 0)]


def _guess_delta_base_version(file_name: str) -> Version | None:
    match = re.search(r"-(\d+(?:\.\d+){1,3}(?:[A-Za-z0-9.\-_]+)?)-(?:delta|Delta)\.nupkg$", file_name)
    if not match:
        return None
    return _parse_version(match.group(1))


def _filter_records(records: list[AssetRecord], keep_versions: set[Version]) -> list[AssetRecord]:
    kept: list[AssetRecord] = []
    for record in records:
        asset_type = record.asset_type.lower()
        if asset_type == "full":
            if record.parsed_version in keep_versions:
                kept.append(record)
            continue
        if asset_type == "delta":
            if record.parsed_version not in keep_versions:
                continue
            base_version = _guess_delta_base_version(record.file_name)
            if base_version is not None and base_version not in keep_versions:
                continue
            kept.append(record)
            continue
        kept.append(record)
    return kept


def _rewrite_manifest(path: Path, payload: dict[str, Any], kept_records: list[AssetRecord]) -> None:
    payload["Assets"] = [record.raw for record in kept_records]
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def _collect_manifest_files(channel: str, release_dir: Path) -> list[Path]:
    candidate = release_dir / f"releases.{channel}.json"
    return [candidate] if candidate.exists() else []


def _safe_print(message: str) -> None:
    stdout = sys.stdout
    encoding = stdout.encoding or "utf-8"
    try:
        stdout.write(message + "\n")
    except UnicodeEncodeError:
        stdout.buffer.write((message + "\n").encode(encoding, errors="backslashreplace"))


def main() -> int:
    args = parse_args()
    release_dir = Path(args.release_dir).resolve()
    if not release_dir.exists():
        raise SystemExit(f"Releases 目录不存在：{release_dir}")

    manifest_path = release_dir / f"releases.{args.channel}.json"
    if not manifest_path.exists():
        raise SystemExit(f"找不到 feed 文件：{manifest_path}")

    payload = _load_manifest(manifest_path)
    records = _build_records(payload.get("Assets", []))
    keep_versions = set(_pick_kept_full_versions(records, args.keep_full))
    kept_records = _filter_records(records, keep_versions)
    kept_file_names = {record.file_name for record in kept_records}

    _rewrite_manifest(manifest_path, payload, kept_records)

    protected_names = {manifest_path.name, f"assets.{args.channel}.json", f"RELEASES-{args.channel}"}
    for path in release_dir.iterdir():
        if not path.is_file():
            continue
        if path.name in protected_names:
            continue
        if path.name not in kept_file_names and path.suffix.lower() in {".nupkg", ".zip"}:
            path.unlink()

    kept_versions_text = ", ".join(str(version) for version in sorted(keep_versions, reverse=True))
    _safe_print(f"[INFO] 保留 Full 版本: {kept_versions_text}")
    _safe_print(f"[INFO] 保留资产数: {len(kept_records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
