#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import shutil
import tarfile
from pathlib import Path
import pandas as pd
import re

from .config import (
    ROOT_DIR, CSV_FILE_PATH, FAILURE_DIR, MOVIE_SUBDIRS,
    ROOT_SLOT_LOCK, SUBDIR_SLOT_LOCK, EPISODE_PATTERNS
)
from .logging_setup import logger
from .file_processing import process_file, _move_to_failures
from .retention import enforce_failure_retention
from .utils import with_lock, is_lock_file, is_nfs_file, get_tmp_dir, file_sidecar_lock
from .ffmpeg_helpers import get_duration_seconds
from .naming import MOVIE_YEAR_RE


def _looks_like_episode_name(name: str) -> bool:
    if re.search(r"S\d{1,2}E\d{1,3}", name, re.IGNORECASE):
        return True
    for pat in EPISODE_PATTERNS:
        if pat.search(name):
            return True
    return False


def _movie_reasons(file_path: Path) -> list[str]:
    """
    Collect all reasons that suggest a file is a movie.
    Reasons:
      - duration >= 3900s (65 min)
      - filename has a year and no episode tag
    Returns a list of reason strings (could be empty).
    """
    if not _looks_like_episode_name(file_path.name):
        reasons: list[str] = []
        dur = get_duration_seconds(file_path) or 0.0
        if dur >= 3900.0:
            reasons.append(f"duration={dur:.0f}s")
        stem = file_path.stem
        if MOVIE_YEAR_RE.search(stem) and not _looks_like_episode_name(stem):
            reasons.append("filename has year and no episode tag")
        return reasons
    return False


def process_directory_movies_any(wd: Path, adult_only: bool, counters: dict) -> bool:
    did_work = False
    allowed_exts = {".mkv", ".mp4"}
    for file_path in sorted(wd.iterdir()):
        if not file_path.is_file() or is_lock_file(file_path) or is_nfs_file(file_path):
            continue

        # Check if it's a tar file
        if file_path.suffix.lower() in ['.tar', '.tar.gz']:
            extract_videos_from_tar(str(file_path))
            counters['tar_successes'] += 1
            did_work = True
            continue

        if file_path.suffix.lower() not in allowed_exts:
            _move_to_failures(file_path, tv_like=False)
            counters["movie_failures"] += 1
            did_work = True
            continue

        with file_sidecar_lock(file_path) as ours:
            if not ours:
                continue

            with with_lock(SUBDIR_SLOT_LOCK) as have_lock:
                if not have_lock:
                    continue

                row = pd.Series({
                    "CRF": "vmaf",
                    "Season": 0,
                    "Offset": 0,
                    "AdultOnly": 1 if adult_only else 0,
                    "Show": "",
                    "FileSearchTerm": "",
                    "MoveOnly": 0,
                    "RegexSearch": 0,
                })
                if file_path.exists() and process_file(file_path, row, media_type="movie"):
                    counters["movie_successes"] += 1
                    did_work = True
                else:
                    counters["movie_failures"] += 1
                    did_work = True
    return did_work


def process_directory_tv_via_csv(wd: Path, df: pd.DataFrame, is_root_slot: bool, counters: dict) -> bool:
    did_work = False

    for file_path in sorted(wd.iterdir()):
        if not file_path.is_file() or is_lock_file(file_path) or is_nfs_file(file_path):
            continue

        # Check if it's a tar file
        if file_path.suffix.lower() in ['.tar', '.tar.gz']:
            with with_lock(ROOT_SLOT_LOCK) as have_lock:
                if not have_lock:
                    continue
                try:
                    extract_videos_from_tar(str(file_path))
                    counters['tar_successes'] += 1
                    did_work = True
                except Exception as e:
                    counters["tar_failures"] += 1
                    did_work = True
            continue
            

        with file_sidecar_lock(file_path) as ours:
            if not ours:
                continue

            matched = False
            for _, row in df.iterrows():
                term = str(row.get("FileSearchTerm", "")).strip()
                if not term:
                    continue

                use_regex = int(row.get("RegexSearch", 0)) == 1
                if use_regex:
                    try:
                        match = re.search(term, file_path.name, re.IGNORECASE) is not None
                    except re.error:
                        continue
                else:
                    match = term.lower() in file_path.name.lower()

                if not match:
                    continue

                with with_lock(ROOT_SLOT_LOCK) as have_lock:
                    if not have_lock:
                        continue
                    if not file_path.exists():
                        continue
                    if process_file(file_path, row, media_type="tv"):
                        counters["tv_successes"] += 1
                        did_work = True
                        matched = True
                        break
                    else:
                        counters["tv_failures"] += 1
                        did_work = True
                        matched = True
                        break

            if matched:
                continue

            reasons = _movie_reasons(file_path)
            if reasons:
                reason_str = ", ".join(reasons)
                with with_lock(SUBDIR_SLOT_LOCK) as have_lock:
                    if not have_lock:
                        continue
                    if not file_path.exists():
                        continue
                    row = pd.Series({
                        "CRF": "vmaf",
                        "Season": 0,
                        "Offset": 0,
                        "AdultOnly": 0,
                        "Show": "",
                        "FileSearchTerm": "",
                        "MoveOnly": 0,
                        "RegexSearch": 0,
                    })
                    if process_file(file_path, row, media_type="movie"):
                        logger.info(
                            f"Unmatched TV file auto-classified as movie ({reason_str}): {file_path.name}"
                        )
                        counters["movie_successes"] += 1
                        did_work = True
                        continue
                    else:
                        counters["movie_failures"] += 1
                        did_work = True
                        continue

            with with_lock(ROOT_SLOT_LOCK) as have_lock:
                if not have_lock:
                    logger.debug(f"Skipping failures move (TV lock busy) for {file_path.name}")
                    continue
                if not file_path.exists():
                    continue
                _move_to_failures(file_path, tv_like=True)
                counters["tv_failures"] += 1
                did_work = True

    return did_work


