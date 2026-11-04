from __future__ import annotations

from PySide6.QtGui import QImage


def qr_pixel_buffer(source: QImage | str) -> memoryview | None:
    image = QImage(source) if isinstance(source, str) else source
    if image.isNull():
        return None
    gray = image.convertToFormat(QImage.Format.Format_Grayscale8)
    width, height, stride = gray.width(), gray.height(), gray.bytesPerLine()
    pixels = bytes(gray.constBits())
    # QImage rows have padding; expose a tightly packed, owned Python buffer.
    packed = b"".join(pixels[row * stride : row * stride + width] for row in range(height))
    return memoryview(packed).cast("B", shape=[height, width])
