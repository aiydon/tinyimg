"""AVIF engine, enabled by installing ``tinyimg[avif]``."""

from __future__ import annotations

import io
import typing as t

from PIL import Image

from ..errors import EncodeError
from ..result import EncodeAttempt
from .base import EncodeContext, search_quality

try:  # Registers AVIF support with Pillow.
    import pillow_avif  # noqa: F401

    _PILLOW_AVIF_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised when the extra is absent
    _PILLOW_AVIF_AVAILABLE = False

_SPEED = {"fast": 9, "balanced": 6, "max": 4}


def _save(image: Image.Image, options: dict[str, t.Any]) -> bytes:
    """Save, dropping optional metadata arguments the plugin does not know."""
    buffer = io.BytesIO()
    try:
        image.save(buffer, **options)
        return buffer.getvalue()
    except TypeError:
        pass
    except (OSError, ValueError) as exc:
        raise EncodeError(f"AVIF encoding failed: {exc}") from exc

    for key in ("exif", "icc_profile"):
        if key in options:
            options.pop(key)
            buffer = io.BytesIO()
            try:
                image.save(buffer, **options)
                return buffer.getvalue()
            except TypeError:
                continue
            except (OSError, ValueError) as exc:
                raise EncodeError(f"AVIF encoding failed: {exc}") from exc
    raise EncodeError("AVIF encoder rejected all supported save options")


def _encode(
    image: Image.Image, quality: int, *, speed: int, ctx: EncodeContext
) -> bytes:
    options: dict[str, t.Any] = {
        "format": "AVIF",
        "quality": quality,
        "speed": speed,
    }
    options.update(ctx.save_options())
    return _save(image, options)


class AvifEncoder:
    """AVIF encoder; unavailable when pillow-avif-plugin is not installed."""

    name = "AVIF"
    supports_lossless = False
    install_hint = "install tinyimg[avif] (pillow-avif-plugin)"

    def available(self) -> bool:
        return _PILLOW_AVIF_AVAILABLE

    def encode(self, image: Image.Image, ctx: EncodeContext) -> EncodeAttempt:
        if not self.available():
            raise EncodeError(self.install_hint)

        options = ctx.options
        if options.quality == "lossless":
            raise EncodeError(
                "AVIF lossless encoding is not supported; use PNG or WebP"
            )

        speed = _SPEED[options.effort]

        def attempt(quality: int) -> EncodeAttempt:
            data = _encode(image, quality, speed=speed, ctx=ctx)
            return EncodeAttempt(
                data=data,
                metrics=ctx.measure(data),
                quality=quality,
                note=f"AVIF quality {quality}, speed {speed}",
            )

        if options.quality_mode == "manual":
            assert options.quality_value is not None
            return attempt(options.quality_value)

        return search_quality(attempt, ctx, low=40, high=95, default=65)
