import os, time, datetime
from pathlib import Path
from .logging_setup import logger
from .config import FAILURE_RETENTION_DAYS, FAILURE_WARN_DAYS_BEFORE


def enforce_failure_retention(base_dir: Path):
    now = time.time()
    today = datetime.date.today()
    current_time = datetime.datetime.now().time()

    # Only log warnings during the first minute of the day
    log_warnings = current_time < datetime.time(hour=0, minute=1)

    if not base_dir.exists():
        logger.info(f"ConversionFailures directory not found: {base_dir}")
        return

    for root, _, files in os.walk(base_dir):
        root_path = Path(root)
        for name in files:
            fp = root_path / name
            try:
                age_days = int((now - fp.stat().st_mtime) // 86400)
                days_until = FAILURE_RETENTION_DAYS - age_days
                if age_days >= FAILURE_RETENTION_DAYS:
                    logger.info(f"Deleting stale failure file ({age_days}d): {fp}")
                    fp.unlink(missing_ok=True)
                elif log_warnings and days_until in FAILURE_WARN_DAYS_BEFORE:
                    logger.info(f"Failure file nearing deletion in {days_until}d: {fp}")
            except Exception as e:
                logger.warning(f"Retention check failed for {fp}: {e}")
