import os
import re
from software.application.constants import STOP_FORCE_WAIT_SECONDS as _STOP_FORCE_WAIT_SECONDS
from software.core.engine.constants import HTTP_MAX_THREADS as _HTTP_MAX_THREADS
from software.core.config.user_agents import (
    DEFAULT_USER_AGENT as DEFAULT_USER_AGENT,
    USER_AGENT_PRESETS as USER_AGENT_PRESETS,
)
from software.core.text_constants import (
    DEFAULT_FILL_TEXT as DEFAULT_FILL_TEXT,
    WHITESPACE_PATTERN,
)
from software.network.config import (
    AUTH_TRIAL_ENDPOINT,
    CARD_REDEEM_ENDPOINT,
    IP_EXTRACT_ENDPOINT,
    PROXY_HEALTH_CHECK_TIMEOUT,
    PROXY_HEALTH_CHECK_URL,
    PROXY_MAX_PROXIES,
    PROXY_MINUTE_OPTIONS,
    PROXY_POOL_ORDINARY,
    PROXY_POOL_QUALITY,
    PROXY_QUOTA_COST_MAP,
    PROXY_SOURCE_BENEFIT,
    PROXY_SOURCE_CUSTOM,
    PROXY_SOURCE_DEFAULT,
    PROXY_STATUS_TIMEOUT_SECONDS,
    PROXY_TTL_GRACE_SECONDS,
    STATUS_ENDPOINT,
    SUBMISSION_REPORT_ENDPOINT,
)
from software.app.settings_store import (
    CONFIG_DIRECTORY_SETTING_KEY as _CONFIG_DIRECTORY_SETTING_KEY,
    app_settings as _app_settings,
    get_bool_from_qsettings as _get_bool_from_qsettings,
    get_int_from_qsettings as _get_int_from_qsettings,
    get_str_from_qsettings as _get_str_from_qsettings,
)

__all__ = [
    "DEFAULT_USER_AGENT",
    "USER_AGENT_PRESETS",
    "DEFAULT_FILL_TEXT",
    "AUTH_TRIAL_ENDPOINT",
    "CARD_REDEEM_ENDPOINT",
    "IP_EXTRACT_ENDPOINT",
    "PROXY_HEALTH_CHECK_TIMEOUT",
    "PROXY_HEALTH_CHECK_URL",
    "PROXY_MAX_PROXIES",
    "PROXY_MINUTE_OPTIONS",
    "PROXY_POOL_ORDINARY",
    "PROXY_POOL_QUALITY",
    "PROXY_QUOTA_COST_MAP",
    "PROXY_SOURCE_BENEFIT",
    "PROXY_SOURCE_CUSTOM",
    "PROXY_SOURCE_DEFAULT",
    "PROXY_STATUS_TIMEOUT_SECONDS",
    "PROXY_TTL_GRACE_SECONDS",
    "STATUS_ENDPOINT",
    "SUBMISSION_REPORT_ENDPOINT",
]

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


def get_proxy_auth() -> str:

    return os.environ.get("WJX_PROXY_AUTH", "")


HTTP_MAX_THREADS = _HTTP_MAX_THREADS


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

STOP_FORCE_WAIT_SECONDS = _STOP_FORCE_WAIT_SECONDS


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
PRESET_DIMENSIONS = [
    "满意度",
    "信任感",
    "使用意愿",
    "感知价值",
    "服务质量",
    "产品质量",
]
DIMENSION_UNGROUPED = "未分组"


_HTML_SPACE_RE = WHITESPACE_PATTERN
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
    re.compile(
        r"(?:请[选選择擇]?|可选|可選|需选|需選|选择|選擇|勾选|勾選)\s*(\d+)\s*(?:-|－|—|–|~|～|至|到)\s*(\d+)(?:\s*[个項项条])?"
    ),
    re.compile(
        r"至少\s*(\d+)\s*[个項项条]?(?:[^0-9]{0,6})(?:最多|至多|不超过|不超過)\s*(\d+)\s*[个項项条]?"
    ),
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
    re.compile(
        r"(?:select|choose|pick)\s+(?:up\s+to|at\s+most|no\s+more\s+than)\s+(\d+)", re.IGNORECASE
    ),
    re.compile(
        r"(?:up\s+to|at\s+most|no\s+more\s+than)\s+(\d+)\s+(?:options?|choices?|items?)",
        re.IGNORECASE,
    ),
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
