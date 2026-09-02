from __future__ import annotations

import json
import shutil
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from PIL import Image

from .image_io import sha256_file, validate_image, write_image_bytes
from .models import ImageRequest
from .providers import create_provider

REFERENCE_ROLES = {
    "identity",
    "product_structure",
    "wardrobe_structure",
    "color_material",
    "pose",
    "expression",
    "composition_camera",
    "background_lighting",
    "style",
    "typography",
    "edit_target",
    "negative_example",
}
AUTHORITIES = {"primary", "secondary", "context_only", "negative"}
CONFIDENCE_LEVELS = {"high", "medium", "low"}
QA_CATEGORIES = {
    "subject_identity",
    "composition_camera",
    "pose_anatomy",
    "product_wardrobe_structure",
    "color_material",
    "count_text_logo_topology",
    "background_lighting",
    "crop_delivery",
}
VERIFICATION_METHODS = {"visual_compare", "pixel_diff", "count", "ocr", "geometry", "human_review"}
REQUIRED_QA_POLICIES = {
    "uncertain_is_fail": True,
    "selective_rerun_only": True,
    "forbid_failed_output_as_reference": True,
    "batch_release_requires_calibration_pass": True,
    "client_approval_separate_from_internal_qa": True,
}
REVIEW_STATUSES = {"pass", "fail", "uncertain"}


