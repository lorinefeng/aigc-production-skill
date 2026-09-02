from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any

import httpx

from ..config import ProviderConfig, gpt_image_config
from ..image_io import mime_type, write_image_bytes
from ..models import ImageRequest, ProviderResult
from .base import ImageProvider


class GPTImageProvider(ImageProvider):
    name = "gpt-image"

    def __init__(self, config: ProviderConfig | None = None, *, client: httpx.Client | None = None):
        self.config = config or gpt_image_config()
        if not self.config.api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        self._client = client

    def generate(self, request: ImageRequest) -> ProviderResult:
        references = [Path(path) for path in request.reference_images]
        missing = [str(path) for path in references if not path.is_file()]
        if missing:
            raise FileNotFoundError("missing reference image: " + ", ".join(missing))
        if request.mask_image is not None and not request.mask_image.is_file():
            raise FileNotFoundError(request.mask_image)

        if references:
            response = self._edit(request, references)
        else:
            response = self._generate(request)
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

    def _generate(self, request: ImageRequest) -> httpx.Response:
        data: dict[str, Any] = {
            "model": self.config.model,
            "prompt": request.prompt,
            "n": 1,
            "size": request.size,
        }
        if request.quality:
            data["quality"] = request.quality
        return self._request_with_retry(
            "POST",
            f"{self.config.base_url}/images/generations",
            json=data,
        )

    def _edit(self, request: ImageRequest, references: list[Path]) -> httpx.Response:
        handles = []
        try:
            files: list[tuple[str, tuple[str, Any, str]]] = []
            for path in references:
                handle = path.open("rb")
                handles.append(handle)
                files.append(("image", (path.name, handle, mime_type(path))))
            if request.mask_image is not None:
                handle = request.mask_image.open("rb")
                handles.append(handle)
                files.append(("mask", (request.mask_image.name, handle, mime_type(request.mask_image))))
            data: dict[str, str] = {
                "model": self.config.model,
                "prompt": request.prompt,
                "n": "1",
                "size": request.size,
            }
            if request.quality:
                data["quality"] = request.quality
            return self._request_with_retry(
                "POST",
                f"{self.config.base_url}/images/edits",
                data=data,
                files=files,
            )
        finally:
            for handle in handles:
                handle.close()

    def _request_with_retry(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                for _, file_value in kwargs.get("files", []):
                    file_handle = file_value[1]
                    if hasattr(file_handle, "seek"):
                        file_handle.seek(0)
                headers = {"Authorization": f"Bearer {self.config.api_key}", "Accept": "application/json"}
                if self._client is not None:
                    response = self._client.request(method, url, headers=headers, **kwargs)
                else:
                    with httpx.Client(timeout=httpx.Timeout(900, connect=30)) as client:
                        response = client.request(method, url, headers=headers, **kwargs)
                if response.status_code == 429 and attempt < 2:
                    time.sleep(20 + attempt * 20)
                    continue
                if response.status_code >= 500 and attempt < 2:
                    time.sleep(8 + attempt * 10)
                    continue
                if response.status_code >= 400:
                    detail = response.text.strip().replace("\n", " ")[:1200]
                    raise RuntimeError(f"GPT Image request failed ({response.status_code}): {detail}")
                return response
            except httpx.TransportError as exc:
                last_error = exc
                if attempt == 2:
                    raise
                time.sleep(8 + attempt * 10)
        raise RuntimeError("GPT Image request failed") from last_error


def _first_image_item(body: dict[str, Any]) -> dict[str, Any]:
    data = body.get("data")
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    if isinstance(data, dict):
        return data
    raise ValueError("GPT Image response contains no image data")


def _save_item(item: dict[str, Any], output: Path) -> None:
    if item.get("b64_json"):
        write_image_bytes(output, base64.b64decode(str(item["b64_json"])))
        return
    if item.get("url"):
        response = httpx.get(str(item["url"]), timeout=120)
        response.raise_for_status()
        write_image_bytes(output, response.content)
        return
    raise ValueError("GPT Image response contains neither url nor b64_json")
