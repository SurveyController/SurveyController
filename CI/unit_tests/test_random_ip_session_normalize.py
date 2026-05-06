from __future__ import annotations
import pytest
from software.network.proxy.session.models import RandomIPAuthError, RandomIPSession
from software.network.proxy.session.normalize import _build_quota_snapshot, _normalize_quota_state, _require_valid_user_id, _resolve_quota_from_payload, format_quota_value

class RandomIPSessionNormalizeTests:

    def test_format_quota_value_normalizes_decimal_and_invalid_input(self) -> None:
        assert format_quota_value('2.5000') == '2.5'
        assert format_quota_value('3.0') == '3'
        assert format_quota_value('-1') == '0'
        assert format_quota_value('bad') == '0'

    def test_normalize_quota_state_prefers_used_quota_when_provided(self) -> None:
        remaining, total, used = _normalize_quota_state(total_quota=5, used_quota=7)
        assert (remaining, total, used) == (0.0, 7.0, 7.0)

    def test_normalize_quota_state_backfills_used_quota_from_remaining(self) -> None:
        remaining, total, used = _normalize_quota_state(remaining_quota=2, total_quota=5)
        assert (remaining, total, used) == (2.0, 5.0, 3.0)

    def test_require_valid_user_id_rejects_non_positive_value(self) -> None:
        with pytest.raises(RandomIPAuthError):
            _require_valid_user_id(0)
        with pytest.raises(RandomIPAuthError):
            _require_valid_user_id('bad')

    def test_resolve_quota_from_payload_accepts_complete_payload(self) -> None:
        remaining, total, used, known = _resolve_quota_from_payload({'remaining_quota': '2', 'total_quota': '5', 'used_quota': '3'}, fallback_session=None, log_context='test')
        assert (remaining, total, used, known) == (2.0, 5.0, 3.0, True)

    def test_resolve_quota_from_payload_reuses_fallback_for_partial_payload(self) -> None:
        fallback = RandomIPSession(user_id=1, remaining_quota=8, total_quota=10, used_quota=2, quota_known=True)
        remaining, total, used, known = _resolve_quota_from_payload({'used_quota': '4'}, fallback_session=fallback, log_context='test')
        assert (remaining, total, used, known) == (6.0, 10.0, 4.0, True)

    def test_resolve_quota_from_payload_marks_missing_numbers_as_untrusted(self) -> None:
        remaining, total, used, known = _resolve_quota_from_payload({'remaining_quota': '', 'used_quota': 'bad'}, fallback_session=RandomIPSession(), log_context='test')
        assert (remaining, total, used, known) == (0.0, 0.0, 0.0, False)

    def test_build_quota_snapshot_returns_normalized_numbers(self) -> None:
        session = RandomIPSession(user_id=1, remaining_quota=3, total_quota=8, used_quota=5, quota_known=True)
        assert _build_quota_snapshot(session) == {'used_quota': 5.0, 'total_quota': 8.0, 'remaining_quota': 3.0, 'quota_known': True}
