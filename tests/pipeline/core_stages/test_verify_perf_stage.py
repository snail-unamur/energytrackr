"""Unit tests for the VerifyPerfStage class."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from energytrackr.config.config_model import PipelineConfig
from energytrackr.config.config_store import Config
from energytrackr.config.loader import load_pipeline_config
from energytrackr.pipeline.core_stages.verify_perf_stage import VerifyPerfStage


@pytest.fixture(autouse=True)
def reset_config_singleton() -> None:
    """Fixture to reset the config singleton before each test."""
    Config.reset()


# Sample minimal config for testing
def make_config(ignore_failures: bool = False) -> PipelineConfig:
    """Create a minimal config for testing.

    Args:
        ignore_failures (bool): Whether to ignore failures in the config.

    Returns:
        PipelineConfig: The created pipeline configuration.
    """
    config_dict = {
        "config_version": "1.0.0",
        "repo": {
            "url": "https://github.com/example/repo.git",
            "branch": "main",
            "clone_options": [],
        },
        "execution_plan": {
            "mode": "tests",
            "granularity": "commits",
            "test_command": "pytest",
            "test_command_path": ".",
            "ignore_failures": ignore_failures,
        },
        "limits": {
            "temperature_safe_limit": 90000,
            "energy_regression_percent": 15,
        },
        "tracked_file_extensions": ["py"],
        "cpu_thermal_file": "/sys/class/thermal/thermal_zone0/temp",
        "setup_commands": [],
        "results": {"file": "results.csv"},
    }
    config_path = Path("temp_config.yml")
    config_path.write_text(yaml.dump(config_dict))

    load_pipeline_config(str(config_path))
    return Config.get_config()


def test_perf_paranoid_is_minus_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """Should not abort when paranoid is -1."""
    Config.reset()
    monkeypatch.setattr(
        "energytrackr.pipeline.core_stages.verify_perf_stage.run_command",
        lambda *_args, **_kw: MagicMock(stdout="-1\n"),
    )

    make_config(ignore_failures=False)

    context = {}
    stage = VerifyPerfStage()
    stage.run(context)

    assert "abort_pipeline" not in context


def test_perf_paranoid_non_minus_one_abort(monkeypatch: pytest.MonkeyPatch) -> None:
    """Should abort pipeline when paranoid != -1 and ignore_failures = False."""
    monkeypatch.setattr(
        "energytrackr.pipeline.core_stages.verify_perf_stage.run_command",
        lambda *_args, **_kw: MagicMock(stdout="2\n"),
    )
    make_config(ignore_failures=False)

    context = {}
    stage = VerifyPerfStage()
    stage.run(context)

    assert context["abort_pipeline"] is True


def test_perf_paranoid_non_minus_one_ignore(monkeypatch: pytest.MonkeyPatch) -> None:
    """Should NOT abort when paranoid != -1 but ignore_failures = True."""
    monkeypatch.setattr("energytrackr.utils.utils.run_command", lambda *_args, **_kw: MagicMock(stdout="1\n"))
    make_config(ignore_failures=True)

    context = {}
    stage = VerifyPerfStage()
    stage.run(context)

    assert "abort_pipeline" not in context
