import os
import re
import sys
from typing import Any, cast

from software.app.settings_store import (
    CONFIG_DIRECTORY_SETTING_KEY as _CONFIG_DIRECTORY_SETTING_KEY,
    app_settings as _app_settings,
    get_bool_from_qsettings as _get_bool_from_qsettings,
    get_int_from_qsettings as _get_int_from_qsettings,
    get_str_from_qsettings as _get_str_from_qsettings,
)

app_settings = _app_settings
get_bool_from_qsettings = _get_bool_from_qsettings
get_int_from_qsettings = _get_int_from_qsettings
get_str_from_qsettings = _get_str_from_qsettings

CONFIG_DIRECTORY_SETTING_KEY = _CONFIG_DIRECTORY_SETTING_KEY
NAVIGATION_TEXT_VISIBLE_SETTING_KEY = "navigation_selected_text_visible"
AUTO_SAVE_LOGS_SETTING_KEY = "auto_save_logs"
AUTO_SAVE_LOG_RETENTION_COUNT_SETTING_KEY = "auto_save_log_retention_count"
TASK_RESULT_SYSTEM_NOTIFICATION_SETTING_KEY = "task_result_system_notification"
TASK_RESULT_WINDOWS_NOTIFICATION_SETTING_KEY = TASK_RESULT_SYSTEM_NOTIFICATION_SETTING_KEY
SUBMISSION_REPORT_TELEMETRY_SETTING_KEY = "submission_report_telemetry"
DEFAULT_AUTO_SAVE_LOGS = True
DEFAULT_AUTO_SAVE_LOG_RETENTION_COUNT = 10
AUTO_SAVE_LOG_RETENTION_OPTIONS = (3, 5, 10, 20, 30, 50)

def _read_windows_env_var(key: str) -> str:
    if sys.platform != "win32":
        return ""
    try:
        import winreg
    except Exception:
        return ""
    registry = cast(Any, winreg)
    try:
        with registry.OpenKey(registry.HKEY_CURRENT_USER, "Environment") as reg_key:
            value, _ = registry.QueryValueEx(reg_key, key)
    except FileNotFoundError:
        return ""
    except Exception:
        return ""
    if value is None:
        return ""
    try:
        return str(value).strip()
    except Exception:
        return ""


def _resolve_env_value(key: str, default: str) -> str:
    env_value = os.environ.get(key)
    if env_value:
        return env_value
    registry_value = _read_windows_env_var(key)
    if registry_value:
        return registry_value
    return default


def get_proxy_auth() -> str:
    
    return os.environ.get("WJX_PROXY_AUTH", "")
_DEFAULT_CONTACT_API = "https://bot.hungrym0.com"
_DEFAULT_AUTH_TRIAL = "https://api-wjx.hungrym0.com/api/auth/trial"
_DEFAULT_AUTH_BONUS_CLAIM = "https://api-wjx.hungrym0.com/api/bonus"
_DEFAULT_CARD_REDEEM_ENDPOINT = "https://api-wjx.hungrym0.com/api/cards/redeem"
_DEFAULT_IP_EXTRACT_ENDPOINT = "https://api-wjx.hungrym0.com/api/ip/extract"
_DEFAULT_SUBMISSION_REPORT_ENDPOINT = "https://api-wjx.hungrym0.com/api/submission/report"
_DEFAULT_AI_FREE_ENDPOINT = "https://api-wjx.hungrym0.com/api/ai/free"
_DEFAULT_STATUS_ENDPOINT = "https://api-wjx.hungrym0.com/api/status"



HTTP_MAX_THREADS = 64


USER_AGENT_PRESETS = {
    "pc_web": {
        "label": "电脑网页端",
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    },
    "mobile_android": {
        "label": "安卓手机浏览器",
        "ua": "Mozilla/5.0 (Linux; Android 16; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36",
    },
    "wechat_android": {
        "label": "安卓微信端",
        "ua": "Mozilla/5.0 (Linux; Android 16; Pixel 8 Build/BP22.250124.009; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/121.0.0.0 Mobile Safari/537.36 MicroMessenger/8.0.43.2460(0x28002B3B) Process/appbrand0 WeChat/arm64 Weixin NetType/WIFI Language/zh_CN ABI/arm64",
    },
}


DEFAULT_USER_AGENT = USER_AGENT_PRESETS["pc_web"]["ua"]


DEFAULT_HTTP_HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "close",
}


LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
LOG_BUFFER_CAPACITY = 2000
LOG_DIR_NAME = "logs"
LOG_REFRESH_INTERVAL_MS = 500


APP_ICON_RELATIVE_PATH = "icon.ico"



