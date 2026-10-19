"""Pluggable encoder registry.

The registry is the stable extension point for ports that need a different
backend (for example a system ``cjpeg``/``pngquant`` binary or a GPU encoder).
It is deliberately independent of the built-in format table: custom engines
may register names that this package does not know how to decode.
"""

from __future__ import annotations

from threading import RLock

from ..errors import UnsupportedFormatError
from ..formats import normalize_format
from .base import Encoder

_ENGINES: dict[str, Encoder] = {}
_LOCK = RLock()


def _key(name: str) -> str:
    raw = name.strip()
    if not raw:
        raise ValueError("encoder name must not be empty")
    try:
        return normalize_format(raw)
    except UnsupportedFormatError:
        return raw.upper()


def register_encoder(encoder: Encoder, *, replace: bool = False) -> None:
    """Register *encoder* under ``encoder.name``.

    ``replace=False`` protects against accidental double registration.
    Built-in engines are registered with ``replace=True`` so module reloads
    during development do not fail.
    """
    if not callable(getattr(encoder, "encode", None)):
        raise TypeError("encoder must define an encode(image, ctx) method")
    name = _key(encoder.name)
    with _LOCK:
        if name in _ENGINES and not replace:
            raise ValueError(f"an encoder for {name} is already registered")
        _ENGINES[name] = encoder


def unregister_encoder(name: str) -> None:
    """Remove an encoder.  Raises ``KeyError`` if it is not registered."""
    key = _key(name)
    with _LOCK:
        if _ENGINES.pop(key, None) is None:
            raise KeyError(key)


def get_encoder(name: str) -> Encoder:
    """Return an available encoder or raise a descriptive error."""
    key = _key(name)
    with _LOCK:
        encoder = _ENGINES.get(key)
    if encoder is None:
        raise UnsupportedFormatError(
            f"no encoder registered for {key}; "
            f"available: {', '.join(available_formats()) or 'none'}"
        )
    if not encoder.available():
        hint = getattr(encoder, "install_hint", "")
        message = f"{key} encoding is unavailable"
        if hint:
            message += f"; {hint}"
        raise UnsupportedFormatError(message)
    return encoder


def available_formats() -> dict[str, bool]:
    """Map every registered encoder name to its availability."""
    with _LOCK:
        items = sorted(_ENGINES.items())
    return {name: encoder.available() for name, encoder in items}
