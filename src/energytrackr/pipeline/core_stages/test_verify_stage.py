"""Module to verify that tests pass before scheduling energy measurements."""

from typing import Any

from energytrackr.config.config_store import Config
from energytrackr.pipeline.stage_interface import PipelineStage
from energytrackr.utils.logger import logger
from energytrackr.utils.utils import run_command


class TestVerifyStage(PipelineStage):
    """Runs the test command once per commit to verify tests pass before scheduling measurements."""

    def run(self, context: dict[str, Any]) -> None:  # noqa: PLR6301
        """Runs the test command and marks the commit as failed if tests do not pass.

        Skips immediately if the build already failed. If tests fail, sets
        ``context["build_failed"]`` so that the commit is excluded from all
        batch measurement runs.

        Args:
            context (dict[str, Any]): The shared context dictionary for the pipeline.
        """
        if context.get("build_failed"):
            logger.info("Skipping test verification because build failed.", context=context)
            return

        config = Config.get_config()
        if not (test_cmd := config.execution_plan.test_command):
            logger.info("Skipping test verification because no test command is provided.", context=context)
            return

        logger.info("Verifying tests pass with: %s", test_cmd, context=context)
        result = run_command(test_cmd, context=context)

        if result.returncode:
            logger.warning(
                "Tests failed for this commit (code %s), skipping measurements.",
                result.returncode,
                context=context,
            )
            context["build_failed"] = True
