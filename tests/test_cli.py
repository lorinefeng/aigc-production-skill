from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from aigc_production.cli import app

runner = CliRunner()


def test_doctor_never_prints_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARK_API_KEY", "seed-secret-value")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret-value")
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert '"available": true' in result.stdout
    assert "seed-secret-value" not in result.stdout
    assert "openai-secret-value" not in result.stdout


def test_cli_init_and_expected_preflight_failure(tmp_path: Path) -> None:
    job = tmp_path / "job"
    result = runner.invoke(app, ["init", str(job)])
    assert result.exit_code == 0
    assert (job / "production_spec.json").is_file()
    preflight = runner.invoke(app, ["preflight", str(job / "production_spec.json")])
    assert preflight.exit_code == 1
    assert "blocking_unknowns" in preflight.stderr
