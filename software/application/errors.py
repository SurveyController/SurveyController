from __future__ import annotations


class ProxyAuthenticationError(RuntimeError):
    def __init__(
        self,
        detail: str,
        *,
        status_code: int = 0,
        retry_after_seconds: int = 0,
    ) -> None:
        self.detail = str(detail or "unknown_error")
        self.status_code = int(status_code or 0)
        self.retry_after_seconds = max(0, int(retry_after_seconds or 0))
        super().__init__(self.detail)


__all__ = ["ProxyAuthenticationError"]