SUBMIT_INITIAL_DELAY = 0.35

SUBMIT_CLICK_SETTLE_DELAY = 0.25

POST_SUBMIT_URL_MAX_WAIT = 0.8

POST_SUBMIT_URL_POLL_INTERVAL = 0.05

POST_SUBMIT_CLOSE_GRACE_SECONDS = 0.8

STOP_FORCE_WAIT_SECONDS = 0.3


PROXY_MAX_PROXIES = 80
PROXY_HEALTH_CHECK_URL = "https://www.wjx.cn"
PROXY_HEALTH_CHECK_TIMEOUT = 15
PROXY_STATUS_TIMEOUT_SECONDS = 5
PROXY_TTL_GRACE_SECONDS = 20
PROXY_MINUTE_OPTIONS = (1, 3, 5, 10, 15, 30)
PROXY_QUOTA_COST_MAP = {
    1: 1,
    3: 2,
    5: 3,
    10: 5,
    15: 8,
    30: 20,
}

PROXY_SOURCE_DEFAULT = "default"
PROXY_SOURCE_BENEFIT = "benefit"
PROXY_SOURCE_CUSTOM = "custom"

PROXY_POOL_ORDINARY = "ordinary"
PROXY_POOL_QUALITY = "quality"

CONTACT_API_URL = _resolve_env_value("CONTACT_API_URL", _DEFAULT_CONTACT_API)
AUTH_TRIAL_ENDPOINT = _resolve_env_value("AUTH_TRIAL_ENDPOINT", _DEFAULT_AUTH_TRIAL)
AUTH_BONUS_CLAIM_ENDPOINT = _resolve_env_value("AUTH_BONUS_CLAIM_ENDPOINT", _DEFAULT_AUTH_BONUS_CLAIM)
CARD_REDEEM_ENDPOINT = _resolve_env_value("CARD_REDEEM_ENDPOINT", _DEFAULT_CARD_REDEEM_ENDPOINT)
IP_EXTRACT_ENDPOINT = _resolve_env_value("IP_EXTRACT_ENDPOINT", _DEFAULT_IP_EXTRACT_ENDPOINT)
SUBMISSION_REPORT_ENDPOINT = _resolve_env_value("SUBMISSION_REPORT_ENDPOINT", _DEFAULT_SUBMISSION_REPORT_ENDPOINT)
AI_FREE_ENDPOINT = _resolve_env_value("AI_FREE_ENDPOINT", _DEFAULT_AI_FREE_ENDPOINT)
STATUS_ENDPOINT = _resolve_env_value("STATUS_ENDPOINT", _DEFAULT_STATUS_ENDPOINT)

QUESTION_TYPE_LABELS = {
    "radio": "单选题",
    "checkbox": "多选题",
    "textarea": "简答题",
    "input": "填空题",
    "dropdown": "下拉题",
    "slider": "滑块题",
    "order": "排序题",
    "score": "评价题",
    "single": "单选题",
    "multiple": "多选题",
    "matrix": "矩阵题",
    "scale": "量表题",
    "text": "填空题",
    "multi_text": "多项填空题",
    "location": "地区题",
}
LOCATION_QUESTION_LABEL = "位置题"
DEFAULT_FILL_TEXT = "无"  



PRESET_DIMENSIONS = [
    "满意度",
    "信任感",
    "使用意愿",
    "感知价值",
    "服务质量",
    "产品质量",
]
DIMENSION_UNGROUPED = "未分组"  


_HTML_SPACE_RE = re.compile(r"\s+")
_LNGLAT_PATTERN = re.compile(r"^\s*-?\d+(?:\.\d+)?\s*,\s*-?\d+(?:\.\d+)?\s*$")
_INVALID_FILENAME_CHARS_RE = re.compile(r'[\\/:*?"<>|]+')


_MULTI_LIMIT_ATTRIBUTE_NAMES = (
    "max",
    "maxvalue",
    "maxValue",
    "maxcount",
    "maxCount",
    "maxchoice",
    "maxChoice",
    "maxselect",
    "maxSelect",
    "selectmax",
    "selectMax",
    "maxsel",
    "maxSel",
    "maxnum",
    "maxNum",
    "maxlimit",
    "maxLimit",
    "data-max",
    "data-maxvalue",
    "data-maxcount",
    "data-maxchoice",
    "data-maxselect",
    "data-selectmax",
)

_MULTI_LIMIT_VALUE_KEYS = (
    "max",
    "maxvalue",
    "maxcount",
    "maxchoice",
    "maxselect",
    "selectmax",
)

