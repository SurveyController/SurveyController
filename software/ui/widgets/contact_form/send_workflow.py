import re


def validate_email(email: str) -> bool:
    if not email:
        return True
    return re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email) is not None


def compute_send_timeout_fallback_ms(
    *,
    connect_timeout_seconds: int,
    read_timeout_seconds: int,
    grace_ms: int,
) -> int:
    total_seconds = connect_timeout_seconds + read_timeout_seconds + read_timeout_seconds
    return int(total_seconds * 1000 + grace_ms)
