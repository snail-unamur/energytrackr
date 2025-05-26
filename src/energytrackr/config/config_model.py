"""This module defines the configuration model for the pipeline."""

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, Field, model_validator


class ModeEnum(StrEnum):
    """Mode of execution for the pipeline.

    - 'tests': Run tests only.
    - 'benchmarks': Run benchmarks only.
    """

    TESTS = "tests"
    BENCHMARKS = "benchmarks"


class GranularityEnum(StrEnum):
    """Granularity of execution for the pipeline.

    - 'commits': Run tests for each commit.
    - 'branches': Run tests for each branch.
    - 'tags': Run tests for each tag.
    """

    COMMITS = "commits"
    BRANCHES = "branches"
    TAGS = "tags"


class SearchStrategyEnum(StrEnum):
    """Batch search strategies for detecting regressions.

    - 'naive': Process all commits in fixed batches.
    - 'three_point': Use 3-point regression-aware search.
    """

    NAIVE = "naive"
    PRUNED_BINARY_SEGMENTATION = "pruned_binary_segmentation"


class RepositoryDefinition(BaseModel):
    """Definition of the repository to be tested."""

    url: str = Field(
        ...,
        description="URL of the repository to be tested.",
        examples=["https://github.com/signalfx/signalfx-java"],
    )
    branch: str | None = Field(None, description="Branch to be used for testing.", examples=["main"])
    clone_options: list[str] | None = Field(
        default=None,
        description="Additional options for cloning the repository.",
        examples=[["--depth", "1"]],
    )


class ExecutionPlanDefinition(BaseModel):
    """Execution plan for the pipeline."""

    mode: ModeEnum = Field(
        default=ModeEnum.TESTS,
        description="Execution mode: either 'tests' or 'benchmarks'.",
        examples=["tests"],
    )
    compile_commands: list[str] | None = Field(
        default=None,
        description="List of compile commands required when using benchmarks mode.",
        examples=[["make all"]],
    )
    granularity: GranularityEnum = Field(
        default=GranularityEnum.COMMITS,
        description="Granularity at which to execute tests (commits, branches, or tags).",
        examples=["commits"],
    )
    pre_command: str | None = Field(
        default=None,
        description="Command to execute before running tests.",
        examples=["mvn clean test-compile"],
    )
    pre_command_condition_files: set[str] = Field(
        default_factory=set,
        description="Set of file paths that trigger the pre_command if modified.",
        examples=[{"pom.xml", "build.gradle"}],
    )
    test_command: str = Field(..., description="Command to execute tests.", examples=["mvn surefire:test"])
    test_command_path: str = Field(default="", description="Path where the test command should be executed.", examples=["."])
    ignore_failures: bool = Field(
        default=True,
        description="Flag indicating whether to ignore failures.",
        examples=[False],
    )
    post_command: str | None = Field(
        default=None,
        description="Command to execute after tests are run.",
        examples=["echo 'Tests completed'"],
    )
    num_commits: int | None = Field(
        default=None,
        description="Number of commits to test.",
        examples=[15],
    )
    num_runs: int = Field(
        default=1,
        description="Number of times each test should be run.",
        examples=[30],
    )
    num_repeats: int = Field(
        default=1,
        description="Number of repetitions for each test execution.",
        examples=[1],
    )
    batch_size: int = Field(
        default=100,
        description="Number of tasks to execute in one batch.",
        examples=[100],
    )
    randomize_tasks: bool = Field(
        default=False,
        description="Flag indicating whether the test tasks should be executed in random order.",
        examples=[True],
    )
    oldest_commit: str | None = Field(
        default=None,
        description="The hash of the oldest commit to consider.",
        examples=["db1ba94c8a8aae10b021ffd8532bd9d8fc42ae10"],
    )
    newest_commit: str | None = Field(
        default=None,
        description="The hash of the newest commit to consider.",
        examples=["f47ac10b-58cc-4372-a567-0e02b2c3d479"],
    )
    execute_common_tests: bool = Field(
        default=False,
        description="Flag indicating whether to execute common tests in addition to specific ones.",
        examples=[False],
    )

    search_strategy: SearchStrategyEnum = Field(
        default=SearchStrategyEnum.NAIVE,
        description="Batch search strategy: 'naive' or 'three_point'.",
        examples=["three_point"],
    )
    parallel_stages: list[str] = Field(
        default_factory=list,
        description=("List of stage names to run in parallel: 'pre', 'setup', 'test', 'post'."),
        examples=[["setup", "test"]],
    )
    max_workers: int | None = Field(
        default=None,
        description="Max number of worker processes for parallel stages (0 = auto cpu_count).",
        examples=[4],
    )

    @model_validator(mode="after")
    def check_compile_commands_for_benchmarks(self: Self) -> Self:
        """Ensure that compile_commands is provided when benchmarks mode is selected.

        Returns:
            Self: The instance of the class.

        Raises:
            ValueError: If compile_commands is not provided in benchmarks mode.
        """
        if self.mode == ModeEnum.BENCHMARKS and not self.compile_commands:
            raise ValueError("compile_commands must be provided for 'benchmarks' mode.")  # noqa: TRY003
        return self


class LimitsDefinition(BaseModel):
    """Limits for the pipeline execution."""

    temperature_safe_limit: int = Field(
        ...,
        description="The maximum safe operating temperature (in milli-degrees).",
        examples=[65000],
    )


class RegressionDetectionDefinition(BaseModel):
    """Configuration for regression detection context in the pipeline.

    This model specifies the minimum number of commits to include before and/or after a candidate commit.
    """

    min_commits_before: int = Field(
        default=1,
        description="Minimum number of commits to include before a candidate commit as baseline.",
        examples=[1],
    )
    min_commits_after: int = Field(
        default=0,
        description=("Minimum number of commits to include after a candidate commit for confirmation."),
        examples=[0],
    )


class PipelineConfig(BaseModel):
    """Configuration model for the entire pipeline."""

    config_version: str = Field(
        default="1.0.0",
        description="Version of the configuration schema.",
        examples=["1.0.0"],
    )
    repo: RepositoryDefinition = Field(..., description="Repository configuration details.")
    execution_plan: ExecutionPlanDefinition = Field(..., description="Execution plan for running tests or benchmarks.")
    limits: LimitsDefinition = Field(
        ...,
        description="Limits for pipeline execution.",
        examples=[{"temperature_safe_limit": 65000, "energy_regression_percent": 20}],
    )
    tracked_file_extensions: set[str] = Field(
        ...,
        description="Set of file extensions to track for changes.",
        examples=[{"java", "xml", "properties", "yaml", "yml"}],
    )
    ignored_directories: set[str] = Field(
        default_factory=set,
        description="Set of directories to ignore during commit filtering.",
        examples=[{"target", "build", "out"}],
    )
    cpu_thermal_file: str = Field(
        ...,
        description="Path to the CPU thermal file for monitoring temperature.",
        examples=["/sys/class/hwmon/hwmon5/temp1_input"],
    )
    setup_commands: list[str] | None = Field(
        default=None,
        description="List of shell commands to setup the environment.",
        examples=[["export JAVA_HOME=/usr/lib/jvm/java-8-openjdk", "export PATH=$JAVA_HOME/bin:$PATH"]],
    )

    regression_detection: RegressionDetectionDefinition = Field(
        default_factory=RegressionDetectionDefinition,
        description="Configuration for regression detection context commits.",
    )
    timeout: int = Field(
        default=120,
        description="Timeout for executions (seconds).",
        examples=[120],
    )
