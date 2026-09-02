from __future__ import annotations

from .base import ImageProvider
from .gpt_image import GPTImageProvider
from .seedream import SeedreamProvider


def create_provider(name: str) -> ImageProvider:
    if name == "seedream":
        return SeedreamProvider()
    if name == "gpt-image":
        return GPTImageProvider()
    raise ValueError(f"unknown executable API provider: {name}")


__all__ = ["GPTImageProvider", "ImageProvider", "SeedreamProvider", "create_provider"]
