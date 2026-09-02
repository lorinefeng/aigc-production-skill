from __future__ import annotations

import json
from pathlib import Path

import pytest

from aigc_production.workflow import (
    GateError,
    _append_manifest,
    compile_asset_prompt,
    init_job,
    promote_candidate,
    record_review,
    register_candidate,
    validate_delivery,
    validate_preflight,
)

from .conftest import make_png


def test_init_never_overwrites_existing_spec(tmp_path: Path) -> None:
    root = tmp_path / "new-job"
    result = init_job(root, "batch-delivery")
    assert Path(result["spec"]).is_file()
    assert (root / "generated").is_dir()
    with pytest.raises(GateError, match="不会覆盖"):
        init_job(root)


def test_preflight_and_prompt_include_reference_contract(ready_job: tuple[Path, Path]) -> None:
    _, spec_path = ready_job
    result = validate_preflight(spec_path)
    prompt = compile_asset_prompt(spec_path, "01")
    assert result["status"] == "pass"
    assert "role=product_structure" in prompt
    assert "never copy background, watermark, unrelated props" in prompt
    assert "Hard invariants" in prompt


def test_preflight_blocks_unknowns_and_reference_contract_conflicts(ready_job: tuple[Path, Path]) -> None:
    _, spec_path = ready_job
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec["blocking_unknowns"] = ["missing label truth"]
    spec["references"][0]["forbidden_transfer"].append("authoritative product structure")
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    with pytest.raises(GateError) as exc:
        validate_preflight(spec_path)
    assert "blocking_unknowns" in str(exc.value)
    assert "允许/禁止迁移冲突" in str(exc.value)


def test_candidate_review_promote_delivery_chain(ready_job: tuple[Path, Path], tmp_path: Path) -> None:
    job, spec_path = ready_job
    external = make_png(tmp_path / "external.webp", color=(1, 2, 3))
    registered = register_candidate(spec_path, "01", external, "codex-imagegen")
    candidate = registered["candidate"]
    review = record_review(spec_path, "01", candidate, "pass", notes="all checks completed")
    promoted = promote_candidate(spec_path, "01", candidate)
    delivery = validate_delivery(spec_path)
    assert review["effective_status"] == "pass"
    assert promoted["final_file"] == "generated/01.png"
    assert delivery["delivered_count"] == 1
    assert {item.name for item in (job / "generated").iterdir()} == {"01.png"}
    manifest_text = (job / "manifest.json").read_text(encoding="utf-8")
    assert "codex-imagegen" in manifest_text
    assert "api_key" not in manifest_text.lower()


def test_uncertain_cannot_promote(ready_job: tuple[Path, Path], tmp_path: Path) -> None:
    _, spec_path = ready_job
    external = make_png(tmp_path / "candidate.png")
    candidate = register_candidate(spec_path, "01", external)["candidate"]
    review = record_review(spec_path, "01", candidate, "uncertain", defects=["hand anatomy"])
    assert review["effective_status"] == "fail"
    with pytest.raises(GateError, match="只有内容未变化"):
        promote_candidate(spec_path, "01", candidate)


def test_delivery_rejects_extra_file(ready_job: tuple[Path, Path], tmp_path: Path) -> None:
    job, spec_path = ready_job
    candidate = register_candidate(spec_path, "01", make_png(tmp_path / "candidate.png"))["candidate"]
    record_review(spec_path, "01", candidate, "pass")
    promote_candidate(spec_path, "01", candidate)
    (job / "generated/notes.txt").write_text("not deliverable", encoding="utf-8")
    with pytest.raises(GateError, match="多余"):
        validate_delivery(spec_path)


def test_promote_detects_candidate_tampering(ready_job: tuple[Path, Path], tmp_path: Path) -> None:
    job, spec_path = ready_job
    candidate = register_candidate(spec_path, "01", make_png(tmp_path / "candidate.png"))["candidate"]
    record_review(spec_path, "01", candidate, "pass")
    make_png(job / candidate, color=(255, 0, 0))
    with pytest.raises(GateError, match="内容未变化"):
        promote_candidate(spec_path, "01", candidate)


def test_manifest_rejects_nested_secret_fields(ready_job: tuple[Path, Path]) -> None:
    _, spec_path = ready_job
    with pytest.raises(GateError, match="不得写入密钥字段"):
        _append_manifest(spec_path, {"usage": {"authorization_token": "hidden"}})


def test_manifest_allows_token_usage_counters(ready_job: tuple[Path, Path]) -> None:
    job, spec_path = ready_job
    _append_manifest(spec_path, {"usage": {"input_tokens": 12, "output_tokens": 34}})
    manifest = json.loads((job / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["entries"][-1]["usage"]["output_tokens"] == 34
