def build_contact_message(
    *,
    version_str: str,
    message_type: str,
    issue_title: str,
    email: str,
    random_ip_user_id: int,
    message: str,
) -> str:
    lines = [f"来源：SurveyController v{version_str}", f"类型：{message_type}"]
    if email:
        lines.append(f"联系邮箱： {email}")
    if issue_title and message_type == "报错反馈":
        lines.append(f"反馈标题： {issue_title}")
    if random_ip_user_id > 0:
        lines.append(f"随机IP用户ID：{random_ip_user_id}")
    lines.extend(["", f"消息：{message}"])
    return "\n".join(lines)


def build_contact_request_fields(
    *,
    message: str,
    message_type: str,
    issue_title: str,
    timestamp: str,
    random_ip_user_id: int,
    files_payload: list[tuple[str, tuple[str, bytes, str]]],
) -> list[tuple[str, tuple[None, str] | tuple[str, bytes, str]]]:
    fields: list[tuple[str, tuple[None, str] | tuple[str, bytes, str]]] = [
        ("message", (None, message)),
        ("messageType", (None, message_type)),
        ("timestamp", (None, timestamp)),
    ]
    if issue_title:
        fields.append(("issueTitle", (None, issue_title)))
    if random_ip_user_id > 0:
        fields.append(("userId", (None, str(random_ip_user_id))))
    fields.extend(files_payload)
    return fields
