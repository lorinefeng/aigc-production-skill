from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from aigc_production.workflow import init_job


def make_png(
    path: Path, size: tuple[int, int] = (96, 128), color: tuple[int, int, int] = (40, 90, 160)
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, format="PNG")
    return path


@pytest.fixture()
def ready_job(tmp_path: Path) -> tuple[Path, Path]:
    job = tmp_path / "job"
    init_job(job)
    source = make_png(job / "reference_sources/primary.png", color=(120, 60, 20))
    make_png(job / "reference_inputs/primary.png", color=(120, 60, 20))
    assert source.is_file()
    spec_path = job / "production_spec.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec["blocking_unknowns"] = []
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    return job, spec_path
