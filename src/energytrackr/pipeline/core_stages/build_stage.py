"""Module to build the project if in 'benchmarks' mode or skip if in 'tests' mode."""

from energytrackr.config.config_store import Config
from energytrackr.pipeline.context import Context
from energytrackr.pipeline.stage_interface import PipelineStage
from energytrackr.utils.logger import logger
from energytrackr.utils.utils import run_command


class BuildStage(PipelineStage):
    """Builds the project if in 'benchmarks' mode, or skip if 'tests' mode has no build commands."""

    def run(self, context: Context) -> None:  # noqa: PLR6301
        """Executes the build stage of the pipeline based on the provided context and configuration.

        This method handles two primary modes of operation:
            1. Benchmarks Mode: Executes a series of build commands specified in the configuration. If any command fails,
               the pipeline may be aborted based on the configuration.
            2. Batch Mode: Creates multiple copies of the repository, runs build commands in each copy, and handles
               failures similarly to benchmarks mode.

        Args:
            context (Context): The pipeline context containing at least a "commits" key with a list of Commit objects.
            Keys used:
                - "build_failed" (bool): Indicates if any build command failed.
                - "abort_pipeline" (bool): Indicates if the pipeline should be aborted.

        Notes:
            - The behavior of the pipeline is influenced by the configuration, specifically:
            - `config.execution_plan.mode`: Determines if the pipeline is in benchmarks mode.
            - `config.execution_plan.batch_size`: Specifies the number of repository copies to create in batch mode.
            - `config.execution_plan.compile_commands`: The list of build commands to execute.
            - `config.execution_plan.ignore_failures`: If True, the pipeline will not abort on build failures.
            - The repository path is derived from `config.repo_path`.
        """
        config = Config.get_config()

        compile_cmds = config.execution_plan.compile_commands or []
        for cmd in compile_cmds:
            logger.info("Running build command: %s", cmd, context=context)
            result = run_command(cmd, context=context)
            if result.returncode:
                logger.error("Build command failed: %s (code %s)", cmd, result.returncode, context=context)
                context["build_failed"] = True
                if not config.execution_plan.ignore_failures:
                    context["abort_pipeline"] = True
                break
