"""Module for measuring energy consumption using perf."""

from datetime import datetime
from pathlib import Path
from typing import Any

from energytrackr.config.config_store import Config
from energytrackr.pipeline.stage_interface import PipelineStage
from energytrackr.utils.logger import logger
from energytrackr.utils.utils import read_cpu_temp, run_command


class MeasureEnergyStage(PipelineStage):
    """Uses `perf` to measure energy consumption. Appends the data to a results file."""

    def __init__(self) -> None:
        """Initialize the MeasureEnergyStage with a timestamp.

        The timestamp is used to uniquely identify the results file
        generated during the energy measurement process.
        """
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    def run(self, context: dict[str, Any]) -> None:
        """Runs the energy measurement and appends the data to a results file.

        If the build failed, or if there is no test command, or if the perf command fails,
        it will abort the pipeline unless ignore_failures is set.

        Args:
            context (dict): The context dictionary containing the current commit and other configuration.

        """
        config = Config.get_config()
        if context["build_failed"]:
            logger.info("Skipping energy measurement because build failed.", context=context)
            return

        if not (test_cmd := config.execution_plan.test_command):
            logger.info("Skipping energy measurement because no test command is provided.", context=context)
            return

        # Read CPU temperature before measurement
        try:
            temp_before: int | str = read_cpu_temp(config.cpu_thermal_file)
        except (OSError, ValueError) as e:
            logger.error("Could not read CPU temperature before measurement: %s", e, context=context)
            if not config.execution_plan.ignore_failures:
                context["abort_pipeline"] = True
                return
            logger.warning("Ignoring temperature read failure; continuing anyway.", context=context)
            temp_before = ""

        logger.info("Temperature before measurement: %s", temp_before, context=context)

        perf_command = f"perf stat -e power/energy-pkg/,power/energy-ram/ {test_cmd}"

        logger.info("Measuring energy with: %s", perf_command, context=context)
        result = run_command(perf_command, context=context)

        # If `perf` fails:
        if result.returncode:
            logger.error("Perf command failed: (code %s).", result.returncode, context=context)
            if not config.execution_plan.ignore_failures:
                context["abort_pipeline"] = True
                return
            logger.warning("Ignoring failures; continuing anyway.", context=context)

        # Extract the reading from perf output
        combined_output = result.stdout + "\n" + result.stderr

        perf_events = ["power/energy-pkg/", "power/energy-ram/", "seconds time elapsed"]
        perf_values = {}
        for event in perf_events:
            if (value := self.extract_perf_value(combined_output, event)) is None:
                logger.warning("No energy data found in perf output for event: %s", event, context=context)
                if not config.execution_plan.ignore_failures:
                    context["abort_pipeline"] = True
                    return
            perf_values[event] = value

        # Read CPU temperature after measurement
        try:
            temp_after: int | str = read_cpu_temp(config.cpu_thermal_file)
        except (OSError, ValueError) as e:
            logger.error("Could not read CPU temperature after measurement: %s", e, context=context)
            if not config.execution_plan.ignore_failures:
                context["abort_pipeline"] = True
                return
            logger.warning("Ignoring temperature read failure; continuing anyway.", context=context)
            temp_after = ""

        logger.info("Temperature after measurement: %s", temp_after, context=context)

        # Log to CSV
        commit_hash = context["commit"].hexsha
        repo_path = context["repo_path"]
        assert repo_path is not None, "Repository path is not set in the configuration."
        output_file = Path(repo_path).parent.parent / "energy_measurements" / f"energy_results_{self.timestamp}.csv"
        output_file.parent.mkdir(parents=True, exist_ok=True)

        write_header = not output_file.exists() or output_file.stat().st_size == 0
        with output_file.open("a") as fh:
            if write_header:
                fh.write("commit,energy-pkg,energy-ram,seconds,temp_before,temp_after\n")
            fh.write(
                f"{commit_hash},{perf_values['power/energy-pkg/']},{perf_values['power/energy-ram/']},"
                f"{perf_values['seconds time elapsed']},{temp_before},{temp_after}\n",
            )

        logger.info("Appended energy data to %s", output_file, context=context)

    @staticmethod
    def extract_perf_value(perf_output: str, event_name: str) -> str | None:
        """Extracts the value of the specified event from perf output.

        Args:
            perf_output (str): The output from the perf command.
            event_name (str): The name of the event to extract, e.g. "power/energy-pkg/".

        Returns:
            str | None: The value of the event as a string, or None if not found.
        """
        for line in perf_output.split("\n"):
            if event_name in line:
                parts = line.split()
                if parts and "<not" not in parts[0]:
                    return parts[0].replace(",", "")
        return None
