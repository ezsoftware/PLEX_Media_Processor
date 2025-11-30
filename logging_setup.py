import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
import os, re, time
from datetime import datetime, date

from .config import ROOT_DIR

LOGS_DIR = ROOT_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
log_file = LOGS_DIR / "process_media.log"


class DatedTimedRotatingFileHandler(TimedRotatingFileHandler):
    """
    Rotates to: <basename>.YYYY-MM-DD.log
    Also fixes deletion by matching the new pattern when culling old logs.
    """
    def __init__(self, *args, **kwargs):
        # keep the usual midnight rotation, local time
        super().__init__(*args, when="midnight", backupCount=14, utc=False, **kwargs)
        # We’ll generate full names ourselves; 'suffix' is not relied on.

        # Regex to match our rotated filenames for deletion
        base = Path(self.baseFilename).name  # e.g. process_media.log
        # We will produce: process_media.YYYY-MM-DD.log
        # Build a regex anchored to the filename stem:
        stem = base[:-4] if base.endswith(".log") else base  # process_media
        self._delete_pattern = re.compile(rf"^{re.escape(stem)}\.\d{{4}}-\d{{2}}-\d{{2}}\.log$")

    def rotation_filename(self, default_name: str) -> str:
        """
        Map default 'process_media.log.YYYY-MM-DD' to 'process_media.YYYY-MM-DD.log'
        """
        p = Path(default_name)
        name = p.name  # e.g. process_media.log.2025-09-05
        if name.endswith(".log"):
            # Some Python versions might not append a date when calling rotation_filename directly.
            return str(p)
        # expected: "<stem>.log.<date>"
        if ".log." in name:
            base, date_part = name.split(".log.", 1)
            new_name = f"{base}.{date_part}.log"
            return str(p.with_name(new_name))
        # Fallback: if anything changes upstream, just return what we got
        return str(p)

    def getFilesToDelete(self):
        """
        Override to collect files like process_media.YYYY-MM-DD.log for pruning.
        """
        dirName, baseName = os.path.split(self.baseFilename)
        try:
            filenames = os.listdir(dirName or ".")
        except Exception:
            filenames = []

        result = []
        for fn in filenames:
            if self._delete_pattern.match(fn):
                result.append(os.path.join(dirName, fn))
        result.sort()
        if self.backupCount > 0:
            return result[:max(0, len(result) - self.backupCount)]
        else:
            return []

    def shouldRollover(self, record):
        """
        Keep base behavior; rotate on first write after midnight.
        """
        return super().shouldRollover(record)


logger = logging.getLogger("process_media")
logger.setLevel(logging.INFO)

file_handler = DatedTimedRotatingFileHandler(str(log_file))
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)


def force_rollover_if_new_day():
    """
    If the last rollover date is not today, force a rollover so
    yesterday’s file exists even if the first write happens well after midnight.
    """
    # Similar to how TimedRotatingFileHandler computes rolloverAt
    # If we’ve crossed midnight since last open, doRollover before any logging.
    try:
        # rolloverAt is set to the *next* rollover time in epoch seconds
        now = int(time.time())
        # If we’re already past the scheduled rollover time, rotate immediately
        if now >= file_handler.rolloverAt:
            file_handler.doRollover()
    except Exception:
        # Best-effort; avoid crashing on startup
        pass

# Call once at import time so the first log line of the run goes to the correct day's file.
force_rollover_if_new_day()
