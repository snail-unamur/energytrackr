"""Module to check if user is allowed to use perf without sudo."""

from energytrackr.config.config_store import Config
from energytrackr.pipeline.context import Context
from energytrackr.pipeline.stage_interface import PipelineStage
from energytrackr.utils.logger import logger
from energytrackr.utils.utils import run_command


class VerifyPerfStage(PipelineStage):
    """Runs any pre-build commands (e.g., setting up environment).

    Optionally only runs if certain files changed, etc.
    """

    def run(self, context: Context) -> None:  # noqa: PLR6301
        """Check if user is allowed to use perf without sudo.

        Args:
            context (Context): The pipeline context.
            Expected keys:
                - "abort_pipeline": bool — indicates if the pipeline should be aborted.
        """
        # read perf_event_paranoid
        command_result = run_command("cat /proc/sys/kernel/perf_event_paranoid")
        if int(command_result.stdout.strip()) != -1:
            logger.warning("Perf_event_paranoid is not set to -1")
            logger.warning("User is not allowed to use perf without sudo.")
            logger.warning("Please run the pipeline with sudo or set perf_event_paranoid to -1.")
            if not Config.get_config().execution_plan.ignore_failures:
                context["abort_pipeline"] = True
