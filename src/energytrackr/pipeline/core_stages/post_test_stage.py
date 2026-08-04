"""Module to run any post-test command (cleanup or teardown)."""

from energytrackr.config.config_store import Config
from energytrackr.pipeline.context import Context
from energytrackr.pipeline.stage_interface import PipelineStage
from energytrackr.utils.logger import logger
from energytrackr.utils.utils import run_command


class PostTestStage(PipelineStage):
    """Runs any post-test command (cleanup or teardown)."""

    def run(self, context: Context) -> None:  # noqa: PLR6301
        """Runs any post-test command (cleanup or teardown).

        Retrieves the post-test command from the configuration and executes it
        within the specified working directory. If the command fails and
        failures are not ignored, the pipeline is aborted.

        Args:
            context (Context): The pipeline context for the stage.
        """
        config = Config.get_config()
        if not (post_cmd := config.execution_plan.post_command):
            return

        logger.info("Running post-test command: %s", post_cmd)
        result = run_command(post_cmd, cwd=context.get("repo_path"), context=context)
        if result.returncode:
            logger.error("Post-test command failed with exit code %d", result.returncode)
            if not config.execution_plan.ignore_failures:
                context["abort_pipeline"] = True
