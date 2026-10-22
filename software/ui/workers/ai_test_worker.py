def ai_test_result(result: str | None = None, error: Exception | None = None) -> tuple[bool, str]:
    if error is not None:
        return False, f"连接失败: {error}"
    message = str(result or "")
    return message.startswith("连接成功"), message


__all__ = ["ai_test_result"]
