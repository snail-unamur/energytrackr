"""Unit tests for the configuration module."""

from pathlib import Path

import pytest
import yaml

from energytrackr.config.config_model import ExecutionPlanDefinition, GranularityEnum, ModeEnum, PipelineConfig
from energytrackr.config.config_store import Config
from energytrackr.config.loader import load_pipeline_config
from energytrackr.utils.exceptions import ConfigurationSingletonAlreadySetError, ConfigurationSingletonNotSetError


def test_compile_commands_required_for_benchmarks() -> None:
    """Test that benchmarks mode requires compile_commands."""
    with pytest.raises(ValueError, match="compile_commands must be provided"):
        ExecutionPlanDefinition(
            mode=ModeEnum.BENCHMARKS,
            granularity=GranularityEnum.COMMITS,
            test_command="run-tests.sh",
            test_command_path=".",
            ignore_failures=True,
            num_commits=5,
            num_runs=1,
            num_repeats=1,
            batch_size=10,
            randomize_tasks=False,
            # compile_commands is omitted on purpose!
        )


def test_load_pipeline_config() -> None:
    """Test the `load_pipeline_config` function to ensure it correctly loads a pipeline configuration from a YAML file.

    Steps:
    1. Copy the contents of a sample configuration file (`sample_conf.yml`) to a
        temporary file in the provided `tmp_path`.
    2. Use the `load_pipeline_config` function to load the configuration from the
        temporary file.
    3. Validate that the loaded configuration matches the expected values by
        asserting specific attributes of the `PipelineConfig` object.

    Assertions:
    - The `repo.url` attribute of the loaded configuration should match the expected
      repository URL.
    - The `execution_plan.num_commits` attribute should match the expected number
      of commits.
    """
    # Copy sample_conf.yml to a temp path
    Config.reset()
    sample_path = Path("tests/config/sample_conf.yml")

    # Load the config using your app code
    load_pipeline_config(str(sample_path))

    # Validate it loaded correctly
    config_obj: PipelineConfig = Config.get_config()
    assert config_obj.repo.url == "https://github.com/example/project.git"
    expected_num_commits = 5
    assert config_obj.execution_plan.num_commits == expected_num_commits


def test_config_singleton_identity() -> None:
    """Ensure that Config always returns the same instance."""
    instance_1 = Config()
    instance_2 = Config()
    assert instance_1 is instance_2


def test_get_config_without_set_raises() -> None:
    """Test that trying to get the config without setting it raises an error."""
    Config.reset()
    with pytest.raises(ConfigurationSingletonNotSetError):
        Config.get_config()


def test_set_config_twice_raises() -> None:
    """Test that trying to set the config twice raises an error."""
    # Load a valid sample config
    config_path = Path(__file__).parent / "sample_conf.yml"
    config_data = yaml.safe_load(config_path.read_text())
    config_obj = PipelineConfig(**config_data)

    Config.reset()
    Config.set_config(config_obj)

    with pytest.raises(ConfigurationSingletonAlreadySetError):
        Config.set_config(config_obj)
