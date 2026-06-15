from __future__ import annotations

from software.ui.widgets.contact_form.send_workflow import (
    compute_send_timeout_fallback_ms,
    validate_email,
)


def test_contact_form_helper_functions() -> None:
    assert compute_send_timeout_fallback_ms(
        connect_timeout_seconds=5,
        read_timeout_seconds=10,
        grace_ms=1500,
    ) == 26_500
    assert validate_email("") is True
    assert validate_email("user@example.com") is True
    assert validate_email("bad@@mail") is False