_MULTI_LIMIT_VALUE_KEYSET = {name.lower() for name in _MULTI_LIMIT_VALUE_KEYS}

_MULTI_MIN_LIMIT_ATTRIBUTE_NAMES = (
    "min",
    "minvalue",
    "minValue",
    "mincount",
    "minCount",
    "minchoice",
    "minChoice",
    "minselect",
    "minSelect",
    "selectmin",
    "selectMin",
    "minsel",
    "minSel",
    "minnum",
    "minNum",
    "minlimit",
    "minLimit",
    "data-min",
    "data-minvalue",
    "data-mincount",
    "data-minchoice",
    "data-minselect",
    "data-selectmin",
)

_MULTI_MIN_LIMIT_VALUE_KEYS = (
    "min",
    "minvalue",
    "mincount",
    "minchoice",
    "minselect",
    "selectmin",
    "minlimit",
)

_MULTI_MIN_LIMIT_VALUE_KEYSET = {name.lower() for name in _MULTI_MIN_LIMIT_VALUE_KEYS}

_SELECTION_KEYWORDS_CN = ("选", "選", "选择", "多选", "复选")
_SELECTION_KEYWORDS_EN = ("option", "options", "choice", "choices", "select", "choose")

_CHINESE_MULTI_LIMIT_PATTERNS = (
    re.compile(r"(?:最多|至多|不超过|不超過)\s*(?:选|選|选择|選擇)?\s*(\d+)\s*[个項项]?"),
    re.compile(r"(?:限选|限選)\s*(\d+)\s*[个項项条]?"),
)

_CHINESE_MULTI_RANGE_PATTERNS = (
    re.compile(r"(?:请[选選择擇]?|可选|可選|需选|需選|选择|選擇|勾选|勾選)\s*(\d+)\s*(?:-|－|—|–|~|～|至|到)\s*(\d+)(?:\s*[个項项条])?"),
    re.compile(r"至少\s*(\d+)\s*[个項项条]?(?:[^0-9]{0,6})(?:最多|至多|不超过|不超過)\s*(\d+)\s*[个項项条]?"),
    re.compile(r"(?:限选|限選)\s*(\d+)\s*(?:-|－|—|–|~|～|至|到)\s*(\d+)(?:\s*[个項项条])?"),
)

_CHINESE_MULTI_EXACT_PATTERNS = (
    re.compile(r"(?:请)?(?:选|選|选择|選擇|勾选|勾選)\s*(\d+)\s*[个項项条]"),
    re.compile(r"(?:必须|需|需要)\s*(?:选|選|选择|選擇|勾选|勾選)\s*(\d+)\s*[个項项条]"),
)

_CHINESE_MULTI_MIN_PATTERNS = (
    re.compile(r"(?:至少|最少|不少于)\s*(?:选|選|选择|選擇)?\s*(\d+)\s*[个項项条]"),
)

_ENGLISH_MULTI_LIMIT_PATTERNS = (
    re.compile(r"(?:select|choose|pick)\s+(?:up\s+to|at\s+most|no\s+more\s+than)\s+(\d+)", re.IGNORECASE),
    re.compile(r"(?:up\s+to|at\s+most|no\s+more\s+than)\s+(\d+)\s+(?:options?|choices?|items?)", re.IGNORECASE),
)

_ENGLISH_MULTI_RANGE_PATTERNS = (
    re.compile(r"(?:select|choose|pick)\s*(\d+)\s*(?:-|–|—|~|～|to)\s*(\d+)", re.IGNORECASE),
    re.compile(r"(?:select|choose)\s+between\s+(\d+)\s+and\s+(\d+)", re.IGNORECASE),
)

_ENGLISH_MULTI_EXACT_PATTERNS = (
    re.compile(r"(?:select|choose|pick)\s+(\d+)\s+(?:options?|choices?|items?)", re.IGNORECASE),
    re.compile(r"(?:must|need\s+to|please)\s+(?:select|choose|pick)\s+(\d+)", re.IGNORECASE),
)

_ENGLISH_MULTI_MIN_PATTERNS = (
    re.compile(r"(?:at\s+least|min(?:imum)?\s*)\s*(\d+)", re.IGNORECASE),
)


VELOPACK_FEED_URL = _resolve_env_value(
    "SURVEYCONTROLLER_VELOPACK_FEED_URL",
    "https://dl.hungrym0.com/surveycontroller/win/stable/" if sys.platform == "win32" else "",
)
VELOPACK_CHANNEL = _resolve_env_value("SURVEYCONTROLLER_VELOPACK_CHANNEL", "stable" if sys.platform == "win32" else "")
