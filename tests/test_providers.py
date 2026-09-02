from __future__ import annotations

import base64
import io
import json
from pathlib import Path

import httpx
import pytest
from PIL import Image

from aigc_production.config import ProviderConfig
from aigc_production.models import ImageRequest
from aigc_production.providers.gpt_image import GPTImageProvider
from aigc_production.providers.seedream import SeedreamProvider

from .conftest import make_png


def png_b64(color: tuple[int, int, int] = (10, 20, 30)) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (24, 32), color).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def test_seedream_multi_reference_payload_and_b64_result(tmp_path: Path) -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen.update(payload)
        assert request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(
            200, json={"id": "seed-1", "data": [{"b64_json": png_b64()}], "usage": {"images": 1}}
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = SeedreamProvider(
        ProviderConfig("test-key", "https://example.invalid/v3", "seed-model"), client=client
    )
    reference = make_png(tmp_path / "ref.png")
    output = tmp_path / "candidate.png"
    result = provider.generate(ImageRequest("edit only background", output, [reference], size="1024x1536"))
    assert seen["model"] == "seed-model"
    assert seen["size"] == "1664x2496"
    assert str(seen["image"][0]).startswith("data:image/png;base64,")
    assert output.is_file()
    assert result.request_id == "seed-1"


def test_gpt_image_generation_payload(tmp_path: Path) -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(
            200, headers={"x-request-id": "req-1"}, json={"data": [{"b64_json": png_b64()}]}
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = GPTImageProvider(
        ProviderConfig("test-key", "https://example.invalid/v1", "gpt-image-2"), client=client
    )
    output = tmp_path / "candidate.png"
    result = provider.generate(ImageRequest("new image", output, size="1024x1024", quality="low"))
    assert seen == {
        "model": "gpt-image-2",
        "prompt": "new image",
        "n": 1,
        "size": "1024x1024",
        "quality": "low",
    }
    assert result.request_id == "req-1"
    assert output.is_file()


def test_gpt_image_edit_sends_references_and_mask(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("aigc_production.providers.gpt_image.time.sleep", lambda _: None)
    body = b""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal body, call_count
        call_count += 1
        body = request.content
        if call_count == 1:
            return httpx.Response(500, text="retry")
        return httpx.Response(200, json={"data": [{"b64_json": png_b64((90, 20, 20))}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = GPTImageProvider(
        ProviderConfig("test-key", "https://example.invalid/v1", "gpt-image-2"), client=client
    )
    reference = make_png(tmp_path / "reference.png")
    mask = make_png(tmp_path / "mask.png", color=(255, 255, 255))
    output = tmp_path / "edit.png"
    provider.generate(ImageRequest("repair hand", output, [reference], mask, "1024x1024"))
    assert call_count == 2
    assert b'name="image"' in body
    assert b'name="mask"' in body
    assert b"repair hand" in body
    assert output.is_file()
