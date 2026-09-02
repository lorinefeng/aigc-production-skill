from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import ImageRequest, ProviderResult


class ImageProvider(ABC):
    name: str

    @abstractmethod
    def generate(self, request: ImageRequest) -> ProviderResult:
        """Generate or edit one candidate without exposing credentials."""
