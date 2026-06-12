from __future__ import annotations

import os
from typing import Any

from PySide6.QtCore import QCoreApplication, QSettings

_SETTINGS_ORG = "SurveyController"
_SETTINGS_APP = "Settings"
_SETTINGS_DOMAIN = "surveycontroller.app"
_SETTINGS_FILE_ENV = "SURVEYCONTROLLER_QSETTINGS_FILE"
CONFIG_DIRECTORY_SETTING_KEY = "config_directory"


def configure_qt_application_metadata() -> None:
    
    if not QCoreApplication.organizationName():
        QCoreApplication.setOrganizationName(_SETTINGS_ORG)
    if not QCoreApplication.organizationDomain():
        QCoreApplication.setOrganizationDomain(_SETTINGS_DOMAIN)
    if not QCoreApplication.applicationName():
        QCoreApplication.setApplicationName(_SETTINGS_APP)


def app_settings() -> QSettings:
    
    isolated_settings_file = os.environ.get(_SETTINGS_FILE_ENV)
    if isolated_settings_file:
        return QSettings(isolated_settings_file, QSettings.Format.IniFormat)
    configure_qt_application_metadata()
    return QSettings(_SETTINGS_ORG, _SETTINGS_APP)


def get_bool_from_qsettings(value: Any, default: bool = False) -> bool:
    
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"true", "1", "yes", "on"}
    return bool(value)


def get_int_from_qsettings(
    value: Any,
    default: int = 0,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    
    try:
        if value is None or value == "":
            result = int(default)
        else:
            result = int(value)
    except (TypeError, ValueError):
        result = int(default)
    if minimum is not None:
        result = max(int(minimum), result)
    if maximum is not None:
        result = min(int(maximum), result)
    return result


def get_str_from_qsettings(value: Any, default: str = "") -> str:
    
    if value is None:
        return default
    text = str(value).strip()
    return text or default

