"""Shared clipboard and drag/drop QR-code handling for survey entry areas."""
from __future__ import annotations

import io
import logging
import os
from typing import TYPE_CHECKING, Optional

from PIL import Image
from PySide6.QtCore import QEvent, QMimeData, QTimer
from PySide6.QtGui import QClipboard, QDragEnterEvent, QDropEvent, QImage
from PySide6.QtWidgets import QFileDialog

from software.app.runtime_paths import get_runtime_directory
from software.io.qr import decode_qrcode
from software.logging.log_utils import log_suppressed_exception


class SurveyClipboardMixin:
    """Handle survey QR-code drag/drop, paste and clipboard parsing."""

    if TYPE_CHECKING:
        from typing import Any

        _toast: Any
        url_edit: Any
        _on_parse_clicked: Any
        link_card: Any
        _clipboard_parse_ticket: int
        _link_entry_widgets: Any

    def eventFilter(self, watched, event):
        if watched in getattr(self, "_link_entry_widgets", ()):
            if event.type() == QEvent.Type.DragEnter:
                if isinstance(event, QDragEnterEvent):
                    mime_data = event.mimeData()
                    if mime_data.hasUrls() or mime_data.hasImage():
                        event.acceptProposedAction()
                        return True
                return False

            if event.type() == QEvent.Type.Drop:
                if isinstance(event, QDropEvent):
                    mime_data = event.mimeData()

                    if mime_data.hasUrls():
                        urls = mime_data.urls()
                        if urls:
                            file_path = urls[0].toLocalFile()
                            if file_path and os.path.exists(file_path):
                                if file_path.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif")):
                                    self._process_qrcode_image(file_path)
                                    event.acceptProposedAction()
                                    return True

                    image_data = self._extract_image_from_clipboard(mime_data)
                    if image_data is not None:
                        self._process_qrcode_image(image_data)
                        event.acceptProposedAction()
                        return True
                return False

            if event.type() == QEvent.Type.KeyPress:
                from PySide6.QtCore import Qt
                from PySide6.QtGui import QKeyEvent
                from PySide6.QtWidgets import QApplication

                if isinstance(event, QKeyEvent):
                    if event.key() == Qt.Key.Key_V and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                        clipboard = QApplication.clipboard()
                        mime_data = clipboard.mimeData(QClipboard.Mode.Clipboard)
                        image_data = self._extract_image_from_clipboard(mime_data, clipboard)
                        if image_data is not None:
                            try:
                                self._clipboard_parse_ticket += 1
                                self._process_qrcode_image(image_data)
                            except Exception:
                                pass
                            return True
                        if mime_data.hasUrls():
                            urls = mime_data.urls()
                            if urls:
                                file_path = urls[0].toLocalFile()
                                if file_path and os.path.exists(file_path):
                                    if file_path.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif")):
                                        self._process_qrcode_image(file_path)
                                        return True

        return super().eventFilter(watched, event)  # type: ignore[attr-defined]

    def _on_clipboard_changed(self):
        if not self._is_focus_in_link_entry():
            return
        self._schedule_clipboard_parse(delay_ms=30, retries=3)

    def _schedule_clipboard_parse(self, delay_ms: int = 30, retries: int = 3):
        self._clipboard_parse_ticket += 1
        ticket = self._clipboard_parse_ticket

        def _run():
            self._try_process_clipboard_image(ticket, retries)

        QTimer.singleShot(delay_ms, _run)

    def _try_process_clipboard_image(self, ticket: int, retries: int):
        if ticket != self._clipboard_parse_ticket:
            return
        if not self._is_focus_in_link_entry():
            return

        from PySide6.QtWidgets import QApplication

        clipboard = QApplication.clipboard()
        mime_data = clipboard.mimeData(QClipboard.Mode.Clipboard)
        if mime_data is None:
            if retries > 0:
                self._schedule_clipboard_parse(delay_ms=50, retries=retries - 1)
            return

        image_data = self._extract_image_from_clipboard(mime_data, clipboard)
        if image_data is not None:
            try:
                self._process_qrcode_image(image_data)
            except Exception:
                pass

    def _is_focus_in_link_entry(self) -> bool:
        from PySide6.QtWidgets import QApplication

        focus_widget = QApplication.focusWidget()
        if focus_widget is None:
            return False
        current = focus_widget
        while current is not None:
            if current is self.link_card:
                return True
            current = current.parentWidget()
        return False

    def _extract_qimage(self, image) -> Optional[QImage]:
        if not isinstance(image, QImage) or image.isNull():
            return None
        return image

    def _extract_image_from_clipboard(self, mime_data: QMimeData, clipboard: Optional[QClipboard] = None):
        if mime_data.hasImage():
            image = mime_data.imageData()
            qimage = self._extract_qimage(image)
            if qimage is not None:
                return qimage

        encoded_image_formats = [
            'application/x-qt-windows-mime;value="PNG"',
            "image/png",
            "image/bmp",
            "image/jpeg",
        ]
        for fmt in encoded_image_formats:
            try:
                raw = mime_data.data(fmt)
                if raw.isEmpty():
                    continue
                qimage = QImage.fromData(raw.data())
                if not qimage.isNull():
                    return qimage
            except Exception:
                continue

        try:
            raw = mime_data.data('application/x-qt-windows-mime;value="DeviceIndependentBitmap"')
            if not raw.isEmpty():
                dib_image = Image.open(io.BytesIO(raw.data()))
                dib_image.load()
                return dib_image
        except Exception as exc:
            log_suppressed_exception("_extract_image_from_clipboard: DeviceIndependentBitmap", exc, level=logging.INFO)

        if clipboard is not None:
            try:
                image = clipboard.image()
                qimage = self._extract_qimage(image)
                if qimage is not None:
                    return qimage
            except Exception as exc:
                log_suppressed_exception("_extract_image_from_clipboard: clipboard.image()", exc, level=logging.INFO)

        return None

    def _process_qrcode_image(self, image_source):
        try:
            url = decode_qrcode(image_source)
            if not url:
                self._toast("未能识别二维码中的链接", "error")
                return

            self.url_edit.setText(url)
            self._on_parse_clicked()
        except Exception as exc:
            self._toast(f"处理二维码图片失败：{exc}", "error")
            log_suppressed_exception("_process_qrcode_image", exc, level=logging.WARNING)

    def _on_qr_clicked(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择二维码图片",
            get_runtime_directory(),
            "含有二维码的图片 (*.png *.jpg *.jpeg *.bmp)",
        )  # type: ignore[arg-type]
        if not path:
            return
        self._process_qrcode_image(path)
