from __future__ import annotations

from pathlib import Path

import pytest

from tinyimg import (
    FORMATS,
    UnsupportedFormatError,
    available_formats,
    format_from_suffix,
    normalize_format,
    output_formats,
)


def test_aliases_and_case() -> None:
    assert normalize_format("png") == "PNG"
    assert normalize_format(".JPG") == "JPEG"
    assert normalize_format("jpeg") == "JPEG"
    assert normalize_format("jfif") == "JPEG"
    assert normalize_format("apng") == "PNG"
    assert normalize_format("tif") == "TIFF"


def test_unknown_format() -> None:
    with pytest.raises(UnsupportedFormatError):
        normalize_format("svg")
    with pytest.raises(UnsupportedFormatError):
        normalize_format("")


def test_suffix_lookup() -> None:
    assert format_from_suffix(Path("photo.jpeg")) == "JPEG"
    assert format_from_suffix(Path("photo.webp")) == "WEBP"
    assert format_from_suffix(Path("photo.unknown")) is None
    assert format_from_suffix(Path("photo")) is None


def test_capabilities() -> None:
    assert FORMATS["PNG"].can_encode
    assert FORMATS["PNG"].supports_alpha
    assert FORMATS["PNG"].supports_lossless
    assert not FORMATS["JPEG"].supports_alpha
    assert not FORMATS["JPEG"].supports_lossless
    assert FORMATS["BMP"].can_decode
    assert not FORMATS["BMP"].can_encode
    assert set(output_formats()) == {"PNG", "JPEG", "WEBP", "GIF", "AVIF"}


def test_registered_encoders_cover_output_formats() -> None:
    status = available_formats()
    for name in output_formats():
        assert name in status
        assert isinstance(status[name], bool)