def extract_videos_from_tar(file_path: str) -> None:
    """
    Extract video files from a .tar or .tar.gz file to the current working directory
    and move the original .tar file to a "ConversionFailures" directory.
    """
    
    try:
        # Check if the file is a .tar or .tar.gz file
        if os.path.splitext(file_path)[1] not in ['.tar', '.tar.gz']:
            logger.warning(f"Skipping non-tar file: {file_path}")
            return

        logger.debug(f"Starting extraction of {os.path.basename(file_path)}")

        # Extract files from the tar archive
        with tarfile.open(file_path, "r:*") as tar:
            for member in tar.getmembers():
                # Skip directories and non-video files
                if os.path.splitext(member.name)[1].lower() not in [
                    '.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv',
                    '.mts', '.m2ts', '.iso'
                ]:
                    continue

                logger.debug(f"Extracting {member.name}")
                tar.extract(member, path=ROOT_DIR, filter='data')

        logger.info(f"Successfully extracted files from {os.path.basename(file_path)}")

        # Move the original .tar file to ConversionFailures directory
        _move_to_failures(Path(file_path), tv_like=True)

    except Exception as e:
        logger.error(f"Error processing file {file_path}: {str(e)}")
        raise  # Re-raise the exception or handle it as needed

def main():
    did_work = False
    counters = {"tv_successes": 0, "tv_failures": 0, "movie_successes": 0, "movie_failures": 0, "tar_successes": 0, "tar_failures": 0}

    os.chdir(ROOT_DIR)
    print(f"[INFO] Changing working directory to {ROOT_DIR}")

    enforce_failure_retention(FAILURE_DIR)

    if not CSV_FILE_PATH.exists():
        logger.error(f"CSV not found: {CSV_FILE_PATH}")
        return

    try:
        df = pd.read_csv(CSV_FILE_PATH).fillna("")
    except Exception as e:
        logger.error(f"Failed to read CSV: {e}")
        return

    for subdir_name, is_adult in MOVIE_SUBDIRS:
        subdir_path = ROOT_DIR / subdir_name
        if subdir_path.exists():
            if process_directory_movies_any(subdir_path, adult_only=is_adult, counters=counters):
                did_work = True

    if process_directory_tv_via_csv(ROOT_DIR, df, is_root_slot=True, counters=counters):
        did_work = True

    if did_work:
        parts = []
        if counters["tv_successes"] or counters["tv_failures"]:
            parts.append(f"TV successes={counters['tv_successes']}, failures={counters['tv_failures']}")
        if counters["movie_successes"] or counters["movie_failures"]:
            parts.append(f"Movie successes={counters['movie_successes']}, failures={counters['movie_failures']}")
        if counters["tar_successes"] or counters["tar_failures"]:
            parts.append(f"TAR successes={counters['tar_successes']}, failures={counters['tar_failures']}")
        if parts:
            logger.info("Summary: " + "; ".join(parts))

    try:
        tmp_dir = get_tmp_dir()
        shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception as e:
        logger.warning(f"Failed to clean up TMP_DIR: {e}")


if __name__ == "__main__":
    main()
