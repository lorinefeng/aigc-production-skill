from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import httpx
import typer
from PIL import __version__ as pillow_version

from .config import provider_availability
from .image_io import prepare_reference
from .workflow import (
    GateError,
    compile_asset_prompt,
    init_job,
    promote_candidate,
    record_review,
    register_candidate,
    run_asset,
    validate_delivery,
    validate_preflight,
)

app = typer.Typer(
    no_args_is_help=True,
    pretty_exceptions_enable=False,
    help="面向商业图片生产的规格、候选、QA 和交付门禁。",
)


def _print(data: object) -> None:
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2))


def _guard(callable_: object, *args: object, **kwargs: object) -> object:
    try:
        return callable_(*args, **kwargs)  # type: ignore[operator]
    except (GateError, OSError, ValueError, RuntimeError, httpx.HTTPError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


@app.command()
def doctor() -> None:
    """检查依赖、provider 和环境变量；不会显示密钥。"""
    availability = provider_availability()
    _print(
        {
            "status": "pass",
            "python": sys.version.split()[0],
            "pillow": pillow_version,
            "httpx": httpx.__version__,
            "providers": {
                "codex-imagegen": {"available": True, "execution": "Codex skill tool"},
                "seedream": {"available": availability["seedream"], "required_env": "ARK_API_KEY"},
                "gpt-image": {"available": availability["gpt-image"], "required_env": "OPENAI_API_KEY"},
            },
        }
    )


@app.command("init")
def init_command(
    job_dir: Annotated[Path, typer.Argument(help="新任务目录")],
    scenario: Annotated[str, typer.Option("--scenario", help="场景路由名称")] = "product-new-image",
) -> None:
    """建立不会覆盖现有规格的通用任务目录。"""
    _print(_guard(init_job, job_dir, scenario))


@app.command("prepare-reference")
def prepare_reference_command(
    source: Annotated[Path, typer.Argument(help="原始参考图")],
    output: Annotated[Path, typer.Argument(help="安全输入图；不得与原图相同")],
    max_edge: Annotated[int, typer.Option("--max-edge", min=256, max=2048)] = 2048,
    max_bytes: Annotated[int, typer.Option("--max-bytes", min=100_000, max=1_500_000)] = 1_500_000,
) -> None:
    """生成长边和体积受控的参考图，不覆盖原图。"""
    result = _guard(prepare_reference, source, output, max_long_edge=max_edge, max_bytes=max_bytes)
    _print({"status": "pass", "output": str(result)})


@app.command()
def preflight(spec: Annotated[Path, typer.Argument(help="production_spec.json")]) -> None:
    """在生成前检查事实、参考图角色、QA 和交付配置。"""
    _print(_guard(validate_preflight, spec))


@app.command("compile")
def compile_command(
    spec: Annotated[Path, typer.Argument(help="production_spec.json")],
    asset: Annotated[str, typer.Argument(help="资产 ID")],
    output: Annotated[Path | None, typer.Option("--output", help="可选 prompt 输出文件")] = None,
) -> None:
    """从唯一规格源编译某个资产的模型 prompt。"""
    prompt = _guard(compile_asset_prompt, spec, asset)
    if output is None:
        typer.echo(prompt, nl=False)
        return
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(str(prompt), encoding="utf-8")
    _print({"status": "pass", "output": str(output)})


@app.command()
def run(
    spec: Annotated[Path, typer.Argument(help="production_spec.json")],
    asset: Annotated[str, typer.Argument(help="资产 ID")],
    provider: Annotated[str, typer.Option("--provider", help="seedream 或 gpt-image")],
    mask: Annotated[Path | None, typer.Option("--mask", help="GPT Image 局部编辑 mask")] = None,
    size: Annotated[str, typer.Option("--size")] = "auto",
    quality: Annotated[str | None, typer.Option("--quality")] = None,
) -> None:
    """选择性调用 provider；输出只写入候选目录。"""
    _print(_guard(run_asset, spec, asset, provider, mask=mask, size=size, quality=quality))


@app.command("register-candidate")
def register_candidate_command(
    spec: Annotated[Path, typer.Argument(help="production_spec.json")],
    asset: Annotated[str, typer.Argument(help="资产 ID")],
    source: Annotated[Path, typer.Argument(help="外部生成结果")],
    provider: Annotated[str, typer.Option("--provider")] = "codex-imagegen",
) -> None:
    """登记 Codex ImageGen 或其他外部工具生成的候选。"""
    _print(_guard(register_candidate, spec, asset, source, provider))


@app.command()
def review(
    spec: Annotated[Path, typer.Argument(help="production_spec.json")],
    asset: Annotated[str, typer.Argument(help="资产 ID")],
    candidate: Annotated[Path, typer.Argument(help="候选相对任务目录的路径")],
    status: Annotated[str, typer.Argument(help="pass、fail 或 uncertain")],
    defect: Annotated[list[str] | None, typer.Option("--defect", help="可重复的缺陷标签")] = None,
    notes: Annotated[str, typer.Option("--notes")] = "",
) -> None:
    """记录内部视觉 QA；uncertain 自动按 fail 处理。"""
    _print(_guard(record_review, spec, asset, candidate, status, defects=defect, notes=notes))


@app.command()
def promote(
    spec: Annotated[Path, typer.Argument(help="production_spec.json")],
    asset: Annotated[str, typer.Argument(help="资产 ID")],
    candidate: Annotated[Path, typer.Argument(help="候选相对任务目录的路径")],
) -> None:
    """只把已通过且内容未变化的候选晋级到 generated/。"""
    _print(_guard(promote_candidate, spec, asset, candidate))


@app.command()
def delivery(spec: Annotated[Path, typer.Argument(help="production_spec.json")]) -> None:
    """校验最终数量、命名、真实格式、QA 和晋级链。"""
    _print(_guard(validate_delivery, spec))


if __name__ == "__main__":
    app()
