"""Stage to check CPU temperature before proceeding with the pipeline."""

import time
from typing import Any

from energytrackr.config.config_store import Config
from energytrackr.pipeline.stage_interface import PipelineStage
from energytrackr.utils.logger import logger
from energytrackr.utils.utils import read_cpu_temp


class TemperatureCheckStage(PipelineStage):
    """Ensures that the CPU is not too hot before starting the next stage."""

    def run(self, context: dict[str, Any]) -> None:  # noqa: ARG002
        """Monitors the CPU temperature and waits until it is below a safe limit before proceeding.

        Args:
            self (TemperatureCheckStage): The instance of the stage.
            context (dict): The shared context dictionary for the pipeline.

        The function repeatedly checks the CPU temperature by reading from
        the thermal file specified in the configuration. If the temperature is
        above the safe limit, it logs a warning and waits for 2 seconds before
        checking again. If the temperature is below the safe limit, or if there
        is an issue reading the temperature, it logs the information and exits
        the loop, allowing the pipeline to proceed.
        """
        config = Config.get_config()
        temp_file = config.cpu_thermal_file
        safe_limit = config.limits.temperature_safe_limit

        while True:
            # Only this single statement is inside the try
            try:
                temp = read_cpu_temp(temp_file)
            except (OSError, ValueError) as e:
                logger.warning("Could not read or parse temperature (%s). Proceeding anyway.", e)
                break

            logger.info("CPU temperature: %d (limit: %d)", temp, safe_limit)
            if temp < safe_limit:
                # Safe to proceed
                break
            logger.warning("CPU too hot (%d), waiting...", temp)
            time.sleep(2)
