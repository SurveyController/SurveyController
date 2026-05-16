"""联系表单里的额度申请规则。"""

from decimal import Decimal, InvalidOperation
from typing import Optional

from software.ui.helpers.contact_api import format_quota_value

from .constants import (
    DONATION_AMOUNT_OPTIONS,
    DONATION_AMOUNT_RULES,
    MAX_REQUEST_QUOTA,
    REQUEST_QUOTA_STEP,
)


def parse_quantity_value(text: Optional[str]) -> Optional[Decimal]:
    raw_text = (text or "").strip()
    if not raw_text:
        return None
    try:
        value = Decimal(raw_text)
    except (InvalidOperation, ValueError):
        return None
    if value < 0:
        return None
    scaled = value / REQUEST_QUOTA_STEP
    if scaled != scaled.to_integral_value():
        return None
    return value


def normalize_quantity_text(text: str) -> str:
    quantity = parse_quantity_value(text)
    if quantity is None:
        return (text or "").strip()
    return format_quota_value(quantity)


def parse_amount_value(text: Optional[str]) -> Optional[Decimal]:
    raw_text = (text or "").strip()
    if not raw_text:
        return None
    try:
        value = Decimal(raw_text)
    except (InvalidOperation, ValueError):
        return None
    if value <= 0:
        return None
    return value


def get_minimum_allowed_amount(quantity: Decimal) -> Optional[Decimal]:
    for min_quantity, min_amount in DONATION_AMOUNT_RULES:
        if quantity >= min_quantity:
            return min_amount
    return parse_amount_value(DONATION_AMOUNT_OPTIONS[0])


def get_allowed_amount_options(quantity: Decimal) -> list[str]:
    minimum_allowed_amount = get_minimum_allowed_amount(quantity)
    if minimum_allowed_amount is None:
        return DONATION_AMOUNT_OPTIONS[:]
    return [
        amount
        for amount in DONATION_AMOUNT_OPTIONS
        if (parse_amount_value(amount) or Decimal("0")) >= minimum_allowed_amount
    ]


def is_amount_allowed(amount_text: str, quantity_text: Optional[str] = None) -> bool:
    amount_value = parse_amount_value(amount_text)
    if amount_value is None:
        return True
    quantity = parse_quantity_value(quantity_text) or Decimal("0")
    minimum_allowed_amount = get_minimum_allowed_amount(quantity)
    if minimum_allowed_amount is None:
        return True
    return amount_value >= minimum_allowed_amount


def clamp_quantity_text(text: str, fallback_text: str) -> str:
    quantity = parse_quantity_value(text)
    if quantity is None:
        return (text or "").strip()
    normalized_text = normalize_quantity_text(text)
    if quantity > Decimal(str(MAX_REQUEST_QUOTA)):
        return fallback_text
    return normalized_text
