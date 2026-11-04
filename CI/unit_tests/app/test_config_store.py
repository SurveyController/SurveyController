from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

import software.io.config.store as config_store
from software.core.config.schema import RuntimeConfig


class ConfigStoreTests:
    def test_sanitize_filename_removes_illegal_characters_and_limits_length(self) -> None:
        sanitized = config_store._sanitize_filename('  A / B: C*? "<>|  ')
        assert sanitized == "A__B_C_"
        assert not any(ch in sanitized for ch in '\\/:*?"<>|')
        assert config_store._sanitize_filename("x" * 100, max_length=8) == "x" * 8

    def test_sanitize_filename_falls_back_when_title_has_no_usable_text(self) -> None:
        assert config_store._sanitize_filename(" \n\t ") == "wjx_config"
        assert config_store._sanitize_filename(None) == "wjx_config"

    def test_build_default_config_filename_uses_sanitized_title(self) -> None:
        assert config_store.build_default_config_filename("问卷 / 标题") == "问卷__标题.json"
        assert config_store.build_default_config_filename("") == "wjx_config.json"

    def test_strip_json_comments_preserves_comment_like_text_inside_strings(self) -> None:
        raw = '{"url": "https://example.com/a//b", "note": "/* keep */"} // remove me\n'

        payload = json.loads(config_store._strip_json_comments(raw))

        assert payload == {"url": "https://example.com/a//b", "note": "/* keep */"}

    def test_load_config_reads_commented_json_payload(self, tmp_path: Path) -> None:
        path = tmp_path / "config.json"
        path.write_text(
            """
            {
              // 用户手写注释
              "url": "https://www.wjx.cn/vm/demo.aspx",
              "target": "9",
              "threads": 3
            }
            """,
            encoding="utf-8",
        )

        config = config_store.load_config(str(path), strict=True)

        assert config.url == "https://www.wjx.cn/vm/demo.aspx"
        assert config.target == 9
        assert config.threads == 3

    def test_load_config_returns_default_when_missing_or_invalid_in_non_strict_mode(
        self, tmp_path: Path
    ) -> None:
        missing = config_store.load_config(str(tmp_path / "missing.json"))
        assert isinstance(missing, RuntimeConfig)
        assert missing.url == ""

        bad_path = tmp_path / "bad.json"
        bad_path.write_text("{bad json", encoding="utf-8")
        bad = config_store.load_config(str(bad_path), strict=False)
        assert isinstance(bad, RuntimeConfig)
        assert bad.url == ""

    def test_load_config_raises_clear_error_for_invalid_json_in_strict_mode(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "bad.json"
        path.write_text("{bad json", encoding="utf-8")

        with pytest.raises(ValueError, match="读取配置失败"):
            config_store.load_config(str(path), strict=True)

    def test_load_config_repairs_empty_default_config_in_non_strict_mode(
        self, tmp_path: Path
    ) -> None:
        default_path = tmp_path / "config.json"
        default_path.write_text("", encoding="utf-8")

        with (
            patch("software.io.config.store._default_config_path", return_value=str(default_path)),
            patch("software.io.config.store.get_legacy_runtime_config_path", return_value=None),
        ):
            config = config_store.load_config(strict=False)

        assert isinstance(config, RuntimeConfig)
        assert default_path.read_text(encoding="utf-8") == "{}\n"

    def test_load_config_reads_legacy_default_without_modifying_it(
        self,
        tmp_path: Path,
    ) -> None:
        default_path = tmp_path / "configs" / "config.json"
        legacy_path = tmp_path / "config.json"
        legacy_path.write_text('{"url": "https://legacy.test"}\n', encoding="utf-8")
        original_content = legacy_path.read_text(encoding="utf-8")

        with (
            patch("software.io.config.store._default_config_path", return_value=str(default_path)),
            patch(
                "software.io.config.store.get_legacy_runtime_config_path",
                return_value=str(legacy_path),
            ),
        ):
            config = config_store.load_config(strict=True)

        assert config.url == "https://legacy.test"
        assert legacy_path.read_text(encoding="utf-8") == original_content
        assert not default_path.exists()

    def test_load_config_prefers_new_default_when_both_paths_exist(
        self,
        tmp_path: Path,
    ) -> None:
        default_path = tmp_path / "configs" / "config.json"
        legacy_path = tmp_path / "config.json"
        default_path.parent.mkdir()
        default_path.write_text('{"url": "https://current.test"}\n', encoding="utf-8")
        legacy_path.write_text('{"url": "https://legacy.test"}\n', encoding="utf-8")

        with (
            patch("software.io.config.store._default_config_path", return_value=str(default_path)),
            patch(
                "software.io.config.store.get_legacy_runtime_config_path",
                return_value=str(legacy_path),
            ),
        ):
            config = config_store.load_config(strict=True)

        assert config.url == "https://current.test"
        assert legacy_path.read_text(encoding="utf-8") == '{"url": "https://legacy.test"}\n'

    def test_save_default_config_writes_new_path_and_keeps_legacy_file(
        self,
        tmp_path: Path,
    ) -> None:
        default_path = tmp_path / "configs" / "config.json"
        legacy_path = tmp_path / "config.json"
        legacy_path.write_text('{"url": "https://legacy.test"}\n', encoding="utf-8")
        original_content = legacy_path.read_text(encoding="utf-8")

        with (
            patch("software.io.config.store._default_config_path", return_value=str(default_path)),
            patch(
                "software.io.config.store.get_legacy_runtime_config_path",
                return_value=str(legacy_path),
            ),
        ):
            saved_path = config_store.save_config(RuntimeConfig(url="https://new.test"))

        assert saved_path == str(default_path)
        assert config_store.load_config(str(default_path), strict=True).url == "https://new.test"
        assert legacy_path.read_text(encoding="utf-8") == original_content

    def test_load_config_rejects_non_object_payload_in_strict_mode(self, tmp_path: Path) -> None:
        path = tmp_path / "list.json"
        path.write_text("[]", encoding="utf-8")

        with pytest.raises(ValueError, match="JSON 顶层必须是对象"):
            config_store.load_config(str(path), strict=True)

    def test_load_config_ignores_unknown_keys_in_strict_mode(self, tmp_path: Path) -> None:
        path = tmp_path / "legacy.json"
        path.write_text(
            '{"url": "https://example.test", "random_proxy_api": "old"}', encoding="utf-8"
        )

        assert config_store.load_config(str(path), strict=True).url == "https://example.test"

    def test_save_config_creates_parent_directory_and_round_trips(self, tmp_path: Path) -> None:
        path = tmp_path / "nested" / "config.json"
        saved_path = config_store.save_config(
            RuntimeConfig(url="https://example.test", target=12, ai_api_key="export-only"),
            str(path),
        )

        assert saved_path == str(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["url"] == "https://example.test"
        assert "ai_api_key" not in payload
        assert config_store.load_config(str(path), strict=True).target == 12

    def test_save_config_includes_key_only_when_explicitly_requested(self, tmp_path: Path) -> None:
        path = tmp_path / "export.json"

        config_store.save_config(
            RuntimeConfig(ai_api_key="export-only"),
            str(path),
            include_secrets=True,
        )

        assert json.loads(path.read_text(encoding="utf-8"))["ai_api_key"] == "export-only"

    def test_save_config_preserves_existing_file_when_atomic_replace_fails(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "config.json"
        original_content = '{"url": "https://existing.test"}\n'
        path.write_text(original_content, encoding="utf-8")

        with patch("software.io.config.store.os.replace", side_effect=OSError("replace failed")):
            with pytest.raises(OSError, match="replace failed"):
                config_store.save_config(RuntimeConfig(url="https://new.test"), str(path))

        assert path.read_text(encoding="utf-8") == original_content
        assert list(tmp_path.glob("*.tmp")) == []
