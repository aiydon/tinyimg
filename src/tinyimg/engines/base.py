"""Encoder contract and helpers shared by all built-in engines.

This module is the main porting seam.  To use a different backend (a system
binary, a WASM encoder, a vendor SDK), implement :class:`Encoder` and register
it with :func:`tinyimg.register_encoder`.  The pipeline only depends on this
small protocol, not on Pillow's save details.
"""

from __future__ import annotations

import io
import typing as t
from collections.abc import Callable

from PIL import Image, ImageOps
from pydantic import BaseModel, ConfigDict

from ..errors import EncodeError
from ..metrics import Metrics, compare
from ..options import Budget, CompressionOptions
from ..result import EncodeAttempt


class EncodeContext(BaseModel):
    """Everything an encoder needs besides the pixel buffer.

    ``reference`` is the normalized image used for quality measurement (EXIF
    orientation applied, alpha flattened only when the target format requires
    it).  ``original`` is the raw source file, needed by the GIF engine to
    preserve animation frames.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    options: CompressionOptions
    reference: Image.Image
    original: bytes
    source_format: str
    icc: bytes | None = None
    exif: bytes | None = None
    animated: bool = False

    @property
    def budget(self) -> Budget:
        return self.options.budget

    @property
    def verify(self) -> bool:
        return self.options.verify

    def save_options(self, *, include_exif: bool = True) -> dict[str, t.Any]:
        """Metadata arguments accepted by Pillow's PNG/JPEG/WebP writers."""
        options: dict[str, t.Any] = {}
        if self.icc:
            options["icc_profile"] = self.icc
        if include_exif and self.options.keep_metadata and self.exif:
            options["exif"] = self.exif
        return options

    def measure(self, data: bytes) -> Metrics | None:
        """Decode encoded bytes and compare them with ``reference``.

        Returns ``None`` when verification is disabled or the image is
        animated (per-frame metrics are not meaningful for an animation).
        """
        if not self.verify or self.animated:
            return None
        try:
            with Image.open(io.BytesIO(data)) as opened:
                opened.load()
                oriented = ImageOps.exif_transpose(opened)
                oriented.load()
                return compare(self.reference, oriented)
        except (OSError, ValueError) as exc:
            raise EncodeError(
                f"encoded output could not be decoded for verification: {exc}"
            ) from exc

    def accepts(self, attempt: EncodeAttempt, *, palette: bool = False) -> bool:
        """True when *attempt* is inside the perceptual budget."""
        if attempt.metrics is None:
            return True
        return self.budget.accepts(attempt.metrics, palette=palette)


@t.runtime_checkable
class Encoder(t.Protocol):
    """Minimal interface the pipeline uses to encode one image."""

    name: str
    supports_lossless: bool
    install_hint: str

    def available(self) -> bool:
        """False when an optional dependency or system binary is missing."""
        ...

    def encode(self, image: Image.Image, ctx: EncodeContext) -> EncodeAttempt:
        """Return encoded bytes plus measured quality, without writing files."""
        ...


def search_quality(
    encode: Callable[[int], EncodeAttempt],
    ctx: EncodeContext,
    *,
    low: int,
    high: int,
    default: int,
) -> EncodeAttempt:
    """Binary-search the lowest quality that satisfies the budget.

    ``encode`` must attach metrics when ``ctx.verify`` is enabled.  When
    verification is off, no search is possible; a conservative ``default`` is
    used so throughput mode still produces predictable output.
    """
    if not ctx.verify:
        return encode(default)

    highest = high
    best: EncodeAttempt | None = None
    while low <= high:
        middle = (low + high) // 2
        candidate = encode(middle)
        if ctx.accepts(candidate):
            best = candidate
            high = middle - 1
        else:
            low = middle + 1

    if best is None:
        best = encode(highest)
        note = "perceptual target not reached"
        best = best.model_copy(
            update={"note": f"{best.note}; {note}" if best.note else note}
        )
    return best
