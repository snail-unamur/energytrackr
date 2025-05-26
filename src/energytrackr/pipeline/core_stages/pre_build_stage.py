"""Module to run pre-build commands (e.g., setting up environment)."""

from energytrackr.config.config_store import Config
from energytrackr.pipeline.context import Context
from energytrackr.pipeline.stage_interface import PipelineStage
from energytrackr.utils.logger import logger
from energytrackr.utils.utils import run_command


class PreBuildStage(PipelineStage):
    """Runs any pre-build commands (e.g., setting up environment).

    Optionally only runs if certain files changed, etc.
    """

    def run(self, context: Context) -> None:  # noqa: PLR6301
        """Executes pre-build commands as defined in the configuration.

        This method retrieves a pre-build command from the configuration and executes it
        within the specified repository path. If no pre-build command is defined, the stage
        is skipped. Optionally, the execution can be conditioned on changes in specific files,
        though such logic is not implemented here.

        If the pre-build command fails and failures are not ignored, the pipeline is aborted.

        Args:
            context: The pipeline context for the stage, which should include the repository path.
        """
        config = Config.get_config()
        if not (pre_cmd := config.execution_plan.pre_command):
            return  # Nothing to do

        # If user wants certain files to trigger this only if changed:
        # Check patterns in commit.stats.files, if so desired.
        # For brevity we skip that logic or replicate from your original code.

        logger.info("Running pre-build command: %s", pre_cmd)
        result = run_command(pre_cmd, cwd=context.get("repo_path"), context=context)

        if result.returncode:
            logger.error("Pre-build command failed with return code %d", result.returncode)
            if not config.execution_plan.ignore_failures:
                context["abort_pipeline"] = True
