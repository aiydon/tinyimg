from __future__ import annotations

import json
import pathlib as p

import numpy as np
from click.testing import CliRunner
from PIL import Image

from tinyimg.cli import main


def _png(path: p.Path) -> p.Path:
    array = np.linspace(0, 255, 64 * 64 * 3, dtype=np.uint8).reshape(64, 64, 3)
    Image.fromarray(array, "RGB").save(path, optimize=True)
    return path


def test_list_formats() -> None:
    result = CliRunner().invoke(main, ["--list-formats"])
    assert result.exit_code == 0
    assert "PNG" in result.output
    assert "AVIF" in result.output
    assert "lossless" in result.output


def test_version() -> None:
    result = CliRunner().invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "tinyimg" in result.output


def test_json_batch_success(tmp_path: p.Path) -> None:
    source = _png(tmp_path / "source.png")
    output = tmp_path / "out"
    result = CliRunner().invoke(
        main,
        [
            str(source),
            "-o",
            str(output),
            "--json",
            "--overwrite",
            "--workers",
            "2",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["totals"]["succeeded"] == 1
    assert payload["totals"]["failed"] == 0
    entry = payload["results"][0]
    assert p.Path(entry["output"]).exists()
    assert entry["metrics"] is not None


def test_json_batch_failure_is_nonzero(tmp_path: p.Path) -> None:
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not an image")
    result = CliRunner().invoke(
        main,
        [str(bad), "-o", str(tmp_path / "out"), "--json"],
    )
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["totals"]["failed"] == 1
    assert payload["failures"][0]["error_type"] == "DecodeError"


def test_missing_input_is_usage_error() -> None:
    result = CliRunner().invoke(main, [])
    assert result.exit_code == 2
    assert "at least one input is required" in result.output
