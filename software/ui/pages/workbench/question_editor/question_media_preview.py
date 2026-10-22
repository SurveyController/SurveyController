from __future__ import annotations

from concurrent.futures import Future
from collections.abc import Callable
from itertools import count
from typing import Any, Dict, Optional

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CardWidget, ImageLabel

from .utils import _apply_label_color

_MEDIA_REQUEST_COUNTER = count(1)


MediaFetcher = Callable[[str], Future[bytes]]


class _MediaResultRelay(QObject):
    finished = Signal(int, object)


class QuestionMediaThumbnail(QWidget):
    def __init__(
        self,
        media_item: Dict[str, Any],
        *,
        fixed_size: int = 72,
        show_label: bool = True,
        media_fetcher: MediaFetcher | None = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._media_item = dict(media_item or {})
        self._media_fetcher = media_fetcher
        self._future: Future[bytes] | None = None
        self._fixed_size = max(40, int(fixed_size))
        self._destroyed = False
        self._request_id = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.image_label = ImageLabel(self)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setFixedSize(self._fixed_size, self._fixed_size)
        self.image_label.setStyleSheet(
            "border: 1px solid rgba(128, 128, 128, 0.24); border-radius: 6px; background: transparent;"
        )
        layout.addWidget(self.image_label, 0, Qt.AlignmentFlag.AlignLeft)

        self.text_label: Optional[BodyLabel] = None
        label_text = str(self._media_item.get("label") or "").strip()
        if show_label and label_text:
            self.text_label = BodyLabel(label_text, self)
            self.text_label.setWordWrap(True)
            self.text_label.setMaximumWidth(self._fixed_size + 28)
            self.text_label.setStyleSheet("font-size: 12px;")
            _apply_label_color(self.text_label, "#666666", "#bfbfbf")
            layout.addWidget(self.text_label, 0, Qt.AlignmentFlag.AlignLeft)

        self._set_placeholder()
        self._media_result_relay = _MediaResultRelay(self)
        self._media_result_relay.finished.connect(self._on_loaded)
        self._load_async()
        self.destroyed.connect(self._mark_destroyed)

    def _mark_destroyed(self) -> None:
        self._destroyed = True
        if self._future is not None and not self._future.done():
            self._future.cancel()

    def _set_placeholder(self) -> None:
        self.image_label.setText("图片")
        self.image_label.setStyleSheet(
            "border: 1px solid rgba(128, 128, 128, 0.24); border-radius: 6px; background: transparent; font-size: 12px; color: #888888;"
        )

    def _load_async(self) -> None:
        source_url = str(self._media_item.get("source_url") or "").strip()
        if not source_url or self._media_fetcher is None:
            return
        self._request_id = next(_MEDIA_REQUEST_COUNTER)
        try:
            future = self._media_fetcher(source_url)
        except Exception:
            return
        self._future = future
        relay = self._media_result_relay
        request_id = self._request_id

        def publish_result(done: Future[bytes]) -> None:
            try:
                payload = done.result()
            except Exception:
                payload = b""
            try:
                relay.finished.emit(request_id, payload)
            except RuntimeError:
                return

        future.add_done_callback(publish_result)

    def _on_loaded(self, request_id: int, payload: bytes) -> None:
        if self._destroyed or int(request_id) != self._request_id:
            return
        self._future = None
        if not payload:
            return
        image = QImage()
        if not image.loadFromData(payload):
            return
        pixmap = QPixmap.fromImage(image)
        if pixmap.isNull():
            return
        scaled = pixmap.scaled(
            self.image_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)
        self.image_label.setText("")


class QuestionMediaStrip(CardWidget):
    def __init__(
        self,
        title: str,
        media_items: list[Dict[str, Any]],
        *,
        fixed_size: int = 72,
        show_item_labels: bool = True,
        media_fetcher: MediaFetcher | None = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        title_label = BodyLabel(title, self)
        title_label.setStyleSheet("font-size: 12px;")
        _apply_label_color(title_label, "#666666", "#bfbfbf")
        layout.addWidget(title_label)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        for item in media_items:
            row.addWidget(
                QuestionMediaThumbnail(
                    item,
                    fixed_size=fixed_size,
                    show_label=show_item_labels,
                    media_fetcher=media_fetcher,
                    parent=self,
                )
            )
        row.addStretch(1)
        layout.addLayout(row)
