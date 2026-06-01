"""Unit tests for the BuildStage class in the pipeline.core_stages module."""

from unittest.mock import MagicMock, patch

import pytest

from energytrackr.pipeline.core_stages.build_stage import BuildStage


@pytest.fixture
def mock_config() -> MagicMock:
    """Fixture to create a mock configuration object for testing.

    Returns:
        MagicMock: A mock configuration object with execution plan settings.
    """
    config = MagicMock()
    config.execution_plan.compile_commands = ["make build", "make test"]
    config.execution_plan.ignore_failures = False
    return config


def test_build_stage_success() -> None:
    """Test the BuildStage when build succeeds."""
    mock_result = MagicMock()
    mock_result.returncode = 0

    context = {"build_failed": False, "abort_pipeline": False}

    with (
        patch("energytrackr.pipeline.core_stages.build_stage.run_command", return_value=mock_result),
        patch("energytrackr.config.config_store.Config.get_config") as mock_config,
    ):
        mock_config.return_value.execution_plan.compile_commands = ["make"]
        mock_config.return_value.execution_plan.ignore_failures = False
        stage = BuildStage()
        stage.run(context)

    assert context.get("build_failed") is not True
    assert context.get("abort_pipeline") is not True


def test_build_stage_fail_and_abort(monkeypatch: MagicMock, mock_config: MagicMock) -> None:
    """Test the BuildStage when build fails and abort is set to True."""
    monkeypatch.setattr("energytrackr.config.config_store.Config.get_config", lambda: mock_config)
    monkeypatch.setattr("energytrackr.utils.utils.run_command", lambda: MagicMock(returncode=1))

    context: dict[str, bool] = {}
    stage = BuildStage()
    stage.run(context)

    assert context["build_failed"] is True
    assert context["abort_pipeline"] is True


def test_build_stage_fail_ignore(monkeypatch: MagicMock, mock_config: MagicMock) -> None:
    """Test the BuildStage when build fails and ignore_failures is set to True."""
    mock_config.execution_plan.ignore_failures = True
    monkeypatch.setattr("energytrackr.config.config_store.Config.get_config", lambda: mock_config)
    monkeypatch.setattr("energytrackr.utils.utils.run_command", lambda: MagicMock(returncode=1))

    context: dict[str, bool] = {}
    stage = BuildStage()
    stage.run(context)

    assert context["build_failed"] is True
    assert context.get("abort_pipeline") is not True
