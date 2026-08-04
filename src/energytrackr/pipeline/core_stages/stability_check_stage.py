"""Module to check the stability of the system before running the pipeline."""

import statistics
import time

from energytrackr.pipeline.context import Context
from energytrackr.pipeline.stage_interface import PipelineStage
from energytrackr.utils.logger import logger
from energytrackr.utils.utils import run_command


class StabilityCheckStage(PipelineStage):
    """Runs a stability test on power usage before running the pipeline."""

    def run(self, context: Context) -> None:
        """Runs a stability test on power usage before running the pipeline.

        If the system is not stable, the pipeline is aborted by setting
        context["abort_pipeline"] = True. Otherwise, the pipeline is allowed to
        proceed.

        Args:
            context (Context): The pipeline context containing the
        """
        logger.info("Running stability test before measuring energy.")

        if not self._is_system_stable():
            logger.error("System is not stable. Aborting pipeline.")
            context["abort_pipeline"] = True
        else:
            logger.info("System is stable. Proceeding.")

    @staticmethod
    def _is_system_stable(k: float = 3.5, warmup: int = 5, duration: int = 30) -> bool:
        """Runs a stability test on power usage.

        The test first warms up by taking 'warmup' number of samples, then
        takes 'duration' number of samples. If the absolute value of the
        modified z-score of any sample is greater than 'k', the system is
        deemed unstable and the function returns False. Otherwise, the
        function returns True.

        The modified z-score is calculated as 0.6745 * (x - median) / median
        absolute deviation, where x is the sample, median is the median of
        the samples, and median absolute deviation is the median of the
        absolute values of the differences between the samples and the
        median.

        If an exception occurs while taking a sample, the sample is
        considered to be 0.

        Args:
            k: the threshold above which the system is deemed unstable
            warmup: the number of samples to take for warming up
            duration: the total number of samples to take

        Returns:
            True if the system is stable, False otherwise
        """
        samples: list[int] = []
        prev = StabilityCheckStage._read_uj()
        for _ in range(warmup):
            time.sleep(1)
            now = StabilityCheckStage._read_uj()
            samples.append(now - prev)
            prev = now

        median = statistics.median(samples)
        mad = statistics.median([abs(x - median) for x in samples]) or 1

        for _ in range(duration - warmup):
            time.sleep(1)
            now = StabilityCheckStage._read_uj()
            diff = now - prev
            prev = now
            mz = 0.6745 * (diff - median) / mad
            if abs(mz) > k:
                return False
        return True

    @staticmethod
    def _read_uj() -> int:
        try:
            result = run_command("cat /sys/class/powercap/intel-rapl:0/energy_uj")
        except Exception:
            return 0
        return int(result.stdout.strip())
