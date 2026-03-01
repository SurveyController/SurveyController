"""UI 辅助函数"""
import logging
import re
from typing import List, Optional, Tuple
from PySide6.QtGui import QColor, QIntValidator
from PySide6.QtWidgets import QLabel
from qfluentwidgets import LineEdit

from wjx.ui.widgets.no_wheel import NoWheelSlider

logger = logging.getLogger(__name__)

_LEADING_NUMBER_RE = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)")
_ANY_NUMBER_RE = re.compile(r"([+-]?\d+(?:\.\d+)?)")
_POSITIVE_RE = re.compile(
    r"(非常好|极好|优秀|满意|同意|符合|喜欢|总是|经常|认可|赞同|推荐|愿意)"
)
_NEGATIVE_RE = re.compile(
    r"(非常差|不满意|不同意|不符合|不喜欢|糟糕|很差|从不|极小|反对|不愿意|差)"
)


def _shorten_text(text: str, limit: int = 80) -> str:
    if not text:
        return ""
    text = str(text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _apply_label_color(label: QLabel, light: str, dark: str) -> None:
    """为标签设置浅色/深色主题颜色。"""
    try:
        getattr(label, 'setTextColor')(QColor(light), QColor(dark))
    except AttributeError as e:
        # setTextColor 方法不存在，使用样式表作为备选方案
        logger.debug(f"setTextColor 方法不可用，使用样式表: {e}")
        style = label.styleSheet() or ""
        style = style.strip()
        if style and not style.endswith(";"):
            style = f"{style};"
        label.setStyleSheet(f"{style}color: {light};")


def _bind_slider_input(slider: NoWheelSlider, edit: LineEdit) -> None:
    """绑定滑块与输入框，避免循环触发。"""
    min_value = int(slider.minimum())
    max_value = int(slider.maximum())
    edit.setValidator(QIntValidator(min_value, max_value, edit))

    def sync_edit(value: int) -> None:
        edit.blockSignals(True)
        edit.setText(str(int(value)))
        edit.blockSignals(False)

    def sync_slider_live(text: str) -> None:
        if not text:
            return
        try:
            value = int(text)
        except ValueError:
            logger.debug(f"滑块输入框数值转换失败: '{text}' 不是有效整数")
            return
        if value < min_value or value > max_value:
            return
        slider.blockSignals(True)
        slider.setValue(value)
        slider.blockSignals(False)

    def sync_slider_final() -> None:
        text = edit.text().strip()
        if not text:
            return
        try:
            value = int(text)
        except ValueError:
            logger.debug(f"滑块输入框最终值转换失败: '{text}' 不是有效整数")
            return
        value = max(min_value, min(max_value, value))
        slider.blockSignals(True)
        slider.setValue(value)
        slider.blockSignals(False)
        edit.blockSignals(True)
        edit.setText(str(value))
        edit.blockSignals(False)

    slider.valueChanged.connect(sync_edit)
    edit.textChanged.connect(sync_slider_live)
    edit.editingFinished.connect(sync_slider_final)


def _extract_number(text: str, prefer_leading: bool = False) -> Optional[float]:
    raw = str(text or "").strip()
    if not raw:
        return None
    match = _LEADING_NUMBER_RE.search(raw)
    if match:
        try:
            return float(match.group(1))
        except Exception:
            return None
    if prefer_leading:
        return None
    match = _ANY_NUMBER_RE.search(raw)
    if not match:
        return None
    try:
        return float(match.group(1))
    except Exception:
        return None


def _score_sentiment(text: str) -> Tuple[int, int, int]:
    """返回（净分, 正向命中数, 负向命中数）。"""
    raw = str(text or "").strip().lower()
    if not raw:
        return (0, 0, 0)
    positive_hits = len(_POSITIVE_RE.findall(raw))
    negative_hits = len(_NEGATIVE_RE.findall(raw))
    return (positive_hits - negative_hits, positive_hits, negative_hits)


def _numeric_reverse_decision(option_texts: List[str]) -> Optional[bool]:
    if len(option_texts) < 2:
        return None

    first = option_texts[0]
    last = option_texts[-1]
    first_leading = _extract_number(first, prefer_leading=True)
    last_leading = _extract_number(last, prefer_leading=True)

    # 纯数字嗅探优先：两端前缀是数字即可直接比较
    if first_leading is not None and last_leading is not None:
        if first_leading > last_leading:
            return True
        if first_leading < last_leading:
            return False

    # 兜底：当全量选项都有数字信息时，再按两端数字比较
    parsed = [_extract_number(text) for text in option_texts]
    if all(value is not None for value in parsed):
        first_num = parsed[0]
        last_num = parsed[-1]
        if first_num is None or last_num is None:
            return None
        if first_num > last_num:
            return True
        if first_num < last_num:
            return False
    return None


def infer_reverse_by_option_texts(option_texts: List[str]) -> bool:
    """根据选项文本自动推断是否为反向题（逆序量表）。"""
    cleaned = [str(text or "").strip() for text in option_texts if str(text or "").strip()]
    if len(cleaned) < 2:
        return False

    # 第一步：数字嗅探（最可靠）
    numeric_decision = _numeric_reverse_decision(cleaned)
    if numeric_decision is not None:
        return numeric_decision

    # 第二步：首尾语义极性判断
    first_score, first_pos, first_neg = _score_sentiment(cleaned[0])
    last_score, last_pos, last_neg = _score_sentiment(cleaned[-1])

    # 首项偏正、末项偏负：逆序
    if first_pos > 0 and last_neg > 0 and first_score > last_score:
        return True
    # 首项偏负、末项偏正：正序
    if first_neg > 0 and last_pos > 0 and first_score < last_score:
        return False

    # 第三步：分差兜底（“首项明显高于末项”）
    score_gap = first_score - last_score
    if score_gap >= 1 and (first_pos > 0 or last_neg > 0):
        return True
    if score_gap <= -1 and (last_pos > 0 or first_neg > 0):
        return False

    return False
