import html as html_lib
import logging
import re
from typing import Any, List, Optional

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

from software.core.questions.utils import _normalize_question_type_code
from software.logging.log_utils import log_suppressed_exception
from software.providers.match_utils import normalize_match_text

from .regexes import WJX_MODLEN_CLASS_RE, WJX_QUESTION_PREFIX_RE, WJX_TITLE_SUFFIX_RE

_TEXT_INPUT_ALLOWED_TYPES = {"text", "tel", "email", "number", "search", "url", "password"}
_KNOWN_NON_TEXT_QUESTION_TYPES = {"3", "4", "5", "6", "7", "8", "11", "12", "13", "15", "16", "17"}
_SELECT_PLACEHOLDER_PREFIXES = ("请选择", "请先选择")
_LOCATION_VERIFY_MARKERS = ("地图", "省市", "省份", "城市", "地区", "map", "city", "province", "area")
_DISPLAY_SPACE_RE = re.compile(r"\s+")


def _normalize_html_text(value: Optional[str]) -> str:
    if value is None:
        return ""
    try:
        text = str(value)
    except Exception:
        return ""
    if not text:
        return ""
    text = html_lib.unescape(text)
    text = _DISPLAY_SPACE_RE.sub(" ", text)
    return text.strip()


def _extract_prefixed_question_number(raw_title: Any) -> Optional[int]:
    text = normalize_match_text(raw_title)
    if not text:
        return None
    match = WJX_QUESTION_PREFIX_RE.match(text)
    if not match:
        return None
    number_text = (
        match.group("cn_num")
        or match.group("q_num")
        or match.group("plain_num")
        or ""
    )
    try:
        number = int(number_text)
    except Exception:
        return None
    return number if number > 0 else None


def _text_looks_like_select_placeholder(value: Any) -> bool:
    text = _normalize_html_text(str(value or ""))
    if not text:
        return False
    compact_text = text.replace(" ", "")
    return any(compact_text.startswith(prefix) for prefix in _SELECT_PLACEHOLDER_PREFIXES)


def _is_select_placeholder_option(index: int, value: Any, text: Any) -> bool:
    if index != 0:
        return False
    normalized_value = _normalize_html_text(str(value or ""))
    normalized_text = _normalize_html_text(str(text or ""))
    if not normalized_text:
        return True
    if normalized_value in {"", "0", "-1", "-2"}:
        return True
    return _text_looks_like_select_placeholder(normalized_text)


def _input_looks_like_location(input_element) -> bool:
    if input_element is None:
        return False
    try:
        verify_value = str(input_element.get("verify") or "").strip()
    except Exception:
        verify_value = ""
    try:
        onclick_value = str(input_element.get("onclick") or "").strip().lower()
    except Exception:
        onclick_value = ""
    if not verify_value and "opencitybox" not in onclick_value:
        return False
    if any(marker in verify_value for marker in _LOCATION_VERIFY_MARKERS if marker in {"地图", "省市", "省份", "城市", "地区"}):
        return True
    return "opencitybox" in onclick_value


def _soup_question_is_required(question_div) -> bool:
    if question_div is None:
        return False
    try:
        if str(question_div.get("req") or "").strip() in {"1", "true", "True"}:
            return True
        if str(question_div.get("required") or "").strip().lower() in {"1", "true", "required"}:
            return True
        if str(question_div.get("must") or "").strip() in {"1", "true", "True"}:
            return True
        if str(question_div.get("wjxreq") or "").strip() in {"1", "true", "True"}:
            return True
        if str(question_div.get("aria-required") or "").strip().lower() == "true":
            return True
    except Exception:
        pass

    marker_selectors = (
        ".req",
        ".required",
        ".must",
        ".star",
        ".red",
        ".wjxreq",
        "[aria-required='true']",
    )
    for selector in marker_selectors:
        try:
            if question_div.select_one(selector):
                return True
        except Exception:
            continue

    heading_text = _extract_display_heading_text(question_div)
    normalized_heading = _normalize_html_text(heading_text)
    if normalized_heading.startswith("*"):
        return True
    if "必答" in normalized_heading:
        return True

    try:
        text = _normalize_html_text(question_div.get_text(" ", strip=True))
    except Exception:
        text = normalized_heading
    if text.startswith("*"):
        return True
    return False