class GateError(ValueError):
    """生产门禁未通过。"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def load_spec(spec_path: str | Path) -> tuple[Path, dict[str, Any]]:
    path = Path(spec_path).expanduser().resolve()
    if not path.is_file():
        raise GateError(f"任务规格不存在：{path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GateError(f"任务规格不是有效 JSON：{exc}") from exc
    if not isinstance(data, dict):
        raise GateError("任务规格顶层必须是 JSON object。")
    return path, data


def _resolved(base: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def _inside(path: Path, directory: Path) -> bool:
    try:
        path.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def _required_mapping(data: dict[str, Any], key: str, errors: list[str]) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        errors.append(f"{key} 必须是 object。")
        return {}
    return value


def _required_list(data: dict[str, Any], key: str, errors: list[str]) -> list[Any]:
    value = data.get(key)
    if not isinstance(value, list) or not value:
        errors.append(f"{key} 必须是非空数组。")
        return []
    return value


def _unique_ids(items: list[Any], label: str, errors: list[str]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"{label}[{index}] 必须是 object。")
            continue
        item_id = str(item.get("id", "")).strip()
        if not item_id:
            errors.append(f"{label}[{index}] 缺少 id。")
        elif item_id in indexed:
            errors.append(f"{label} 存在重复 id：{item_id}")
        else:
            indexed[item_id] = item
    return indexed


def validate_preflight(spec_path: str | Path) -> dict[str, Any]:
    path, spec = load_spec(spec_path)
    base = path.parent
    errors: list[str] = []
    warnings: list[str] = []

    if str(spec.get("schema_version", "")) != "1.0":
        errors.append("schema_version 必须为 1.0。")
    if not str(spec.get("job_id", "")).strip():
        errors.append("job_id 不能为空。")
    if not str(spec.get("use_case", "")).strip():
        errors.append("use_case 不能为空。")
    if spec.get("blocking_unknowns") not in ([], None):
        errors.append("blocking_unknowns 必须在生成前清零，不得自行猜测关键事实。")
    if not str(spec.get("coordinate_convention", "")).strip():
        errors.append("coordinate_convention 必须明确画面左右与主体解剖左右。")

    limits = _required_mapping(spec, "input_safety", errors)
    max_bytes = int(limits.get("max_reference_bytes", 1_500_000))
    max_edge = int(limits.get("max_reference_long_edge", 2048))
    references = _required_list(spec, "references", errors)
    ref_by_id = _unique_ids(references, "references", errors)
    for ref_id, reference in ref_by_id.items():
        role = str(reference.get("role", ""))
        authority = str(reference.get("authority", ""))
        confidence = str(reference.get("confidence", ""))
        allowed = reference.get("allowed_transfer")
        forbidden = reference.get("forbidden_transfer")
        if role not in REFERENCE_ROLES:
            errors.append(f"reference {ref_id} 的 role 无效：{role}")
        if authority not in AUTHORITIES:
            errors.append(f"reference {ref_id} 的 authority 无效：{authority}")
        if confidence not in CONFIDENCE_LEVELS:
            errors.append(f"reference {ref_id} 的 confidence 无效：{confidence}")
        if authority == "primary" and confidence != "high":
            errors.append(f"reference {ref_id} 是 primary 真值，confidence 必须为 high。")
        if not str(reference.get("description", "")).strip():
            errors.append(f"reference {ref_id} 缺少 description。")
        if not str(reference.get("evidence_region", "")).strip():
            errors.append(f"reference {ref_id} 缺少 evidence_region。")
        source_path = str(reference.get("source_path", "")).strip()
        source_url = str(reference.get("source_url", "")).strip()
        if not source_path and not source_url:
            errors.append(f"reference {ref_id} 必须记录 source_path 或 source_url。")
        if source_path and not _resolved(base, source_path).is_file():
            errors.append(f"reference {ref_id} 的 source_path 不存在：{_resolved(base, source_path)}")
        if not isinstance(allowed, list) or not allowed:
            errors.append(f"reference {ref_id} 的 allowed_transfer 必须是非空数组。")
            allowed = []
        if not isinstance(forbidden, list) or not forbidden:
            errors.append(f"reference {ref_id} 的 forbidden_transfer 必须是非空数组。")
            forbidden = []
        overlap = sorted(set(map(str, allowed)) & set(map(str, forbidden)))
        if overlap:
            errors.append(f"reference {ref_id} 的允许/禁止迁移冲突：{', '.join(overlap)}")
        input_path = str(reference.get("input_path", "")).strip()
        if not input_path:
            errors.append(f"reference {ref_id} 缺少 input_path。")
            continue
        image_path = _resolved(base, input_path)
        if not image_path.is_file():
            errors.append(f"reference {ref_id} 的 input_path 不存在：{image_path}")
            continue
        if image_path.stat().st_size > max_bytes:
            errors.append(f"reference {ref_id} 超过请求体安全大小：{image_path.stat().st_size} > {max_bytes}")
        try:
            with Image.open(image_path) as image:
                if max(image.size) > max_edge:
                    errors.append(f"reference {ref_id} 长边超限：{max(image.size)} > {max_edge}px")
        except OSError as exc:
            errors.append(f"reference {ref_id} 无法解析为图片：{exc}")

    invariants = _required_list(spec, "global_invariants", errors)
    invariant_by_id = _unique_ids(invariants, "global_invariants", errors)
    for invariant_id, invariant in invariant_by_id.items():
        category = str(invariant.get("category", ""))
        evidence_refs = invariant.get("evidence_refs")
        applies_to = invariant.get("applies_to")
        verification = str(invariant.get("verification", ""))
        if category not in QA_CATEGORIES:
            errors.append(f"invariant {invariant_id} 的 category 无效：{category}")
        if not str(invariant.get("description", "")).strip():
            errors.append(f"invariant {invariant_id} 缺少 description。")
        if not isinstance(evidence_refs, list) or not evidence_refs:
            errors.append(f"invariant {invariant_id} 必须绑定至少一个 evidence_refs。")
        else:
            missing = sorted(set(map(str, evidence_refs)) - set(ref_by_id))
            if missing:
                errors.append(f"invariant {invariant_id} 引用不存在的参考：{', '.join(missing)}")
        if applies_to != "all" and (not isinstance(applies_to, list) or not applies_to):
            errors.append(f"invariant {invariant_id} 的 applies_to 必须为 all 或非空 asset id 数组。")
        if verification not in VERIFICATION_METHODS:
            errors.append(f"invariant {invariant_id} 的 verification 无效：{verification}")
        if invariant.get("critical") is not True:
            warnings.append(f"invariant {invariant_id} 非 critical；确认其可以漂移。")

    qa = _required_mapping(spec, "qa", errors)
    required_categories = qa.get("required_categories")
    if not isinstance(required_categories, list) or not required_categories:
        errors.append("qa.required_categories 必须是非空数组。")
        required_categories = []
    invalid_categories = sorted(set(map(str, required_categories)) - QA_CATEGORIES)
    if invalid_categories:
        errors.append(f"qa.required_categories 含无效项：{', '.join(invalid_categories)}")
    for key, expected in REQUIRED_QA_POLICIES.items():
        if qa.get(key) is not expected:
            errors.append(f"qa.{key} 必须为 {str(expected).lower()}。")
    if int(qa.get("max_selective_reruns_per_asset", 0)) not in {1, 2}:
        errors.append("qa.max_selective_reruns_per_asset 必须为 1 或 2。")

    assets = _required_list(spec, "assets", errors)
    asset_by_id = _unique_ids(assets, "assets", errors)
    filenames: list[str] = []
    for asset_id, asset in asset_by_id.items():
        filename = str(asset.get("filename", "")).strip()
        filenames.append(filename)
        if not filename:
            errors.append(f"asset {asset_id} 缺少 filename。")
        elif Path(filename).name != filename:
            errors.append(f"asset {asset_id} filename 必须是单一文件名：{filename}")
        if not str(asset.get("asset_type", "")).strip():
            errors.append(f"asset {asset_id} 缺少 asset_type。")
        bindings = asset.get("reference_bindings")
        if not isinstance(bindings, list) or not bindings:
            errors.append(f"asset {asset_id} 必须绑定参考图。")
            bindings = []
        missing_refs = sorted(set(map(str, bindings)) - set(ref_by_id))
        if missing_refs:
            errors.append(f"asset {asset_id} 绑定不存在的参考：{', '.join(missing_refs)}")
        invariant_ids = asset.get("invariant_ids")
        if not isinstance(invariant_ids, list) or not invariant_ids:
            errors.append(f"asset {asset_id} 必须显式声明 invariant_ids。")
            invariant_ids = []
        missing_invariants = sorted(set(map(str, invariant_ids)) - set(invariant_by_id))
        if missing_invariants:
            errors.append(f"asset {asset_id} 引用不存在的 invariant：{', '.join(missing_invariants)}")
        for invariant_id, invariant in invariant_by_id.items():
            applies_to = invariant.get("applies_to")
            if (applies_to == "all" or asset_id in (applies_to or [])) and invariant_id not in invariant_ids:
                errors.append(f"asset {asset_id} 遗漏应用的 invariant：{invariant_id}")
        shot = asset.get("shot")
        if not isinstance(shot, dict):
            errors.append(f"asset {asset_id} 缺少 shot object。")
            shot = {}
        for field in ("framing", "camera_view", "subject_orientation", "gaze", "crop_basis"):
            if not str(shot.get(field, "")).strip():
                errors.append(f"asset {asset_id} 缺少 shot.{field}。")
        for field in ("action", "expression"):
            if not str(asset.get(field, "")).strip():
                errors.append(f"asset {asset_id} 缺少 {field}；不适用时写 not_applicable。")
        for field in ("change_scope", "preserve", "negative_constraints"):
            value = asset.get(field)
            if not isinstance(value, list) or not value:
                errors.append(f"asset {asset_id} 的 {field} 必须是非空数组。")
        checks = asset.get("acceptance_checks")
        if not isinstance(checks, list) or not checks:
            errors.append(f"asset {asset_id} 必须定义 acceptance_checks。")
            checks = []
        check_categories = {str(check.get("category", "")) for check in checks if isinstance(check, dict)}
        missing_categories = sorted(set(map(str, required_categories)) - check_categories)
        if missing_categories:
            errors.append(f"asset {asset_id} 验收项缺少类别：{', '.join(missing_categories)}")
        for index, check in enumerate(checks):
            if not isinstance(check, dict):
                errors.append(f"asset {asset_id} acceptance_checks[{index}] 必须是 object。")
                continue
            if str(check.get("category", "")) not in QA_CATEGORIES:
                errors.append(f"asset {asset_id} acceptance_checks[{index}] category 无效。")
            if not str(check.get("description", "")).strip():
                errors.append(f"asset {asset_id} acceptance_checks[{index}] 缺少 description。")

    output = _required_mapping(spec, "output", errors)
    expected_files = output.get("expected_files")
    allowed_extensions = output.get("allowed_extensions")
    if not isinstance(expected_files, list) or not expected_files:
        errors.append("output.expected_files 必须是非空数组。")
        expected_files = []
    if len(set(map(str, expected_files))) != len(expected_files):
        errors.append("output.expected_files 不得重复。")
    if len(set(filenames)) != len(filenames):
        errors.append("assets[].filename 不得重复。")
    if set(map(str, expected_files)) != set(filenames):
        errors.append("output.expected_files 必须与 assets[].filename 完全一致。")
    if not isinstance(allowed_extensions, list) or not allowed_extensions:
        errors.append("output.allowed_extensions 必须是非空数组。")
        allowed_extensions = []
    normalized_exts = {str(ext).lower() for ext in allowed_extensions}
    for filename in filenames:
        if filename and Path(filename).suffix.lower() not in normalized_exts:
            errors.append(f"asset 文件格式不在交付白名单：{filename}")
    candidate_dir = str(output.get("candidate_directory", "")).strip()
    final_dir = str(output.get("final_directory", "")).strip()
    if not candidate_dir or not final_dir:
        errors.append("output 必须同时定义 candidate_directory 和 final_directory。")
    else:
        candidate_path = _resolved(base, candidate_dir)
        final_path = _resolved(base, final_dir)
        if (
            candidate_path == final_path
            or _inside(candidate_path, final_path)
            or _inside(final_path, candidate_path)
        ):
            errors.append("候选目录与最终交付目录必须独立，不得相同或彼此嵌套。")
    if output.get("final_directory_only_accepted_assets") is not True:
        errors.append("output.final_directory_only_accepted_assets 必须为 true。")
    if not str(output.get("review_file", "")).strip():
        errors.append("output.review_file 不能为空。")

    calibration_id = str(qa.get("calibration_asset_id", ""))
    if calibration_id not in asset_by_id:
        errors.append("qa.calibration_asset_id 必须指向存在的 asset。")

    if errors:
        raise GateError("AIGC 生成前预检失败：\n- " + "\n- ".join(errors))
    return {
        "status": "pass",
        "job_id": spec["job_id"],
        "reference_count": len(ref_by_id),
        "invariant_count": len(invariant_by_id),
        "asset_count": len(asset_by_id),
        "calibration_asset_id": calibration_id,
        "warnings": warnings,
    }


def compile_asset_prompt(spec_path: str | Path, asset_id: str) -> str:
    validate_preflight(spec_path)
    _, spec = load_spec(spec_path)
    ref_by_id = {str(item["id"]): item for item in spec["references"]}
    invariant_by_id = {str(item["id"]): item for item in spec["global_invariants"]}
    asset = next((item for item in spec["assets"] if str(item["id"]) == asset_id), None)
    if asset is None:
        raise GateError(f"不存在 asset：{asset_id}")
    refs: list[str] = []
    for index, ref_id in enumerate(asset["reference_bindings"], start=1):
        reference = ref_by_id[str(ref_id)]
        refs.append(
            f"- Reference image {index} ({ref_id}): role={reference['role']}; "
            f"authority={reference['authority']}; confidence={reference['confidence']}; "
            f"evidence region={reference['evidence_region']}; "
            f"use only for {', '.join(reference['allowed_transfer'])}; "
            f"never copy {', '.join(reference['forbidden_transfer'])}. Evidence: {reference['description']}"
        )
    invariants = [
        f"- [{invariant_by_id[item]['category']}] {invariant_by_id[item]['description']}"
        for item in asset["invariant_ids"]
    ]
    checks = [f"- [{check['category']}] {check['description']}" for check in asset["acceptance_checks"]]
    shot = asset["shot"]
    return (
        "\n".join(
            [
                f"Use case: {spec['use_case']}",
                f"Asset ID: {asset_id}",
                f"Asset type: {asset['asset_type']}",
                "",
                "Reference roles and transfer boundaries:",
                *refs,
                "",
                "Required result:",
                f"- Action: {asset['action']}",
                f"- Expression: {asset['expression']}",
                f"- Framing: {shot['framing']}",
                f"- Camera view: {shot['camera_view']}",
                f"- Subject orientation: {shot['subject_orientation']}",
                f"- Gaze: {shot['gaze']}",
                f"- Crop basis: {shot['crop_basis']}",
                f"- Coordinate convention: {spec['coordinate_convention']}",
                "",
                "Hard invariants:",
                *invariants,
                "",
                "Change only:",
                *[f"- {item}" for item in asset["change_scope"]],
                "",
                "Preserve unchanged:",
                *[f"- {item}" for item in asset["preserve"]],
                "",
                "Hard exclusions:",
                *[f"- {item}" for item in asset["negative_constraints"]],
                "",
                "Acceptance checks:",
                *checks,
                "",
                "Generate one candidate only. Never promote it before every acceptance check passes.",
            ]
        )
        + "\n"
    )


def default_spec(job_id: str, scenario: str) -> dict[str, Any]:
    checks = [
        {"category": category, "description": f"Confirm {category} against authoritative references."}
        for category in sorted(QA_CATEGORIES)
    ]
    return {
        "schema_version": "1.0",
        "job_id": job_id,
        "use_case": scenario,
        "coordinate_convention": (
            "Image-left/right means viewer coordinates; anatomical left/right is stated explicitly."
        ),
        "blocking_unknowns": [
            "Replace this item with resolved facts, then set blocking_unknowns to an empty list."
        ],
        "input_safety": {"max_reference_bytes": 1_500_000, "max_reference_long_edge": 2048},
        "references": [
            {
                "id": "ref-primary",
                "role": "product_structure",
                "authority": "primary",
                "confidence": "high",
                "description": "Describe the authoritative structure visible in this source.",
                "evidence_region": "Describe the exact visible region.",
                "source_path": "reference_sources/primary.png",
                "input_path": "reference_inputs/primary.png",
                "allowed_transfer": ["authoritative product structure"],
                "forbidden_transfer": ["background", "watermark", "unrelated props"],
            }
        ],
        "global_invariants": [
            {
                "id": "inv-structure",
                "category": "product_wardrobe_structure",
                "description": "Preserve the authoritative product or wardrobe structure exactly.",
                "evidence_refs": ["ref-primary"],
                "applies_to": "all",
                "verification": "visual_compare",
                "critical": True,
            }
        ],
        "qa": {
            "required_categories": sorted(QA_CATEGORIES),
            "uncertain_is_fail": True,
            "selective_rerun_only": True,
            "forbid_failed_output_as_reference": True,
            "batch_release_requires_calibration_pass": True,
            "client_approval_separate_from_internal_qa": True,
            "max_selective_reruns_per_asset": 2,
            "calibration_asset_id": "01",
        },
        "assets": [
            {
                "id": "01",
                "filename": "01.png",
                "asset_type": "commercial_static_image",
                "reference_bindings": ["ref-primary"],
                "invariant_ids": ["inv-structure"],
                "action": "Describe the requested action.",
                "expression": "not_applicable",
                "shot": {
                    "framing": "Describe the framing.",
                    "camera_view": "Describe the camera view.",
                    "subject_orientation": "Describe subject orientation.",
                    "gaze": "not_applicable",
                    "crop_basis": "Describe the crop reference.",
                },
                "change_scope": ["Only the requested production change."],
                "preserve": ["All confirmed facts and critical invariants."],
                "negative_constraints": ["No invented text, logo, parts, people, or materials."],
                "acceptance_checks": checks,
            }
        ],
        "output": {
            "candidate_directory": "candidates",
            "final_directory": "generated",
            "expected_files": ["01.png"],
            "allowed_extensions": [".png"],
            "final_directory_only_accepted_assets": True,
            "review_file": "review/summary.json",
        },
    }


def init_job(job_dir: str | Path, scenario: str = "product-new-image") -> dict[str, str]:
    root = Path(job_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    spec_path = root / "production_spec.json"
    if spec_path.exists():
        raise GateError(f"不会覆盖已有任务规格：{spec_path}")
    for name in (
        "reference_sources",
        "reference_inputs",
        "candidates",
        "generated",
        "prompts",
        "review",
        "supporting_files/rejected_versions",
    ):
        (root / name).mkdir(parents=True, exist_ok=True)
    spec = default_spec(root.name or "aigc-job", scenario)
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    review = {
        "schema_version": "1.0",
        "status": "pending_internal_qa",
        "client_approval": False,
        "reviews": [],
        "promotions": [],
    }
    (root / "review/summary.json").write_text(
        json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    manifest = {"schema_version": "1.0", "job_id": spec["job_id"], "entries": []}
    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {"job_directory": str(root), "spec": str(spec_path)}


def _asset(spec: dict[str, Any], asset_id: str) -> dict[str, Any]:
    asset = next((item for item in spec["assets"] if str(item["id"]) == asset_id), None)
    if asset is None:
        raise GateError(f"不存在 asset：{asset_id}")
    return asset


def _read_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists() and default is not None:
        return deepcopy(default)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GateError(f"无法读取记录文件 {path}：{exc}") from exc
    if not isinstance(data, dict):
        raise GateError(f"记录文件顶层必须是 object：{path}")
    return data


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _manifest_path(spec_path: Path) -> Path:
    return spec_path.parent / "manifest.json"


def _append_manifest(spec_path: Path, entry: dict[str, Any]) -> None:
    manifest_path = _manifest_path(spec_path)
    manifest = _read_json(
        manifest_path,
        {"schema_version": "1.0", "job_id": spec_path.parent.name, "entries": []},
    )
    entries = manifest.setdefault("entries", [])
    if not isinstance(entries, list):
        raise GateError("manifest.entries 必须是数组。")
    _assert_no_secrets(entry)
    entries.append({**entry, "recorded_at": _now()})
    _write_json(manifest_path, manifest)


def _assert_no_secrets(value: Any, path: str = "manifest") -> None:
    allowed_token_counters = {
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cached_tokens",
        "image_tokens",
        "text_tokens",
    }
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).lower().replace("-", "_")
            sensitive = (
                normalized in {"api_key", "apikey", "authorization", "token", "private_key"}
                or normalized.endswith("_api_key")
                or "secret" in normalized
                or "password" in normalized
                or "authorization" in normalized
                or (normalized.endswith("_token") and normalized not in allowed_token_counters)
            )
            if sensitive:
                raise GateError(f"manifest 不得写入密钥字段：{path}.{key}")
            _assert_no_secrets(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _assert_no_secrets(nested, f"{path}[{index}]")
    elif isinstance(value, str) and value.lower().startswith(("bearer ", "sk-")):
        raise GateError(f"manifest 不得写入疑似密钥值：{path}")


def register_candidate(
    spec_path: str | Path,
    asset_id: str,
    source: str | Path,
    provider: str = "codex-imagegen",
) -> dict[str, Any]:
    validate_preflight(spec_path)
    path, spec = load_spec(spec_path)
    asset = _asset(spec, asset_id)
    source_path = Path(source).expanduser().resolve()
    if not source_path.is_file():
        raise GateError(f"候选源文件不存在：{source_path}")
    validate_image(source_path)
    candidate_dir = _resolved(path.parent, spec["output"]["candidate_directory"])
    final_dir = _resolved(path.parent, spec["output"]["final_directory"])
    if _inside(source_path, final_dir):
        raise GateError("不能从最终交付目录反向登记候选。")
    candidate_dir.mkdir(parents=True, exist_ok=True)
    safe_provider = "".join(char if char.isalnum() or char in "-_" else "-" for char in provider).strip("-")
    candidate_id = uuid.uuid4().hex[:12]
    target = candidate_dir / f"{asset_id}__{safe_provider or 'external'}__{candidate_id}.png"
    write_image_bytes(target, source_path.read_bytes())
    record = {
        "candidate_id": candidate_id,
        "asset_id": asset_id,
        "provider": provider,
        "model": None,
        "candidate": str(target.relative_to(path.parent)),
        "candidate_sha256": sha256_file(target),
        "target_filename": asset["filename"],
        "usage": {},
    }
    _append_manifest(path, record)
    return record


def run_asset(
    spec_path: str | Path,
    asset_id: str,
    provider_name: str,
    *,
    mask: str | Path | None = None,
    size: str = "auto",
    quality: str | None = None,
) -> dict[str, Any]:
    validate_preflight(spec_path)
    path, spec = load_spec(spec_path)
    asset = _asset(spec, asset_id)
    reviews = _review_data(path, spec)
    if any(
        item.get("asset_id") == asset_id and item.get("status") == "pass"
        for item in reviews.get("reviews", [])
    ):
        raise GateError(f"asset {asset_id} 已有通过项；按选择性重跑规则不得再次运行。")
    calibration_id = str(spec["qa"]["calibration_asset_id"])
    calibration_passed = any(
        item.get("asset_id") == calibration_id and item.get("effective_status") == "pass"
        for item in reviews.get("reviews", [])
    )
    if asset_id != calibration_id and not calibration_passed:
        raise GateError(f"校准资产 {calibration_id} 尚未通过，不能运行 {asset_id}。")
    reruns = sum(
        1
        for item in reviews.get("reviews", [])
        if item.get("asset_id") == asset_id and item.get("status") != "pass"
    )
    limit = int(spec["qa"]["max_selective_reruns_per_asset"])
    if reruns >= limit:
        raise GateError(f"asset {asset_id} 已达到自动重跑上限 {limit}。请人工调整策略或切换 provider。")
    ref_by_id = {str(item["id"]): item for item in spec["references"]}
    references = [
        _resolved(path.parent, ref_by_id[str(ref_id)]["input_path"]) for ref_id in asset["reference_bindings"]
    ]
    prompt = compile_asset_prompt(path, asset_id)
    prompt_path = path.parent / "prompts" / f"{asset_id}.txt"
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(prompt, encoding="utf-8")
    candidate_dir = _resolved(path.parent, spec["output"]["candidate_directory"])
    candidate_dir.mkdir(parents=True, exist_ok=True)
    candidate_id = uuid.uuid4().hex[:12]
    output = candidate_dir / f"{asset_id}__{provider_name}__{candidate_id}.png"
    provider = create_provider(provider_name)
    result = provider.generate(
        ImageRequest(
            prompt=prompt,
            reference_images=references,
            mask_image=Path(mask).expanduser().resolve() if mask else None,
            size=size,
            quality=quality,
            output_path=output,
        )
    )
    validate_image(output)
    record = {
        "candidate_id": candidate_id,
        "asset_id": asset_id,
        "provider": result.provider,
        "model": result.model,
        "request_id": result.request_id,
        "candidate": str(output.relative_to(path.parent)),
        "candidate_sha256": sha256_file(output),
        "target_filename": asset["filename"],
        "prompt_file": str(prompt_path.relative_to(path.parent)),
        "prompt_sha256": sha256(prompt.encode("utf-8")).hexdigest(),
        "usage": result.usage,
    }
    _append_manifest(path, record)
    return record


def _review_data(path: Path, spec: dict[str, Any]) -> dict[str, Any]:
    review_path = _resolved(path.parent, spec["output"]["review_file"])
    return _read_json(
        review_path,
        {
            "schema_version": "1.0",
            "status": "pending_internal_qa",
            "client_approval": False,
            "reviews": [],
            "promotions": [],
        },
    )


def _candidate_path(path: Path, spec: dict[str, Any], candidate: str | Path) -> Path:
    candidate_dir = _resolved(path.parent, spec["output"]["candidate_directory"])
    candidate_path = _resolved(path.parent, candidate)
    if not _inside(candidate_path, candidate_dir):
        raise GateError(f"候选必须位于 candidate_directory：{candidate_path}")
    if not candidate_path.is_file():
        raise GateError(f"候选文件不存在：{candidate_path}")
    return candidate_path


def record_review(
    spec_path: str | Path,
    asset_id: str,
    candidate: str | Path,
    status: str,
    *,
    defects: list[str] | None = None,
    notes: str = "",
) -> dict[str, Any]:
    validate_preflight(spec_path)
    path, spec = load_spec(spec_path)
    _asset(spec, asset_id)
    if status not in REVIEW_STATUSES:
        raise GateError(f"review status 必须是 {', '.join(sorted(REVIEW_STATUSES))}。")
    candidate_path = _candidate_path(path, spec, candidate)
    manifest = _read_json(_manifest_path(path), {"entries": []})
    known = any(
        item.get("asset_id") == asset_id
        and _resolved(path.parent, str(item.get("candidate", ""))) == candidate_path
        for item in manifest.get("entries", [])
        if isinstance(item, dict)
    )
    if not known:
        raise GateError("候选尚未登记到 manifest；先运行 run 或 register-candidate。")
    review_path = _resolved(path.parent, spec["output"]["review_file"])
    review = _review_data(path, spec)
    reviews = review.setdefault("reviews", [])
    if not isinstance(reviews, list):
        raise GateError("review.reviews 必须是数组。")
    record = {
        "review_id": uuid.uuid4().hex[:12],
        "asset_id": asset_id,
        "candidate": str(candidate_path.relative_to(path.parent)),
        "candidate_sha256": sha256_file(candidate_path),
        "status": status,
        "effective_status": "fail" if status == "uncertain" else status,
        "defects": defects or [],
        "notes": notes,
        "reviewed_at": _now(),
    }
    reviews.append(record)
    passed_assets = {item.get("asset_id") for item in reviews if item.get("effective_status") == "pass"}
    expected_assets = {str(item["id"]) for item in spec["assets"]}
    review["status"] = "internal_qa_pass" if passed_assets == expected_assets else "internal_qa_incomplete"
    if not isinstance(review.get("client_approval"), bool):
        review["client_approval"] = False
    _write_json(review_path, review)
    return record


def promote_candidate(spec_path: str | Path, asset_id: str, candidate: str | Path) -> dict[str, Any]:
    validate_preflight(spec_path)
    path, spec = load_spec(spec_path)
    asset = _asset(spec, asset_id)
    candidate_path = _candidate_path(path, spec, candidate)
    review_path = _resolved(path.parent, spec["output"]["review_file"])
    review = _review_data(path, spec)
    matching = [
        item
        for item in review.get("reviews", [])
        if item.get("asset_id") == asset_id
        and item.get("effective_status") == "pass"
        and _resolved(path.parent, str(item.get("candidate", ""))) == candidate_path
        and item.get("candidate_sha256") == sha256_file(candidate_path)
    ]
    if not matching:
        raise GateError("只有内容未变化且内部 QA 已通过的候选才能晋级。")
    final_dir = _resolved(path.parent, spec["output"]["final_directory"])
    final_dir.mkdir(parents=True, exist_ok=True)
    target = final_dir / asset["filename"]
    if target.exists() and sha256_file(target) != sha256_file(candidate_path):
        raise GateError(f"目标已存在且内容不同，不会静默覆盖：{target}")
    if not target.exists():
        shutil.copy2(candidate_path, target)
    validate_image(target)
    promotions = review.setdefault("promotions", [])
    if not isinstance(promotions, list):
        raise GateError("review.promotions 必须是数组。")
    record = {
        "asset_id": asset_id,
        "candidate": str(candidate_path.relative_to(path.parent)),
        "candidate_sha256": sha256_file(candidate_path),
        "final_file": str(target.relative_to(path.parent)),
        "final_sha256": sha256_file(target),
        "promoted_at": _now(),
    }
    if not any(
        item.get("final_file") == record["final_file"] and item.get("final_sha256") == record["final_sha256"]
        for item in promotions
    ):
        promotions.append(record)
    _write_json(review_path, review)
    return record


def validate_delivery(spec_path: str | Path) -> dict[str, Any]:
    preflight = validate_preflight(spec_path)
    path, spec = load_spec(spec_path)
    output = spec["output"]
    final_dir = _resolved(path.parent, output["final_directory"])
    if not final_dir.is_dir():
        raise GateError(f"最终交付目录不存在：{final_dir}")
    expected = set(map(str, output["expected_files"]))
    actual = {entry.name for entry in final_dir.iterdir()}
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        details = []
        if missing:
            details.append("缺少：" + ", ".join(missing))
        if extra:
            details.append("多余：" + ", ".join(extra))
        raise GateError("最终交付目录与 expected_files 不一致；" + "；".join(details))
    allowed_formats = {str(item).upper().lstrip(".") for item in output["allowed_extensions"]}
    review = _review_data(path, spec)
    if not isinstance(review.get("client_approval"), bool):
        raise GateError("review_file 必须显式记录 boolean client_approval。")
    if review.get("status") != "internal_qa_pass":
        raise GateError("全部最终文件必须先通过内部 QA。")
    promotions = review.get("promotions", [])
    files: list[dict[str, Any]] = []
    for filename in sorted(expected):
        image_path = final_dir / filename
        if not image_path.is_file():
            raise GateError(f"最终交付项不是文件：{image_path}")
        try:
            with Image.open(image_path) as image:
                image_format = str(image.format or "").upper()
                if image_format not in allowed_formats:
                    raise GateError(f"{filename} 实际格式 {image_format} 不在白名单。")
                record = next(
                    (
                        item
                        for item in promotions
                        if item.get("final_file") == str(image_path.relative_to(path.parent))
                        and item.get("final_sha256") == sha256_file(image_path)
                    ),
                    None,
                )
                if record is None:
                    raise GateError(f"{filename} 没有可验证的通过候选晋级记录。")
                files.append(
                    {"file": filename, "format": image_format, "mode": image.mode, "size": list(image.size)}
                )
        except OSError as exc:
            raise GateError(f"无法读取最终交付图 {filename}：{exc}") from exc
    return {
        **preflight,
        "status": "pass",
        "final_directory": str(final_dir),
        "delivered_count": len(files),
        "files": files,
        "internal_qa_status": review["status"],
        "client_approval": review["client_approval"],
    }
