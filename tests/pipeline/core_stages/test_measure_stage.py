"""Unit tests for the MeasureEnergyStage class."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from energytrackr.pipeline.core_stages.measure_stage import MeasureEnergyStage


class DummyCommit:
    """Dummy commit class for testing purposes."""

    def __init__(self, hexsha: str = "abc123") -> None:
        """Initialize a dummy commit object."""
        self.hexsha = hexsha


@pytest.fixture
def dummy_context(tmp_path: str) -> dict[str, str | bool]:
    """Fixture to provide a dummy context for testing.

    Args:
        tmp_path (str): The temporary path to create the repository.

    Returns:
        dict[str, str | bool]: A dictionary representing the context.
    """
    return {
        "commit": DummyCommit(),
        "repo_path": str(tmp_path / "workspace" / "repos" / "myrepo"),
        "build_failed": False,
        "abort_pipeline": False,
    }


@pytest.fixture
def mock_config() -> SimpleNamespace:
    """Fixture to provide a mock config object.

    Yields:
        SimpleNamespace: A mock configuration object.
    """

    class DummyConfig:
        class ExecutionPlan:
            test_command = "run-tests.sh"
            ignore_failures = False

        execution_plan = ExecutionPlan()
        repo = SimpleNamespace(url="some/repo", branch="main")
        cpu_thermal_file = "/sys/class/thermal/thermal_zone0/temp"

    with patch("energytrackr.pipeline.core_stages.measure_stage.Config.get_config", return_value=DummyConfig()):
        yield DummyConfig()


PERF_OUTPUT = "42.00 power/energy-pkg/\n5.00 power/energy-ram/\n1.23 seconds time elapsed"


@patch("energytrackr.pipeline.core_stages.measure_stage.read_cpu_temp")
@patch("energytrackr.pipeline.core_stages.measure_stage.run_command")
def test_measure_energy_success(
    mock_run: MagicMock, mock_temp: MagicMock, dummy_context: dict[str, str], mock_config: SimpleNamespace
) -> None:  # noqa: ARG001
    """Test the MeasureEnergyStage with a successful run."""
    mock_run.return_value = SimpleNamespace(returncode=0, stdout=PERF_OUTPUT, stderr="")
    mock_temp.side_effect = [55000, 57000]
    dummy_context["repo_path"] = str(Path(dummy_context["repo_path"]))
    Path(dummy_context["repo_path"]).mkdir(parents=True, exist_ok=True)

    stage = MeasureEnergyStage()
    stage.run(dummy_context)

    output_dir = Path(dummy_context["repo_path"]).parent.parent / "energy_measurements"
    output_files = list(output_dir.glob("energy_results_*.csv"))

    assert output_files
    lines = output_files[0].read_text().splitlines()
    assert lines[0] == "commit,energy-pkg,energy-ram,seconds,temp_before,temp_after"
    assert lines[1] == "abc123,42.00,5.00,1.23,55000,57000"


@patch("energytrackr.pipeline.core_stages.measure_stage.read_cpu_temp")
@patch("energytrackr.pipeline.core_stages.measure_stage.run_command")
def test_measure_energy_perf_failure_abort(
    mock_run: MagicMock,
    mock_temp: MagicMock,
    dummy_context: dict[str, str],
    mock_config: SimpleNamespace,  # noqa: ARG001
) -> None:
    """Test that the pipeline aborts if the test command fails."""
    mock_run.return_value = SimpleNamespace(returncode=1, stdout="", stderr="")
    mock_temp.return_value = 55000

    stage = MeasureEnergyStage()
    stage.run(dummy_context)

    assert dummy_context["abort_pipeline"] is True


@patch("energytrackr.pipeline.core_stages.measure_stage.read_cpu_temp")
@patch("energytrackr.pipeline.core_stages.measure_stage.run_command")
def test_measure_energy_ignore_failure_warning(
    mock_run: MagicMock,
    mock_temp: MagicMock,
    dummy_context: dict[str, str],
    mock_config: SimpleNamespace,
) -> None:
    """Test that the pipeline does not abort when ignore_failures is True."""
    mock_run.return_value = SimpleNamespace(returncode=1, stdout="", stderr="")
    mock_temp.side_effect = [55000, 57000]

    # change config to allow ignoring failures
    mock_config.execution_plan.ignore_failures = True

    stage = MeasureEnergyStage()
    stage.run(dummy_context)

    assert dummy_context["abort_pipeline"] is False


@patch("energytrackr.pipeline.core_stages.measure_stage.run_command")
def test_measure_energy_no_test_command(mock_run: MagicMock, dummy_context: dict[str, str]) -> None:
    """Test that the pipeline skips the measure stage if no test command is provided."""

    class DummyConfig:
        class ExecutionPlan:
            test_command = ""
            ignore_failures = False

        execution_plan = ExecutionPlan()

    with patch("energytrackr.pipeline.core_stages.measure_stage.Config.get_config", return_value=DummyConfig()):
        stage = MeasureEnergyStage()
        stage.run(dummy_context)

    mock_run.assert_not_called()


@patch("energytrackr.pipeline.core_stages.measure_stage.run_command")
def test_measure_energy_build_failed_skips(mock_run: MagicMock, dummy_context: dict[str, str]) -> None:
    """Test that the pipeline skips the measure stage if build failed."""
    dummy_context["build_failed"] = True

    class DummyConfig:
        class ExecutionPlan:
            test_command = "run"
            ignore_failures = False

        execution_plan = ExecutionPlan()

    with patch("energytrackr.pipeline.core_stages.measure_stage.Config.get_config", return_value=DummyConfig()):
        stage = MeasureEnergyStage()
        stage.run(dummy_context)

    mock_run.assert_not_called()


@patch("energytrackr.pipeline.core_stages.measure_stage.read_cpu_temp")
@patch("energytrackr.pipeline.core_stages.measure_stage.run_command")
def test_measure_energy_no_data_found(
    mock_run: MagicMock,
    mock_temp: MagicMock,
    dummy_context: dict[str, str],
    mock_config: SimpleNamespace,  # noqa: ARG001
) -> None:
    """Test that the pipeline aborts if no energy data is found."""
    mock_run.return_value = SimpleNamespace(returncode=0, stdout="no energy info here", stderr="")
    mock_temp.return_value = 55000

    stage = MeasureEnergyStage()
    stage.run(dummy_context)

    assert dummy_context["abort_pipeline"] is True


@patch("energytrackr.pipeline.core_stages.measure_stage.read_cpu_temp")
@patch("energytrackr.pipeline.core_stages.measure_stage.run_command")
def test_measure_energy_no_data_ignore_failure(
    mock_run: MagicMock,
    mock_temp: MagicMock,
    dummy_context: dict[str, str],
    mock_config: SimpleNamespace,
) -> None:
    """Test that the pipeline does not abort when ignore_failures is True."""
    mock_config.execution_plan.ignore_failures = True
    mock_run.return_value = SimpleNamespace(returncode=0, stdout="...", stderr="")
    mock_temp.side_effect = [55000, 57000]

    stage = MeasureEnergyStage()
    stage.run(dummy_context)

    assert dummy_context["abort_pipeline"] is False


@patch("energytrackr.pipeline.core_stages.measure_stage.read_cpu_temp")
@patch("energytrackr.pipeline.core_stages.measure_stage.run_command")
def test_measure_energy_perf_fails_but_data_saved(
    mock_run: MagicMock,
    mock_temp: MagicMock,
    dummy_context: dict[str, str],
    mock_config: SimpleNamespace,
) -> None:
    """Test that energy data is still extracted and saved even if perf fails but ignore_failures is True."""
    mock_config.execution_plan.ignore_failures = True
    mock_run.return_value = SimpleNamespace(returncode=1, stdout=PERF_OUTPUT, stderr="")
    mock_temp.side_effect = [55000, 57000]

    dummy_context["repo_path"] = str(Path(dummy_context["repo_path"]))
    Path(dummy_context["repo_path"]).mkdir(parents=True, exist_ok=True)

    stage = MeasureEnergyStage()
    stage.run(dummy_context)

    output_dir = Path(dummy_context["repo_path"]).parent.parent / "energy_measurements"
    output_files = list(output_dir.glob("energy_results_*.csv"))

    assert output_files
    lines = output_files[0].read_text().splitlines()
    assert lines[0] == "commit,energy-pkg,energy-ram,seconds,temp_before,temp_after"
    assert lines[1] == "abc123,42.00,5.00,1.23,55000,57000"
    assert dummy_context["abort_pipeline"] is False


@patch("energytrackr.pipeline.core_stages.measure_stage.read_cpu_temp")
@patch("energytrackr.pipeline.core_stages.measure_stage.run_command")
def test_measure_energy_temp_before_failure_abort(
    mock_run: MagicMock,
    mock_temp: MagicMock,
    dummy_context: dict[str, str],
    mock_config: SimpleNamespace,  # noqa: ARG001
) -> None:
    """Test that the pipeline aborts when temperature reading before measurement fails."""
    mock_temp.side_effect = OSError("thermal file not readable")

    stage = MeasureEnergyStage()
    stage.run(dummy_context)

    assert dummy_context["abort_pipeline"] is True
    mock_run.assert_not_called()


@patch("energytrackr.pipeline.core_stages.measure_stage.read_cpu_temp")
@patch("energytrackr.pipeline.core_stages.measure_stage.run_command")
def test_measure_energy_temp_after_failure_abort(
    mock_run: MagicMock,
    mock_temp: MagicMock,
    dummy_context: dict[str, str],
    mock_config: SimpleNamespace,  # noqa: ARG001
) -> None:
    """Test that the pipeline aborts when temperature reading after measurement fails."""
    mock_run.return_value = SimpleNamespace(returncode=0, stdout=PERF_OUTPUT, stderr="")
    mock_temp.side_effect = [55000, OSError("thermal file not readable")]

    stage = MeasureEnergyStage()
    stage.run(dummy_context)

    assert dummy_context["abort_pipeline"] is True


@patch("energytrackr.pipeline.core_stages.measure_stage.read_cpu_temp")
@patch("energytrackr.pipeline.core_stages.measure_stage.run_command")
def test_measure_energy_temp_failure_ignore(
    mock_run: MagicMock,
    mock_temp: MagicMock,
    dummy_context: dict[str, str],
    mock_config: SimpleNamespace,
) -> None:
    """Test that temperature read failures produce empty values when ignore_failures is True."""
    mock_config.execution_plan.ignore_failures = True
    mock_run.return_value = SimpleNamespace(returncode=0, stdout=PERF_OUTPUT, stderr="")
    mock_temp.side_effect = [OSError("fail"), OSError("fail")]

    dummy_context["repo_path"] = str(Path(dummy_context["repo_path"]))
    Path(dummy_context["repo_path"]).mkdir(parents=True, exist_ok=True)

    stage = MeasureEnergyStage()
    stage.run(dummy_context)

    assert dummy_context["abort_pipeline"] is False
    output_dir = Path(dummy_context["repo_path"]).parent.parent / "energy_measurements"
    output_files = list(output_dir.glob("energy_results_*.csv"))
    assert output_files
    lines = output_files[0].read_text().splitlines()
    assert lines[0] == "commit,energy-pkg,energy-ram,seconds,temp_before,temp_after"
    assert lines[1] == "abc123,42.00,5.00,1.23,,"
