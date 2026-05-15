from __future__ import annotations

from types import SimpleNamespace

import software.ui.pages.workbench.dashboard.parts.random_ip as dashboard_random_ip
from software.ui.pages.workbench.dashboard.parts.random_ip import DashboardRandomIPMixin


class _FakeButton:
    def __init__(self) -> None:
        self.enabled = True
        self.text = ""
        self.tooltip = ""
        self.icon = None

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)

    def setText(self, text: str) -> None:
        self.text = str(text)

    def setToolTip(self, tooltip: str) -> None:
        self.tooltip = str(tooltip)

    def setIcon(self, icon) -> None:
        self.icon = icon


class _FakeRing:
    def __init__(self) -> None:
        self.range = (0, 100)
        self.value = 0
        self.text_visible = False
        self.format_text = ""
        self.paused = False
        self.error = False
        self.colors = None

    def setRange(self, minimum: int, maximum: int) -> None:
        self.range = (minimum, maximum)

    def setValue(self, value: int) -> None:
        self.value = int(value)

    def setTextVisible(self, visible: bool) -> None:
        self.text_visible = bool(visible)

    def setFormat(self, text: str) -> None:
        self.format_text = str(text)

    def setPaused(self, paused: bool) -> None:
        self.paused = bool(paused)

    def setError(self, error: bool) -> None:
        self.error = bool(error)

    def setCustomBarColor(self, color1, color2) -> None:
        self.colors = (color1.name(), color2.name())


class _FakeToggle:
    def __init__(self) -> None:
        self.checked = False
        self.blocked = []

    def isChecked(self) -> bool:
        return self.checked

    def blockSignals(self, blocked: bool) -> None:
        self.blocked.append(bool(blocked))

    def setChecked(self, checked: bool) -> None:
        self.checked = bool(checked)


class _FakeDashboard(DashboardRandomIPMixin):
    def __init__(self) -> None:
        self.card_btn = _FakeButton()
        self.random_ip_usage_ring = _FakeRing()
        self.random_ip_cb = _FakeToggle()
        self.controller = SimpleNamespace(set_runtime_ui_state=lambda **_kwargs: None)
        self.low_infobar_calls = []
        self.cost_infobar_calls = []
        self.sync_calls = []

    def _update_ip_low_infobar(self, count: float, limit: float, custom_api: bool) -> None:
        self.low_infobar_calls.append((count, limit, custom_api))

    def _update_ip_cost_infobar(self, custom_api: bool) -> None:
        self.cost_infobar_calls.append(bool(custom_api))

    def _sync_random_ip_toggle_presentation(self, enabled: bool) -> None:
        self.sync_calls.append(bool(enabled))


class DashboardRandomIPTests:
    def test_counter_card_shows_remaining_quota_and_inverse_warning_colors(self, monkeypatch) -> None:
        dashboard = _FakeDashboard()

        monkeypatch.setattr(
            dashboard_random_ip,
            "get_session_snapshot",
            lambda: {
                "authenticated": True,
                "user_id": 7,
                "remaining_quota": 2,
                "total_quota": 10,
            },
        )
        monkeypatch.setattr(dashboard_random_ip, "has_authenticated_session", lambda: True)
        monkeypatch.setattr(dashboard_random_ip, "has_unknown_local_quota", lambda _snapshot: False)
        monkeypatch.setattr(dashboard_random_ip, "is_quota_exhausted", lambda _snapshot: False)
        monkeypatch.setattr(dashboard_random_ip, "load_shop_icon", lambda: None)

        dashboard.update_random_ip_counter(8, 10, False)

        assert dashboard.card_btn.text == "额度兑换"
        assert dashboard.random_ip_usage_ring.format_text == "2/10"
        assert dashboard.random_ip_usage_ring.value == 20
        assert dashboard.random_ip_usage_ring.colors == ("#c77900", "#ffb347")
        assert dashboard.random_ip_usage_ring.paused is False
        assert dashboard.random_ip_usage_ring.error is False
