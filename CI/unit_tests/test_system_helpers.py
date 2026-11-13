from __future__ import annotations

from software.system import secure_store
from software.ui.helpers import ai_fill


class SystemHelpersTests:
    def test_secure_store_unsupported_and_invalid_key_paths(self, patch_attrs) -> None:
        patch_attrs((secure_store.sys, "platform", "linux"))
        secure_store.set_secret("key", "value")
        secure_store.delete_secret("key")
        assert secure_store.read_secret("key").status == "unsupported"

        assert secure_store.read_secret("").status == "invalid_key"
        secure_store.set_secret("", "value")
        secure_store.delete_secret("")

    def test_ensure_ai_ready_warns_when_config_missing(self, patch_attrs) -> None:
        calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
        patch_attrs(
            (ai_fill, "get_ai_readiness_error", lambda: "缺少 Key"),
            (ai_fill.InfoBar, "warning", lambda *args, **kwargs: calls.append((args, kwargs))),
        )

        assert ai_fill.ensure_ai_ready(parent="parent") is False
        assert "缺少 Key" in calls[0][0][1]
        assert calls[0][1]["parent"] == "parent"

        patch_attrs((ai_fill, "get_ai_readiness_error", lambda: ""))
        assert ai_fill.ensure_ai_ready(parent="parent") is True
