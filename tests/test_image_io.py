from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from aigc_production.image_io import prepare_reference, validate_image

from .conftest import make_png


def test_prepare_reference_limits_dimensions_and_bytes(tmp_path: Path) -> None:
    source = make_png(tmp_path / "large.png", size=(3600, 2400), color=(80, 120, 160))
    output = tmp_path / "safe/reference.jpg"
    result = prepare_reference(source, output, max_long_edge=512, max_bytes=100_000)
    assert result == output
    assert output.stat().st_size <= 100_000
    with Image.open(output) as image:
        assert max(image.size) <= 512
    assert validate_image(output)["format"] == "JPEG"


def test_prepare_reference_never_overwrites_source(tmp_path: Path) -> None:
    source = make_png(tmp_path / "source.png")
    with pytest.raises(ValueError, match="must not overwrite"):
        prepare_reference(source, source)