def extract_survey_title_from_html(html: str) -> Optional[str]:
    


    if not BeautifulSoup:
        return None
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return None

    selectors = [
        "#divTitle h1",
        "#divTitle",
        ".surveytitle",
        ".survey-title",
        ".surveyTitle",
        ".wjdcTitle",
        ".htitle",
        ".topic_tit",
        "#htitle",
        "#lbTitle",
    ]
    candidates: List[str] = []
    for selector in selectors:
        element = soup.select_one(selector)
        if element:
            text = _normalize_html_text(element.get_text(" ", strip=True))
            if text:
                candidates.append(text)

    if not candidates:
        for tag_name in ("h1", "h2"):
            header = soup.find(tag_name)
            if header:
                text = _normalize_html_text(header.get_text(" ", strip=True))
                if text:
                    candidates.append(text)
                if candidates:
                    break

    title_tag = soup.find("title")
    if title_tag:
        text = _normalize_html_text(title_tag.get_text(" ", strip=True))
        if text:
            candidates.append(text)

    for raw in candidates:
        cleaned = raw
        cleaned = WJX_TITLE_SUFFIX_RE.sub("", cleaned)
        cleaned = cleaned.strip(" -_|")
        if cleaned:
            return cleaned
    return None

def _extract_question_number_from_div(question_div) -> Optional[int]:
    topic_attr = question_div.get("topic")
    if topic_attr and topic_attr.isdigit():
        return int(topic_attr)
    id_attr = question_div.get("id") or ""
    match = re.search(r"div(\d+)", id_attr)
    if match:
        return int(match.group(1))
    return None

def _cleanup_question_title(raw_title: str) -> str:
    title = _normalize_html_text(raw_title)
    if not title:
        return ""
    title = WJX_QUESTION_PREFIX_RE.sub("", title)
    title = title.replace("【单选题】", "").replace("【多选题】", "")
    return title.strip()

def _extract_display_question_number(raw_title: Any) -> Optional[int]:
    return _extract_prefixed_question_number(raw_title)

def _extract_display_heading_text(question_div) -> str:
    if question_div is None:
        return ""
    try:
        field_label = question_div.find(class_="field-label")
    except Exception:
        field_label = None
    if field_label is not None:
        parts: List[str] = []
        for class_name in ("topicnumber", "topichtml"):
            try:
                element = field_label.find(class_=class_name)
            except Exception:
                element = None
            if element is None:
                continue
            try:
                text = element.get_text(" ", strip=True)
            except Exception:
                text = ""
            text = _normalize_html_text(text)
            if text:
                parts.append(text)
        if parts:
            return _normalize_html_text(" ".join(parts))
    for class_name in ("topichtml", "field-label", "qtypetip"):
        try:
            title_element = question_div.find(class_=class_name)
        except Exception:
            title_element = None
        if not title_element:
            continue
        try:
            text = title_element.get_text(" ", strip=True)
        except Exception:
            text = ""
        text = _normalize_html_text(text)
        if text:
            return text
    try:
        blockquote = question_div.find("blockquote")
    except Exception:
        blockquote = None
    if blockquote is not None:
        try:
            text = blockquote.get_text(" ", strip=True)
        except Exception:
            text = ""
        text = _normalize_html_text(text)
        if text:
            return text
    try:
        text = question_div.get_text(" ", strip=True)
    except Exception:
        text = ""
    return _normalize_html_text(text)

def _count_text_inputs_in_soup(question_div) -> int:
    try:
        candidates = question_div.find_all(["input", "textarea", "span", "div"])
    except Exception as exc:
        log_suppressed_exception("survey.parser._count_text_inputs candidates", exc, level=logging.ERROR)
        return 0
    count = 0
    for cand in candidates:
        try:
            tag_name = (cand.name or "").lower()
        except Exception:
            tag_name = ""
        input_type = ""
        try:
            input_type = (cand.get("type") or "").lower()
        except Exception:
            input_type = ""
        style_text = ""
        try:
            style_text = (cand.get("style") or "").lower()
        except Exception:
            style_text = ""
        try:
            class_attr = cand.get("class") or []
            if isinstance(class_attr, str):
                class_text = class_attr.lower()
            else:
                class_text = " ".join(class_attr).lower()
        except Exception:
            class_text = ""
        is_textcont = "textcont" in class_text or "textedit" in class_text

        if input_type == "hidden" or "display:none" in style_text or "visibility:hidden" in style_text:
            continue
        if tag_name == "input" and _input_looks_like_location(cand):
            continue

        if tag_name == "input":
            try:
                sibling = cand.find_next_sibling()
                sibling_classes = sibling.get("class") if sibling else None
                if sibling_classes and any("textedit" in cls.lower() for cls in sibling_classes):
                    continue
            except Exception as exc:
                log_suppressed_exception("survey.parser._count_text_inputs sibling", exc, level=logging.ERROR)
        if tag_name == "textarea" or (tag_name == "input" and input_type in _TEXT_INPUT_ALLOWED_TYPES):
            count += 1
            continue
        try:
            contenteditable = (cand.get("contenteditable") or "").lower() == "true"
        except Exception:
            contenteditable = False
        if (contenteditable or is_textcont) and tag_name in {"span", "div"}:
            count += 1
    return count

