"""GIF engine: lossless LZW/palette optimization, animation preserved."""

from __future__ import annotations

import io

from PIL import Image

from ..errors import EncodeError
from ..result import EncodeAttempt
from .base import EncodeContext


def _optimize(data: bytes) -> bytes:
    try:
        with Image.open(io.BytesIO(data)) as gif:
            animated = bool(getattr(gif, "is_animated", False))
            buffer = io.BytesIO()
            gif.save(
                buffer,
                format="GIF",
                save_all=animated,
                optimize=True,
            )
            return buffer.getvalue()
    except (OSError, ValueError):
        return data


class GifEncoder:
    """GIF is optimized losslessly; per-frame losses are never introduced."""

    name = "GIF"
    supports_lossless = True
    install_hint = ""

    def available(self) -> bool:
        return True

    def encode(self, image: Image.Image, ctx: EncodeContext) -> EncodeAttempt:
        if ctx.options.quality_mode == "manual":
            raise EncodeError(
                "GIF only supports lossless optimization; "
                "use quality='auto' or 'lossless'"
            )
        data = _optimize(ctx.original)
        metrics = ctx.measure(data)
        note = "GIF losslessly optimized"
        if ctx.animated:
            note += " (animation preserved)"
        return EncodeAttempt(data=data, metrics=metrics, quality="lossless", note=note)
