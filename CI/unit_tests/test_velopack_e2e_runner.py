from __future__ import annotations

import pytest

from CI.live_tests import run_velopack_e2e


def test_resolve_old_version_uses_latest_full_asset() -> None:
    assets = run_velopack_e2e._parse_feed_assets(
        {
            "Assets": [
                {
                    "Version": "3.2.0",
                    "Type": "Full",
                    "FileName": "SurveyController-3.2.0-stable-full.nupkg",
                },
                {
                    "Version": "3.2.1",
                    "Type": "Delta",
                    "FileName": "SurveyController-3.2.1-stable-delta.nupkg",
                },
                {
                    "Version": "3.1.9",
                    "Type": "Full",
                    "FileName": "SurveyController-3.1.9-stable-full.nupkg",
                },
            ]
        }
    )

    assert run_velopack_e2e._resolve_old_version(assets, "auto") == "3.2.0"


def test_resolve_new_version_bumps_patch_when_auto() -> None:
    assert run_velopack_e2e._resolve_new_version("3.2.0", "auto") == "3.2.1"
    assert run_velopack_e2e._resolve_new_version("3.2", "auto") == "3.2.1"


def test_resolve_new_version_keeps_explicit_value() -> None:
    assert run_velopack_e2e._resolve_new_version("3.2.0", "4.0.0") == "4.0.0"


def test_normalize_feed_url_requires_non_empty_url() -> None:
    assert run_velopack_e2e._normalize_feed_url("https://example.test/feed") == "https://example.test/feed/"
    with pytest.raises(ValueError):
        run_velopack_e2e._normalize_feed_url(" ")
