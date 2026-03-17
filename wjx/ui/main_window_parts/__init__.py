"""MainWindow 拆分模块。"""

from .dialogs import MainWindowDialogsMixin
from .lazy_pages import MainWindowLazyPagesMixin
from .update import MainWindowUpdateMixin

__all__ = [
    "MainWindowDialogsMixin",
    "MainWindowLazyPagesMixin",
    "MainWindowUpdateMixin",
]
