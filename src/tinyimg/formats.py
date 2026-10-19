"""Format names, aliases, suffixes and capabilities.

Keeping this table in one place means a port can add a format or change which
formats are accepted without touching the compression pipeline.
"""

from __future__ import annotations

import pathlib as p

from pydantic import BaseModel, ConfigDict

from .errors import UnsupportedFormatError


class FormatSpec(BaseModel):
    """Static capabilities of one image format."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    suffix: str
    can_encode: bool
    supports_alpha: bool
    supports_lossless: bool

    @property
    def can_decode(self) -> bool:
        """All formats in the built-in table are decodable."""
        return True


#: Built-in formats.  ``can_encode`` is False for input-only formats.
FORMATS: dict[str, FormatSpec] = {
    "PNG": FormatSpec(
        name="PNG",
        suffix=".png",
        can_encode=True,
        supports_alpha=True,
        supports_lossless=True,
    ),
    "JPEG": FormatSpec(
        name="JPEG",
        suffix=".jpg",
        can_encode=True,
        supports_alpha=False,
        supports_lossless=False,
    ),
    "WEBP": FormatSpec(
        name="WEBP",
        suffix=".webp",
        can_encode=True,
        supports_alpha=True,
        supports_lossless=True,
    ),
    "GIF": FormatSpec(
        name="GIF",
        suffix=".gif",
        can_encode=True,
        supports_alpha=True,
        supports_lossless=True,
    ),
    "AVIF": FormatSpec(
        name="AVIF",
        suffix=".avif",
        can_encode=True,
        supports_alpha=True,
        supports_lossless=False,
    ),
    "BMP": FormatSpec(
        name="BMP",
        suffix=".bmp",
        can_encode=False,
        supports_alpha=False,
        supports_lossless=True,
    ),
    "TIFF": FormatSpec(
        name="TIFF",
        suffix=".tif",
        can_encode=False,
        supports_alpha=True,
        supports_lossless=True,
    ),
}

_ALIASES = {
    "APNG": "PNG",
    "JPG": "JPEG",
    "JPE": "JPEG",
    "JFIF": "JPEG",
    "MPO": "JPEG",
    "TIF": "TIFF",
}

#: Suffixes accepted when scanning a directory.  Includes aliases so that
#: ``.jpeg`` and ``.tiff`` files are not silently skipped.
INPUT_SUFFIXES: frozenset[str] = frozenset(
    {
        ".apng",
        ".avif",
        ".bmp",
        ".gif",
        ".jfif",
        ".jpe",
        ".jpeg",
        ".jpg",
        ".mpo",
        ".png",
        ".tif",
        ".tiff",
        ".webp",
    }
)


def normalize_format(value: str) -> str:
    """Return the canonical upper-case format name for *value*.

    Accepts ``"png"``, ``".PNG"``, ``"jpg"`` and the other aliases in the
    table.  Raises :class:`UnsupportedFormatError` for unknown formats.
    """
    key = value.strip().upper().lstrip(".")
    if not key:
        raise UnsupportedFormatError("empty image format")
    key = _ALIASES.get(key, key)
    if key not in FORMATS:
        raise UnsupportedFormatError(f"unsupported image format: {value!r}")
    return key


def format_from_suffix(path: str | p.Path) -> str | None:
    """Infer a format from a path suffix, or return ``None``."""
    suffix = p.Path(path).suffix
    if not suffix:
        return None
    try:
        return normalize_format(suffix)
    except UnsupportedFormatError:
        return None


def output_formats() -> tuple[str, ...]:
    """Canonical names of formats this package can write."""
    return tuple(name for name, spec in FORMATS.items() if spec.can_encode)


def is_input_suffix(path: str | p.Path) -> bool:
    """True when *path* has a suffix accepted by the directory scanner."""
    return p.Path(path).suffix.lower() in INPUT_SUFFIXES
