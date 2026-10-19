"""Exception hierarchy for tinyimg.

Every library error derives from :class:`TinyImgError`, so host
applications can catch one base class at their boundary.  The more specific
classes let a service distinguish "bad input" from "bad options" or "output
already exists" without parsing messages.
"""

from __future__ import annotations


class TinyImgError(Exception):
    """Base class for every error raised by tinyimg."""


class CompressionError(TinyImgError):
    """A single image could not be compressed."""


class OptionError(CompressionError, ValueError):
    """Compression options are invalid or mutually inconsistent."""


class UnsupportedFormatError(CompressionError):
    """An image format is unknown or cannot be encoded by this installation."""


class DecodeError(CompressionError):
    """Input bytes could not be decoded as an image."""


class EncodeError(CompressionError):
    """An encoder failed to produce output."""


class OutputExistsError(CompressionError):
    """The output path exists and ``overwrite`` is disabled."""
