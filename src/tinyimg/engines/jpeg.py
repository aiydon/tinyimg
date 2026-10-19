"""JPEG engine: adaptive quality search with progressive encoding."""

from __future__ import annotations

import io
import typing as t

from PIL import Image

from ..errors import EncodeError
from ..result import EncodeAttempt
from .base import EncodeContext, search_quality


def _encode(image: Image.Image, quality: int, ctx: EncodeContext) -> bytes:
    buffer = io.BytesIO()
    options: dict[str, t.Any] = {
        "format": "JPEG",
        "quality": quality,
        "optimize": True,
        "progressive": True,
    }
    if image.mode == "RGB":
        options["subsampling"] = 0 if quality >= 90 else 2
    options.update(ctx.save_options())
    try:
        image.save(buffer, **options)
    except (OSError, ValueError, TypeError) as exc:
        raise EncodeError(f"JPEG encoding failed: {exc}") from exc
    return buffer.getvalue()


class JpegEncoder:
    """JPEG encoder with a perceptual quality floor."""

    name = "JPEG"
    supports_lossless = False
    install_hint = ""

    def available(self) -> bool:
        return True

    def encode(self, image: Image.Image, ctx: EncodeContext) -> EncodeAttempt:
        options = ctx.options
        if options.quality == "lossless":
            raise EncodeError("JPEG cannot be encoded losslessly; use PNG or WebP")

        def attempt(quality: int) -> EncodeAttempt:
            data = _encode(image, quality, ctx)
            subsampling = "4:4:4" if quality >= 90 else "4:2:0"
            return EncodeAttempt(
                data=data,
                metrics=ctx.measure(data),
                quality=quality,
                note=f"JPEG quality {quality}, progressive, {subsampling}",
            )

        if options.quality_mode == "manual":
            assert options.quality_value is not None
            return attempt(options.quality_value)

        # A perceptual metric can approve absurdly low JPEG qualities on flat
        # graphics because ringing is local.  Keep a sane encoder floor.
        return search_quality(attempt, ctx, low=60, high=95, default=82)
