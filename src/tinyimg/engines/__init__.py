"""Built-in encoder engines and the public registry API."""

from __future__ import annotations

from .avif import AvifEncoder
from .base import EncodeContext, Encoder, search_quality
from .gif import GifEncoder
from .jpeg import JpegEncoder
from .png import PngEncoder
from .registry import (
    available_formats,
    get_encoder,
    register_encoder,
    unregister_encoder,
)
from .webp import WebpEncoder

# Import-time registration is intentional: importing tinyimg gives a
# complete, ready-to-use set of engines.  ``replace=True`` keeps reloads safe.
for _engine in (
    PngEncoder(),
    JpegEncoder(),
    WebpEncoder(),
    AvifEncoder(),
    GifEncoder(),
):
    register_encoder(_engine, replace=True)

__all__ = [
    "AvifEncoder",
    "EncodeContext",
    "Encoder",
    "GifEncoder",
    "JpegEncoder",
    "PngEncoder",
    "WebpEncoder",
    "available_formats",
    "get_encoder",
    "register_encoder",
    "search_quality",
    "unregister_encoder",
]
