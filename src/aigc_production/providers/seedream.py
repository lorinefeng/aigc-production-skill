from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any

import httpx

from ..config import ProviderConfig, seedream_config
from ..image_io import image_data_url, write_image_bytes
from ..models import ImageRequest, ProviderResult
from .base import ImageProvider

_SIZE_MAP = {
    "1024x1024": "2048x2048",
    "1024x1536": "1664x2496",
    "1536x1024": "2496x1664",
    "1920x1080": "2848x1600",
    "auto": "2K",
}


class SeedreamProvider(ImageProvider):
    name = "seedream"

    def __init__(self, config: ProviderConfig | None = None, *, client: httpx.Client | None = None):
        self.config = config or seedream_config()
        if not self.config.api_key:
            raise RuntimeError("ARK_API_KEY is not set")
        self._client = client

    def generate(self, request: ImageRequest) -> ProviderResult:
        references = [Path(path) for path in request.reference_images]
        missing = [str(path) for path in references if not path.is_file()]
        if missing:
            raise FileNotFoundError("missing reference image: " + ", ".join(missing))
        if len(references) > 10:
            raise ValueError("SeedreamProvider accepts at most 10 reference images")
        if request.mask_image is not None:
            raise ValueError("Seedream uses prompt coordinates or marked references, not a multipart mask")

        payload: dict[str, Any] = {
            "model": self.config.model,
            "prompt": request.prompt,
            "response_format": "url",
            "size": _SIZE_MAP.get(request.size, request.size or "2K"),
            "watermark": False,
        }
        if references:
            payload["image"] = [image_data_url(path) for path in references]

        response = self._post_with_retry(f"{self.config.base_url}/images/generations", payload)
        body = response.json()
        item = _first_image_item(body)
        output = Path(request.output_path)
        _save_item(item, output)
        return ProviderResult(
            provider=self.name,
            model=self.config.model,
            output_paths=[output],
            request_id=response.headers.get("x-request-id") or str(body.get("id") or "") or None,
            usage=body.get("usage") if isinstance(body.get("usage"), dict) else {},
        )

    def _post_with_retry(self, url: str, payload: dict[str, Any]) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                if self._client is not None:
                    response = self._client.post(url, headers=self._headers(), json=payload)
                else:
                    with httpx.Client(timeout=httpx.Timeout(900, connect=30)) as client:
                        response = client.post(url, headers=self._headers(), json=payload)
                if response.status_code == 429 and attempt < 2:
                    time.sleep(20 + attempt * 20)
                    continue
                if response.status_code >= 500 and attempt < 2:
                    time.sleep(8 + attempt * 10)
                    continue
                if response.status_code >= 400:
                    detail = response.text.strip().replace("\n", " ")[:1200]
                    raise RuntimeError(f"Seedream request failed ({response.status_code}): {detail}")
                return response
            except httpx.TransportError as exc:
                last_error = exc
                if attempt == 2:
                    raise
                time.sleep(8 + attempt * 10)
        raise RuntimeError("Seedream request failed") from last_error

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }


def _first_image_item(body: dict[str, Any]) -> dict[str, Any]:
    data = body.get("data")
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    if isinstance(data, dict):
        return data
    raise ValueError("Seedream response contains no image data")


def _save_item(item: dict[str, Any], output: Path) -> None:
    if item.get("b64_json"):
        write_image_bytes(output, base64.b64decode(str(item["b64_json"])))
        return
    if item.get("url"):
        response = httpx.get(str(item["url"]), timeout=120)
        response.raise_for_status()
        write_image_bytes(output, response.content)
        return
    raise ValueError("Seedream response contains neither url nor b64_json")