def _extract_text_input_labels(question_div) -> List[str]:
    
    labels = []

    def _label_before_node(node) -> str:
        parts: List[str] = []
        current = getattr(node, "previous_sibling", None)
        while current is not None:
            name = str(getattr(current, "name", "") or "").lower()
            if name in {"input", "textarea", "label", "span"}:
                if name == "input":
                    current = getattr(current, "previous_sibling", None)
                    continue
                break
            if name in {"br"}:
                break
            text = _normalize_html_text(current.get_text(" ", strip=True) if hasattr(current, "get_text") else str(current))
            if text:
                parts.append(text)
            current = getattr(current, "previous_sibling", None)
        return _normalize_html_text(" ".join(reversed(parts))).rstrip("：:").strip()

    try:
        candidates = question_div.find_all(["input", "textarea", "span", "div"])
    except Exception as exc:
        log_suppressed_exception("survey.parser._extract_text_input_labels candidates", exc, level=logging.ERROR)
        return labels

    for cand in candidates:
        try:
            tag_name = (cand.name or "").lower()
            input_type = (cand.get("type") or "").lower()
            style_text = (cand.get("style") or "").lower()
            class_attr = cand.get("class") or []
            class_text = " ".join(class_attr).lower() if isinstance(class_attr, list) else str(class_attr).lower()
            is_textcont = "textcont" in class_text or "textedit" in class_text

            if input_type == "hidden" or "display:none" in style_text or "visibility:hidden" in style_text:
                continue
            if tag_name == "input" and _input_looks_like_location(cand):
                continue

            if tag_name == "input":
                sibling = cand.find_next_sibling()
                if sibling and sibling.get("class") and any("textedit" in cls.lower() for cls in sibling.get("class")):
                    continue

            is_text_input = False
            if tag_name == "textarea" or (tag_name == "input" and input_type in _TEXT_INPUT_ALLOWED_TYPES):
                is_text_input = True
            elif (cand.get("contenteditable") == "true" or is_textcont) and tag_name in {"span", "div"}:
                is_text_input = True

            if is_text_input:
                label = cand.get("placeholder") or cand.get("aria-label") or cand.get("data-label") or ""
                if not label:
                    prev = cand.find_previous_sibling(string=True)
                    if prev:
                        label = prev.strip().rstrip("：:").strip()
                if not label:
                    label = _label_before_node(cand)
                if not label and is_textcont:
                    parent = cand.find_parent()
                    if parent is not None:
                        label = _label_before_node(parent)
                labels.append(label if label else f"填空{len(labels) + 1}")
        except Exception as exc:
            log_suppressed_exception("survey.parser._extract_text_input_labels candidate", exc, level=logging.ERROR)
            continue

    return labels

def _soup_question_looks_like_description(question_div, type_code: str) -> bool:
    
    if question_div is None:
        return False
    try:
        relation = str(question_div.get("relation") or "").strip()
        style_text = str(question_div.get("style") or "").lower()
        is_unreachable_placeholder = (
            relation == "-1"
            and "display:none" in style_text.replace(" ", "")
            and not _soup_question_is_required(question_div)
        )
        if is_unreachable_placeholder:
            return True
    except Exception:
        pass
    
    if type_code not in {"3", "4"}:
        return False
    try:
        
        choice_inputs = question_div.find_all(
            "input", attrs={"type": lambda v: v and v.lower() in ("radio", "checkbox")}
        )
        if choice_inputs:
            return False
        
        has_control_group = bool(question_div.select_one(".ui-controlgroup"))
        if has_control_group:
            return False
        
        has_jq_controls = bool(question_div.select_one(".jqradio, .jqcheck"))
        if has_jq_controls:
            return False
    except Exception:
        return False
    
    return True

