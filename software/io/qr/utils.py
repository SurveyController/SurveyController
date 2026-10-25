import logging
from typing import Optional

import zxingcpp


def decode_qrcode(image_source: object) -> Optional[str]:

    try:
        result = zxingcpp.read_barcode(
            image_source,
            zxingcpp.BarcodeFormats([zxingcpp.BarcodeFormat.QRCode]),
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
