from __future__ import annotations

import base64
import io
import mimetypes
from hashlib import sha256
from pathlib import Path

from PIL import Image, ImageOps


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".png":
        return "image/png"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def image_data_url(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type(path)};base64,{encoded}"


def write_image_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise ValueError(f"unsupported output extension: {suffix}")
    with Image.open(io.BytesIO(payload)) as source:
        image = ImageOps.exif_transpose(source)
        if suffix == ".png":
            image.save(path, format="PNG", optimize=True)
        elif suffix == ".webp":
            image.save(path, format="WEBP", quality=95, method=6)
        else:
            image.convert("RGB").save(path, format="JPEG", quality=95, optimize=True)


def validate_image(path: Path) -> dict[str, object]:
    with Image.open(path) as image:
        image.verify()
    with Image.open(path) as image:
        return {
            "format": str(image.format or "").upper(),
            "mode": image.mode,
            "size": [image.width, image.height],
            "sha256": sha256_file(path),
        }


def prepare_reference(
    source: Path,
    output: Path,
    *,
    max_long_edge: int = 2048,
    max_bytes: int = 1_500_000,
) -> Path:
    if source.resolve() == output.resolve():
        raise ValueError("reference output must not overwrite the source")
    if not source.is_file():
        raise FileNotFoundError(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as raw:
        image = ImageOps.exif_transpose(raw)
        image.thumbnail((max_long_edge, max_long_edge), Image.Resampling.LANCZOS)
        suffix = output.suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise ValueError("reference output must be PNG, JPEG, or WebP")

        for attempt in range(14):
            if suffix == ".png":
                image.save(output, format="PNG", optimize=True)
            elif suffix == ".webp":
                quality = max(55, 92 - attempt * 4)
                image.save(output, format="WEBP", quality=quality, method=6)
            else:
                quality = max(55, 92 - attempt * 4)
                image.convert("RGB").save(output, format="JPEG", quality=quality, optimize=True)
            if output.stat().st_size <= max_bytes and max(image.size) <= max_long_edge:
                return output
            new_size = (max(1, int(image.width * 0.88)), max(1, int(image.height * 0.88)))
            image = image.resize(new_size, Image.Resampling.LANCZOS)
    raise ValueError(f"could not prepare reference under {max_bytes} bytes")
