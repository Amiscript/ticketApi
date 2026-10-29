from io import BytesIO

import qrcode


def generate_qr_png(data: str) -> bytes:
    img = qrcode.make(data, box_size=8, border=2)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
