import logging
import os
from typing import Optional

from PySide6.QtGui import QImage

import zxingcpp


def _load_qimage(image_path: str) -> QImage:
    
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"图片文件不存在: {image_path}")

    image = QImage(image_path)
    if image.isNull():
        raise ValueError(f"无法读取图片: {image_path}")

    return image


def decode_qrcode(image_source: object) -> Optional[str]:
    
    try:
        if isinstance(image_source, str):
            image = _load_qimage(image_source)
        elif isinstance(image_source, QImage):
            if image_source.isNull():
                raise ValueError("图片数据为空")
            image = image_source
        else:
            image = image_source

        result = zxingcpp.read_barcode(
            image,
            zxingcpp.BarcodeFormat.QRCode,
            try_rotate=True,
            try_downscale=True,
            try_invert=True,
        )

        if result and result.valid and result.text:
            return result.text

        return None

    except Exception as exc:
        logging.error(f"二维码解码失败: {exc}")
        return None
