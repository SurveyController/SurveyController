from __future__ import annotations

import json
import sys
from pathlib import Path

from CI.release_tools import trim_velopack_feed


def test_drop_version_removes_matching_assets_only(tmp_path: Path, monkeypatch) -> None:
    release_dir = tmp_path
    manifest_path = release_dir / "releases.stable.json"
    manifest_path.write_text(
        json.dumps(
            {
                "Assets": [
                    {
                        "Version": "3.1.2",
                        "Type": "Full",
                        "FileName": "SurveyController-3.1.2-stable-full.nupkg",
                    },
                    {
                        "Version": "3.1.3",
                        "Type": "Full",
                        "FileName": "SurveyController-3.1.3-stable-full.nupkg",
                    },
                    {
                        "Version": "3.1.3",
                        "Type": "Delta",
                        "FileName": "SurveyController-3.1.3-stable-delta.nupkg",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    for file_name in (
        "SurveyController-3.1.2-stable-full.nupkg",
        "SurveyController-3.1.3-stable-full.nupkg",
        "SurveyController-3.1.3-stable-delta.nupkg",
    ):
        (release_dir / file_name).write_text("x", encoding="utf-8")

    args = [
        "trim_velopack_feed.py",
        "--release-dir",
        str(release_dir),
        "--channel",
        "stable",
        "--keep-full",
        "6",
        "--drop-version",
        "3.1.3",
    ]
    monkeypatch.setattr(sys, "argv", args)
    assert trim_velopack_feed.main() == 0

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert [asset["Version"] for asset in payload["Assets"]] == ["3.1.2"]
    assert (release_dir / "SurveyController-3.1.2-stable-full.nupkg").exists()
    assert not (release_dir / "SurveyController-3.1.3-stable-full.nupkg").exists()
    assert not (release_dir / "SurveyController-3.1.3-stable-delta.nupkg").exists()


def test_drop_version_keeps_legacy_metadata_files(tmp_path: Path, monkeypatch) -> None:
    release_dir = tmp_path
    manifest_path = release_dir / "releases.stable.json"
    manifest_path.write_text(
        json.dumps(
            {
                "Assets": [
                    {
                        "Version": "3.2.1",
                        "Type": "Full",
                        "FileName": "SurveyController-3.2.1-stable-full.nupkg",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (release_dir / "SurveyController-3.2.1-stable-full.nupkg").write_text("x", encoding="utf-8")
    (release_dir / "assets.stable.json").write_text("legacy", encoding="utf-8")
    (release_dir / "RELEASES-stable").write_text("legacy", encoding="utf-8")

    args = [
        "trim_velopack_feed.py",
        "--release-dir",
        str(release_dir),
        "--channel",
        "stable",
        "--keep-full",
        "6",
        "--drop-version",
        "3.2.2",
    ]
    monkeypatch.setattr(sys, "argv", args)
    assert trim_velopack_feed.main() == 0

    assert (release_dir / "assets.stable.json").exists()
    assert (release_dir / "RELEASES-stable").exists()
