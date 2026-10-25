from __future__ import annotations

import pytest

from software.network.proxy.pool import prefetch
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

    @pytest.mark.asyncio
    async def test_prefetch_proxy_pool_passes_effective_url_and_minimum_count(
        self, patch_attrs
    ) -> None:
        calls: list[dict[str, object]] = []

        def fake_fetch(**kwargs):
            calls.append(kwargs)
            return ["lease"]

        import software.network.proxy.api as proxy_api

        async def fake_fetch_async(**kwargs):
            return fake_fetch(**kwargs)

        patch_attrs(
            (prefetch, "get_effective_proxy_api_url", lambda: "https://proxy.example/api"),
            (proxy_api, "fetch_proxy_batch_async", fake_fetch_async),
        )

        assert await prefetch.prefetch_proxy_pool(0) == ["lease"]
        assert calls == [
            {
                "expected_count": 1,
                "proxy_url": "https://proxy.example/api",
                "notify_on_area_error": False,
                "stop_signal": None,
            }
        ]

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
