from __future__ import annotations

import base64 as _base64
from io import BytesIO
from typing import Any

import numpy as np
from PIL import Image

DIGITS = (
    (7, 5, 5, 5, 7),
    (2, 6, 2, 2, 7),
    (7, 1, 7, 4, 7),
    (7, 1, 7, 1, 7),
    (5, 5, 7, 1, 1),
    (7, 4, 7, 1, 7),
    (7, 4, 7, 5, 7),
    (7, 1, 1, 1, 1),
    (7, 5, 7, 5, 7),
    (7, 5, 7, 1, 7),
)
SCALE, RADIUS = 3, 15


def mark(rgb: bytearray, width: int, height: int, spots: list[dict[str, Any]]) -> None:
    def put(x: int, y: int, colour: tuple[int, int, int], alpha: float) -> None:
        if 0 <= x < width and 0 <= y < height:
            at = (y * width + x) * 3
            for c in range(3):
                rgb[at + c] = int(rgb[at + c] * (1 - alpha) + colour[c] * alpha)

    for spot in spots:
        try:
            ident, cx, cy = (
                int(spot["id"]),
                int(float(spot["x"]) * width),
                int(float(spot["y"]) * height),
            )
        except (KeyError, TypeError, ValueError):
            continue
        for dy in range(-RADIUS, RADIUS + 1):
            for dx in range(-RADIUS, RADIUS + 1):
                distance = (dx * dx + dy * dy) ** 0.5
                if distance <= RADIUS - 2:
                    put(cx + dx, cy + dy, (0, 0, 0), 0.7)
                elif distance <= RADIUS:
                    put(cx + dx, cy + dy, (255, 255, 255), 1)
        text = str(ident)
        left = cx - (len(text) * 4 * SCALE - SCALE) // 2
        top = cy - 5 * SCALE // 2
        for n, digit in enumerate(text):
            for row, bits in enumerate(DIGITS[int(digit)]):
                for col in range(3):
                    if bits >> (2 - col) & 1:
                        for sy in range(SCALE):
                            for sx in range(SCALE):
                                put(
                                    left + n * 4 * SCALE + col * SCALE + sx,
                                    top + row * SCALE + sy,
                                    (255, 255, 255),
                                    1,
                                )


def png(rgb: bytes | bytearray, width: int, height: int) -> bytes:
    image = Image.fromarray(np.frombuffer(rgb, dtype=np.uint8).reshape(height, width, 3), "RGB")
    out = BytesIO()
    image.save(out, format="PNG", compress_level=0)
    return out.getvalue()


def base64(data: bytes) -> str:
    return _base64.b64encode(data).decode()
