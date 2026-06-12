from __future__ import annotations

from typing import Optional

import os

from PySide6.QtCore import Qt, QTimer, QSize, QThread
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QWidget
from qfluentwidgets import (
    CaptionLabel,
    IndeterminateProgressBar,
    SplashScreen,
    TitleLabel,
    isDarkTheme,
)

from software.app.runtime_paths import get_resource_path
from software.app.version import __VERSION__

__all__ = ["BootSplash", "create_boot_splash", "finish_boot_splash"]


class BootSplash:
    

    def __init__(self, window: QWidget):
        self.window = window
        self._boot_icon = self._resolve_boot_icon(window)
        self.splash_screen = SplashScreen(self._boot_icon, window)
        self.splash_screen.setIconSize(QSize(64, 64))
        self._finish_timer: Optional[QTimer] = None
        self._icon_size = 64
        self._scale = 1.0

        
        is_dark = isDarkTheme()
        self._title_color = "#ffffff" if is_dark else "#1f2937"
        self._version_color = "#a1a1aa" if is_dark else "#6b7280"
        self._badge_bg = "rgba(255, 255, 255, 0.1)" if is_dark else "rgba(0, 0, 0, 0.08)"

        
        self.title_label = TitleLabel(self.splash_screen)
        self.title_label.setText("SurveyController")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        
        self.version_label = CaptionLabel(self.splash_screen)
        self.version_label.setText(f"v{__VERSION__}")
        self.version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        
        self.progress_bar = IndeterminateProgressBar(self.splash_screen)
        self.progress_bar.start()
        self.title_label.show()
        self.version_label.show()
        self.progress_bar.show()
        self.update_layout(window.width(), window.height())
        self.splash_screen.raise_()

    def _resolve_boot_icon(self, window: QWidget) -> QIcon:
        
        icon_path = get_resource_path(os.path.join("assets", "icon.png"))
        if os.path.exists(icon_path):
            return QIcon(icon_path)
        return window.windowIcon()

    def _apply_scale(self, width: int, height: int):
        
        base_width, base_height = 1180, 780
        width = max(width, 900)
        height = max(height, 640)

        scale = min(width / base_width, height / base_height)
        self._scale = max(1.0, min(scale, 1.45))
        self._icon_size = int(220 * self._scale)
        self.splash_screen.setIconSize(QSize(self._icon_size, self._icon_size))

        title_font_size = int(28 * self._scale)
        version_font_size = int(14 * self._scale)
        badge_radius = max(12, int(13 * self._scale))
        pad_vertical = max(4, int(4 * self._scale))
        pad_horizontal = max(12, int(14 * self._scale))

        self.title_label.setStyleSheet(
            f"""
            color: {self._title_color};
            font-size: {title_font_size}px;
            font-weight: bold;
            font-family: 'Microsoft YaHei UI';
            """
        )
        self.title_label.adjustSize()

        self.version_label.setStyleSheet(
            f"""
            color: {self._version_color};
            font-size: {version_font_size}px;
            font-family: 'Microsoft YaHei UI';
            background-color: {self._badge_bg};
            border-radius: {badge_radius}px;
            padding: {pad_vertical}px {pad_horizontal}px;
            """
        )
        self.version_label.adjustSize()

    def update_layout(self, width: int, height: int):
        
        self.splash_screen.resize(width, height)
        self._apply_scale(width, height)

        
        icon_bottom = height // 2 + self._icon_size // 2 + int(18 * self._scale)
        title_width = self.title_label.width()
        self.title_label.move((width - title_width) // 2, icon_bottom)

        
        title_bottom = icon_bottom + self.title_label.height() + int(10 * self._scale)
        badge_width = self.version_label.width()
        self.version_label.move((width - badge_width) // 2, title_bottom)

        
        bar_width = int(max(340, min(width * 0.34, 520)))
        bar_height = max(4, int(5 * self._scale))
        self.progress_bar.setGeometry(
            (width - bar_width) // 2,
            height - int(82 * self._scale),
            bar_width,
            bar_height,
        )

    def finish(self):
        
        self._stop_finish_timer()
        self._stop_progress_bar()
        try:
            self.splash_screen.finish()
        except Exception:
            pass

    def cleanup(self):
        
        self._stop_finish_timer()
        self._stop_progress_bar()

    def _stop_finish_timer(self) -> None:
        timer = self._finish_timer
        self._finish_timer = None
        if timer is None:
            return
        try:
            if timer.thread() is QThread.currentThread() and timer.isActive():
                timer.stop()
        except Exception:
            pass
        try:
            timer.deleteLater()
        except Exception:
            pass

    def _stop_progress_bar(self) -> None:
        
        try:
            if self.progress_bar.thread() is QThread.currentThread():
                self.progress_bar.stop()
        except Exception:
            pass


_boot_splash: Optional[BootSplash] = None


def create_boot_splash(window: QWidget) -> BootSplash:
    
    global _boot_splash
    _boot_splash = BootSplash(window)
    return _boot_splash


def finish_boot_splash(delay_ms: int = 1500):
    
    if _boot_splash:
        
        _boot_splash._stop_finish_timer()
        _boot_splash._finish_timer = QTimer(_boot_splash.splash_screen)
        _boot_splash._finish_timer.setSingleShot(True)
        _boot_splash._finish_timer.timeout.connect(_boot_splash.finish)
        _boot_splash._finish_timer.start(delay_ms)
