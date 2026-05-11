from __future__ import annotations

import gc
from dataclasses import dataclass

from software.network.browser.runtime_async import BrowserDriver
from software.providers.common import SURVEY_PROVIDER_WJX
from software.providers.runtime_state import ProviderRuntimeState, get_provider_runtime_state_store


@dataclass
class _DummyState(ProviderRuntimeState):
    value: int = 0


class _DummyDriver:
    pass


class ProviderRuntimeStateTests:
    def test_store_isolates_state_by_driver_instance(self) -> None:
        store = get_provider_runtime_state_store(f"{SURVEY_PROVIDER_WJX}-runtime-state-test-isolation", _DummyState)
        driver_a = _DummyDriver()
        driver_b = _DummyDriver()

        state_a = store.get_or_create(driver_a)
        state_b = store.get_or_create(driver_b)
        state_a.value = 11
        state_b.value = 22

        assert store.get_or_create(driver_a).value == 11
        assert store.get_or_create(driver_b).value == 22
        assert state_a is not state_b

    def test_store_releases_state_when_driver_is_gone(self) -> None:
        store = get_provider_runtime_state_store(f"{SURVEY_PROVIDER_WJX}-runtime-state-test-gc", _DummyState)
        driver = _DummyDriver()
        store.get_or_create(driver).value = 7

        assert store.snapshot_size() == 1

        del driver
        gc.collect()

        assert store.snapshot_size() == 0

    def test_browser_driver_protocol_stays_free_of_provider_runtime_fields(self) -> None:
        annotations = dict(getattr(BrowserDriver, "__annotations__", {}) or {})
        banned_fields = {
            "_wjx_runtime_page_number",
            "_wjx_runtime_page_questions",
            "_wjx_runtime_indices_snapshot",
            "_wjx_runtime_psycho_plan",
            "_wjx_submission_recovery_attempts",
            "_qq_runtime_page_index",
            "_credamo_runtime_page_index",
        }

        assert not banned_fields.intersection(annotations)
