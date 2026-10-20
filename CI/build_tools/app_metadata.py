"""Generate the version snapshot and Windows packaging values from pyproject.toml."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from packaging.version import Version

from software.app.app_info import read_project_version

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def build_metadata(project_file: Path, *, release_tag: str | None = None) -> dict[str, str]:
    version = read_project_version(project_file)
    if release_tag is not None and release_tag != f"v{version}":
        raise ValueError(f"Release tag {release_tag!r} must match project version v{version}")
    parsed = Version(version)
    release = parsed.release
    if parsed.epoch or parsed.local or len(release) > 4 or any(n > 65535 for n in release):
        raise ValueError(f"Version {version!r} cannot be represented as a Windows version")
    windows_version = ".".join(str(n) for n in (release + (0, 0, 0, 0))[:4])
    return {
        "version": version,
        "windows_version": windows_version,
        "archive_name": f"SurveyController-{version}.zip",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--release-tag", help="Require the exact v<project.version> release tag")
    args = parser.parse_args(argv)
    try:
        metadata = build_metadata(PROJECT_ROOT / "pyproject.toml", release_tag=args.release_tag)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Application metadata error: {exc}\n")
    payload = json.dumps(metadata, indent=2) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
