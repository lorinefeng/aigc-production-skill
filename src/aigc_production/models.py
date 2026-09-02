from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ImageRequest:
    prompt: str
    output_path: Path
    reference_images: list[Path] = field(default_factory=list)
    mask_image: Path | None = None
    size: str = "1024x1536"
    quality: str | None = None


@dataclass(slots=True)
class ProviderResult:
    provider: str
    model: str
    output_paths: list[Path]
    request_id: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
