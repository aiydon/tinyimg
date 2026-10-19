"""WebP engine: adaptive lossy quality with lossless alpha."""

from __future__ import annotations

import io
import typing as t

from PIL import Image

from ..errors import EncodeError
from ..result import EncodeAttempt
from .base import EncodeContext, search_quality

_METHOD = {"fast": 2, "balanced": 4, "max": 6}


def _encode(
    image: Image.Image,
    quality: int,
    *,
    method: int,
    ctx: EncodeContext,
) -> bytes:
    buffer = io.BytesIO()
    options: dict[str, t.Any] = {
        "format": "WEBP",
        "quality": quality,
        "method": method,
        "alpha_quality": 100,
        "use_sharp_yuv": True,
    }
    options.update(ctx.save_options())
    try:
        image.save(buffer, **options)
    except (OSError, ValueError, TypeError) as exc:
        raise EncodeError(f"WebP encoding failed: {exc}") from exc
    return buffer.getvalue()


def _encode_lossless(image: Image.Image, *, method: int, ctx: EncodeContext) -> bytes:
    buffer = io.BytesIO()
    options: dict[str, t.Any] = {
        "format": "WEBP",
        "lossless": True,
        "quality": 100,
        "method": method,
    }
    options.update(ctx.save_options())
    try:
        image.save(buffer, **options)
    except (OSError, ValueError, TypeError) as exc:
        raise EncodeError(f"lossless WebP encoding failed: {exc}") from exc
    return buffer.getvalue()


class WebpEncoder:
    """WebP encoder with lossless alpha and optional lossless mode."""

    name = "WEBP"
    supports_lossless = True
    install_hint = ""

    def available(self) -> bool:
        return True

    def encode(self, image: Image.Image, ctx: EncodeContext) -> EncodeAttempt:
        options = ctx.options
        method = _METHOD[options.effort]

        if options.quality == "lossless":
            data = _encode_lossless(image, method=method, ctx=ctx)
            return EncodeAttempt(
                data=data,
                metrics=ctx.measure(data),
                quality="lossless",
                note="lossless WebP",
            )

        def attempt(quality: int) -> EncodeAttempt:
            data = _encode(image, quality, method=method, ctx=ctx)
            return EncodeAttempt(
                data=data,
                metrics=ctx.measure(data),
                quality=quality,
                note=f"WebP quality {quality}, method {method}",
            )

        if options.quality_mode == "manual":
            assert options.quality_value is not None
            return attempt(options.quality_value)

        return search_quality(attempt, ctx, low=50, high=95, default=80)
