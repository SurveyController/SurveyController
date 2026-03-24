"""软件层 IO 能力。"""

from software.io.config import (
    RuntimeConfig,
    _sanitize_filename,
    build_default_config_filename,
    load_config,
    save_config,
)
from software.io.markdown import strip_markdown
from software.io.qr import decode_qrcode
from software.io.reports import get_usage_summary

__all__ = [
    "RuntimeConfig",
    "_sanitize_filename",
    "build_default_config_filename",
    "decode_qrcode",
    "get_usage_summary",
    "load_config",
    "save_config",
    "strip_markdown",
]


