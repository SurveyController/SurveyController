from __future__ import annotations

from software.core.engine.runtime_layout import build_owner_window_positions


class RuntimeLayoutTests:
    def test_build_owner_window_positions_handles_zero_and_multiple(self) -> None:
        assert build_owner_window_positions(0) == [(50, 50)]
        assert build_owner_window_positions(3) == [(50, 50), (110, 110), (170, 170)]
