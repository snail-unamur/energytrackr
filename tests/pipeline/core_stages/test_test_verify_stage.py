"""Unit tests for the TestVerifyStage class."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from energytrackr.pipeline.core_stages.test_verify_stage import TestVerifyStage


@pytest.fixture
def dummy_context() -> dict[str, bool]:
    """Fixture to provide a dummy context for testing.

    Returns:
        dict[str, bool]: A dictionary representing the context.
    """
    return {
        "build_failed": False,
        "abort_pipeline": False,
    }


def test_verify_skips_if_build_failed(dummy_context: dict[str, bool]) -> None:
    """Test that TestVerifyStage skips execution if build already failed."""
    dummy_context["build_failed"] = True

    with patch("energytrackr.pipeline.core_stages.test_verify_stage.run_command") as mock_run:
        with patch("energytrackr.pipeline.core_stages.test_verify_stage.Config.get_config"):
            stage = TestVerifyStage()
            stage.run(dummy_context)

    mock_run.assert_not_called()
    assert dummy_context["build_failed"] is True


def test_verify_skips_if_no_test_command(dummy_context: dict[str, bool]) -> None:
    """Test that TestVerifyStage skips execution if no test command is provided."""

    class DummyConfig:
        class ExecutionPlan:
            test_command = ""

        execution_plan = ExecutionPlan()

    with patch("energytrackr.pipeline.core_stages.test_verify_stage.run_command") as mock_run:
        with patch("energytrackr.pipeline.core_stages.test_verify_stage.Config.get_config", return_value=DummyConfig()):
            stage = TestVerifyStage()
            stage.run(dummy_context)

    mock_run.assert_not_called()
    assert dummy_context["build_failed"] is False


def test_verify_passes_if_tests_succeed(dummy_context: dict[str, bool]) -> None:
    """Test that TestVerifyStage does not mark build_failed when tests pass."""

    class DummyConfig:
        class ExecutionPlan:
            test_command = "mvn test"

        execution_plan = ExecutionPlan()

    with (
        patch(
            "energytrackr.pipeline.core_stages.test_verify_stage.run_command",
            return_value=SimpleNamespace(returncode=0),
        ),
        patch("energytrackr.pipeline.core_stages.test_verify_stage.Config.get_config", return_value=DummyConfig()),
    ):
        stage = TestVerifyStage()
        stage.run(dummy_context)

    assert dummy_context["build_failed"] is False
    assert dummy_context.get("abort_pipeline") is not True


def test_verify_sets_build_failed_if_tests_fail(dummy_context: dict[str, bool]) -> None:
    """Test that TestVerifyStage sets build_failed=True when tests fail."""

    class DummyConfig:
        class ExecutionPlan:
            test_command = "mvn test"

        execution_plan = ExecutionPlan()

    with (
        patch(
            "energytrackr.pipeline.core_stages.test_verify_stage.run_command",
            return_value=SimpleNamespace(returncode=1),
        ),
        patch("energytrackr.pipeline.core_stages.test_verify_stage.Config.get_config", return_value=DummyConfig()),
    ):
        stage = TestVerifyStage()
        stage.run(dummy_context)

    assert dummy_context["build_failed"] is True
    assert dummy_context.get("abort_pipeline") is not True
