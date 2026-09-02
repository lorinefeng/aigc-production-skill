from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    api_key: str
    base_url: str
    model: str


def seedream_config() -> ProviderConfig:
    return ProviderConfig(
        api_key=os.getenv("ARK_API_KEY", ""),
        base_url=os.getenv("VOLCENGINE_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3").rstrip("/"),
        model=os.getenv("SEEDREAM_MODEL", "doubao-seedream-5-0-pro-260628"),
    )


def gpt_image_config() -> ProviderConfig:
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    if not base_url.endswith("/v1"):
        base_url += "/v1"
    return ProviderConfig(
        api_key=os.getenv("OPENAI_API_KEY", ""),
        base_url=base_url,
        model=os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2"),
    )


def provider_availability() -> dict[str, bool]:
    return {
        "codex-imagegen": True,
        "seedream": bool(seedream_config().api_key),
        "gpt-image": bool(gpt_image_config().api_key),
    }
