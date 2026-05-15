"""联系表单消息与请求字段拼装。"""

from .constants import REQUEST_MESSAGE_TYPE


def build_contact_message(
    *,
    version_str: str,
    message_type: str,
    issue_title: str,
    email: str,
    donated: bool,
    random_ip_user_id: int,
    message: str,
    request_payment_method: str,
    request_amount_text: str,
    request_quota_text: str,
    request_urgency_text: str,
) -> str:
    lines = [f"来源：SurveyController v{version_str}", f"类型：{message_type}"]
    if email:
        lines.append(f"联系邮箱： {email}")
    if issue_title and message_type == "报错反馈":
        lines.append(f"反馈标题： {issue_title}")
    if message_type == REQUEST_MESSAGE_TYPE:
        lines.append(f"已支付：{'是' if donated else '否'}")
    if random_ip_user_id > 0:
        lines.append(f"随机IP用户ID：{random_ip_user_id}")
    if message_type == REQUEST_MESSAGE_TYPE:
        lines.extend(
            [
                f"支付方式：{request_payment_method}",
                f"支付金额：￥{request_amount_text}",
                f"申请额度：{request_quota_text}",
                f"紧急程度：{request_urgency_text or '中'}",
                "",
                f"\n补充说明：{message or '未填写'}",
            ]
        )
    else:
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