def _soup_question_looks_like_reorder(question_div) -> bool:
    
    if question_div is None:
        return False
    try:
        if question_div.select_one(".sortnum, .sortnum-sel, .order-number, .order-index"):
            return True
    except Exception as exc:
        log_suppressed_exception("survey.parser._soup_question_looks_like_reorder quick", exc, level=logging.ERROR)
    try:
        has_list_items = bool(question_div.select("ul li, ol li"))
        if not has_list_items:
            return False
        has_sort_signature = bool(
            question_div.select(".ui-sortable, .ui-sortable-handle, [class*='sort']")
        )
        return has_sort_signature
    except Exception:
        return False

def _soup_question_looks_like_numeric_scale(question_div) -> bool:
    
    if question_div is None:
        return False
    try:
        anchors = question_div.select("ul[tp='d'] li a, .scale-rating ul li a, .scale-rating a[val]")
    except Exception:
        anchors = []
    texts: List[str] = []
    for anchor in anchors:
        text = _normalize_html_text(anchor.get_text(" ", strip=True))
        if not text:
            try:
                text = _normalize_html_text(
                    anchor.get("title")
                    or anchor.get("aria-label")
                    or anchor.get("val")
                    or anchor.get("value")
                    or anchor.get("dval")
                    or anchor.get("data-value")
                    or anchor.get("data-val")
                    or ""
                )
            except Exception:
                text = ""
        if text:
            texts.append(text)
    if not texts:
        return False
    numeric_count = sum(1 for t in texts if re.fullmatch(r"\d{1,2}", t))
    has_scale_title = False
    try:
        has_scale_title = bool(question_div.select_one(".scaleTitle, .scaleTitle_frist, .scaleTitle_last, .scaleTitleFirst, .scaleTitleLast"))
    except Exception:
        has_scale_title = False
    total = len(texts)
    return total >= 5 and numeric_count >= max(3, int(total * 0.7)) and (total >= 9 or has_scale_title)

def _soup_question_looks_like_rating(question_div) -> bool:
    
    if question_div is None:
        return False
    
    if _soup_question_looks_like_numeric_scale(question_div):
        return False
    has_rate_icon = False
    try:
        has_rate_icon = bool(question_div.select_one("a.rate-off, a.rate-on, .rate-off, .rate-on"))
    except Exception:
        has_rate_icon = False
    has_tag_wrap = False
    try:
        has_tag_wrap = bool(question_div.find(class_="evaluateTagWrap"))
    except Exception:
        has_tag_wrap = False
    has_iconfont = False
    try:
        has_iconfont = bool(question_div.select_one(".scale-rating .iconfontNew, .iconfontNew"))
    except Exception:
        has_iconfont = False

    
    if has_tag_wrap:
        return True
    if has_rate_icon or has_iconfont:
        return True
    return False

def _extract_rating_option_count(question_div) -> int:
    
    if question_div is None:
        return 0
    try:
        rating_list = question_div.find("ul", class_=WJX_MODLEN_CLASS_RE)
    except Exception:
        rating_list = None
    if rating_list:
        try:
            class_attr = rating_list.get("class") or []
            for cls in class_attr:
                match = WJX_MODLEN_CLASS_RE.search(str(cls))
                if match:
                    return int(match.group("count"))
        except Exception as exc:
            log_suppressed_exception("survey.parser._extract_rating_option_count modlen", exc, level=logging.ERROR)
    try:
        options = question_div.select(".scale-rating ul li")
        if options:
            return len(options)
    except Exception as exc:
        log_suppressed_exception("survey.parser._extract_rating_option_count scale-rating", exc, level=logging.ERROR)
    try:
        options = question_div.select("a.rate-off, a.rate-on")
        if options:
            return len(options)
    except Exception as exc:
        log_suppressed_exception("survey.parser._extract_rating_option_count rate-off", exc, level=logging.ERROR)
    return 0

def _should_mark_as_multi_text(
    type_code: Any,
    option_count: int,
    text_input_count: int,
    is_location: bool,
    has_gapfill: bool = False,
    has_slider_matrix: bool = False,
) -> bool:
    if is_location:
        return False
    if has_slider_matrix:
        return False
    normalized = _normalize_question_type_code(type_code)
    if normalized == "9" and has_gapfill:
        return True
    if text_input_count < 2:
        return False
    if normalized in ("1", "2", "9"):
        return True
    if normalized in _KNOWN_NON_TEXT_QUESTION_TYPES:
        return False
    if (option_count or 0) == 0:
        return True
    return (option_count or 0) <= 1 and text_input_count >= 2
