from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from tinyimg import (
    CompressionError,
    CompressionOptions,
    OptionError,
    compress_directory,
    compress_many,
)


def _png(path: Path, seed: int = 0) -> Path:
    rng = np.random.default_rng(seed)
    array = rng.integers(0, 256, (64, 64, 3), dtype=np.uint8)
    Image.fromarray(array, "RGB").save(path, optimize=True)
    return path


def test_compress_many_collects_failures(tmp_path: Path) -> None:
    good_a = _png(tmp_path / "a.png", 1)
    good_b = _png(tmp_path / "b.png", 2)
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not an image")

    report = compress_many(
        [good_a, good_b, bad],
        tmp_path / "out",
        workers=2,
        options=CompressionOptions(overwrite=True),
    )

    assert report.scanned == 3
    assert report.succeeded == 2
    assert report.failed == 1
    assert [failure.source.name for failure in report.failures] == ["bad.png"]
    assert report.failures[0].error_type == "DecodeError"
    assert report.total_source_bytes > 0
    assert report.total_output_bytes > 0
    assert report.savings >= 0.0
    assert all(result.output.parent == tmp_path / "out" for result in report.results)

    payload = report.as_dict()
    assert payload["totals"]["succeeded"] == 2
    assert payload["totals"]["failed"] == 1
    assert len(payload["results"]) == 2
    assert len(payload["failures"]) == 1

    with pytest.raises(CompressionError, match="1 image"):
        report.raise_for_failures()


def test_compress_many_callbacks_and_input_order(tmp_path: Path) -> None:
    files = [_png(tmp_path / f"{index}.png", index) for index in range(3)]
    seen: list[str] = []

    report = compress_many(
        files,
        tmp_path / "out",
        workers=3,
        options=CompressionOptions(overwrite=True),
        on_result=lambda result: seen.append(result.source.name),
    )

    assert report.failed == 0
    assert [result.source.name for result in report.results] == [
        "0.png",
        "1.png",
        "2.png",
    ]
    assert sorted(seen) == ["0.png", "1.png", "2.png"]


def test_compress_directory_recursive(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    _png(source / "top.png", 1)
    nested = source / "nested"
    nested.mkdir()
    _png(nested / "deep.png", 2)

    flat = compress_directory(
        source,
        tmp_path / "flat",
        options=CompressionOptions(overwrite=True),
    )
    assert flat.scanned == 1
    assert flat.results[0].source.name == "top.png"

    recursive = compress_directory(
        source,
        tmp_path / "recursive",
        recursive=True,
        options=CompressionOptions(overwrite=True),
    )
    assert recursive.scanned == 2
    assert {result.source.name for result in recursive.results} == {
        "top.png",
        "deep.png",
    }


def test_batch_output_must_be_directory_for_multiple_inputs(
    tmp_path: Path,
) -> None:
    first = _png(tmp_path / "a.png", 1)
    second = _png(tmp_path / "b.png", 2)
    with pytest.raises(OptionError):
        compress_many([first, second], tmp_path / "out.png")


def test_workers_validation(tmp_path: Path) -> None:
    source = _png(tmp_path / "a.png", 1)
    with pytest.raises(OptionError):
        compress_many([source], workers=0)


def test_batch_detects_duplicate_output_names(tmp_path: Path) -> None:
    first = tmp_path / "a" / "photo.png"
    second = tmp_path / "b" / "photo.png"
    first.parent.mkdir()
    second.parent.mkdir()
    _png(first, 1)
    _png(second, 2)
    with pytest.raises(OptionError, match="same output name"):
        compress_many([first, second], tmp_path / "out")
