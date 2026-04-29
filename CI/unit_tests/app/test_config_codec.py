from __future__ import annotations

import unittest

from software.core.config.codec import (
    CURRENT_CONFIG_SCHEMA_VERSION,
    _ensure_supported_config_payload,
    deserialize_runtime_config,
    serialize_runtime_config,
)
from software.core.config.schema import RuntimeConfig
from software.core.reverse_fill.schema import REVERSE_FILL_FORMAT_WJX_SEQUENCE


class ConfigCodecTests(unittest.TestCase):
    def test_runtime_config_roundtrip_keeps_reverse_fill_fields(self) -> None:
        config = RuntimeConfig(
            reverse_fill_enabled=True,
            reverse_fill_source_path="D:/demo.xlsx",
            reverse_fill_format=REVERSE_FILL_FORMAT_WJX_SEQUENCE,
            reverse_fill_start_row=3,
        )

        payload = serialize_runtime_config(config)
        restored = deserialize_runtime_config(payload)

        self.assertEqual(payload["config_schema_version"], CURRENT_CONFIG_SCHEMA_VERSION)
        self.assertTrue(restored.reverse_fill_enabled)
        self.assertEqual(restored.reverse_fill_source_path, "D:/demo.xlsx")
        self.assertEqual(restored.reverse_fill_format, REVERSE_FILL_FORMAT_WJX_SEQUENCE)
        self.assertEqual(restored.reverse_fill_start_row, 3)

    def test_legacy_v4_payload_is_upgraded_to_v5_with_reverse_fill_defaults(self) -> None:
        upgraded = _ensure_supported_config_payload(
            {
                "config_schema_version": 4,
                "reverse_fill_enabled": True,
                "reverse_fill_source_path": "D:/legacy.xlsx",
                "reverse_fill_format": "unknown",
                "reverse_fill_start_row": 0,
            },
            config_path="legacy.json",
        )

        self.assertEqual(upgraded["config_schema_version"], CURRENT_CONFIG_SCHEMA_VERSION)
        self.assertTrue(upgraded["reverse_fill_enabled"])
        self.assertEqual(upgraded["reverse_fill_source_path"], "D:/legacy.xlsx")
        self.assertEqual(upgraded["reverse_fill_format"], "auto")
        self.assertEqual(upgraded["reverse_fill_start_row"], 1)


if __name__ == "__main__":
    unittest.main()
