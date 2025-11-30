import shutil
import subprocess
import pandas as pd
import time
import os
import urllib.request
import re 
from pathlib import Path

from .config import (
    AO_MOVIE_DIR, MOVIE_DIR, AO_TV_DIR, TV_DIR, FORCE_REENCODE, FAILURE_DIR, PLEX_REFRESH_URLS
)
from .logging_setup import logger
from .ffmpeg_helpers import build_ffmpeg_cmd, run_ffprobe_json, get_source_bit_depth
from .metadata_lookup import extract_title_from_filename, lookup_anilist, lookup_jikan
from .crf_helpers import determine_crf
from .utils import sanitize_folder_name, get_tmp_dir, is_lock_file, is_nfs_file
from .naming import derive_movie_folder_name, get_final_dest_dir, build_output_name, tag_episode_in_name, extract_episode_number_and_version


def _refresh_plex_libraries():
    if not PLEX_REFRESH_URLS:
        return
    for url in PLEX_REFRESH_URLS:
        try:
            with urllib.request.urlopen(url, timeout=5):
                pass
        except Exception as e:
            logger.warning(f"Failed to refresh Plex library via {url}: {e}")


def _move_to_failures(file_path: Path, tv_like: bool):
    # Get the current access time
    current_mtime = time.time()
    


    fail_target_dir = FAILURE_DIR / ("tv" if tv_like else "movie")
    fail_target_dir.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(str(file_path), str(fail_target_dir / file_path.name))
        # Set the modification time of the moved file
        os.utime(
            fail_target_dir / file_path.name,
            times=(current_mtime, current_mtime)
        )
        logger.info(f"Moved {file_path.name} -> {fail_target_dir}")
    except Exception as e:
        logger.error(f"Failed to move {file_path.name} to failures: {e}")


def _movie_final_dest_dir(base_dir: Path, file_path: Path) -> Path:
    return base_dir / sanitize_folder_name(derive_movie_folder_name(file_path))

def _find_existing_episode_version(final_dest_dir: Path, season: int, episode: int) -> int:
    """
    Scan final_dest_dir for files matching S{season:02d}E{episode:02d}[vN].
    Returns the highest found version (0 if none).
    """
    tag = f"S{season:02d}E{episode:02d}"
    pat = re.compile(re.escape(tag) + r"(?:v(?P<ver>\d+))?", re.IGNORECASE)
    max_ver = 0
    for p in final_dest_dir.iterdir():
        if not p.is_file():
            continue
        m = pat.search(p.name)
        if not m:
            continue
        ver_str = m.group("ver")
        ver = int(ver_str) if ver_str and ver_str.isdigit() else 1
        if ver > max_ver:
            max_ver = ver
    return max_ver


def _delete_older_episode_versions(final_dest_dir: Path, season: int, episode: int, keep_version: int) -> None:
    """
    In final_dest_dir, delete all files for S{season}E{episode} with version < keep_version.
    """
    if keep_version <= 1:
        # Nothing to clean up when we keep v1 as the only version.
        return

    tag = f"S{season:02d}E{episode:02d}"
    pat = re.compile(re.escape(tag) + r"(?:v(?P<ver>\d+))?", re.IGNORECASE)
    for p in final_dest_dir.iterdir():
        if not p.is_file():
            continue
        m = pat.search(p.name)
        if not m:
            continue
        ver_str = m.group("ver")
        ver = int(ver_str) if ver_str and ver_str.isdigit() else 1
        if ver < keep_version:
            try:
                p.unlink()
                logger.info(f"Removed older version v{ver} of {tag}: {p}")
            except Exception as e:
                logger.warning(f"Failed to remove older version {p}: {e}")


def process_file(file_path: Path, row: pd.Series, media_type: str) -> bool:
    # Skip junk/locks
    if not file_path.is_file() or is_lock_file(file_path) or is_nfs_file(file_path):
        return False

    season = int(row["Season"]) if not pd.isna(row["Season"]) else 0
    offset = int(row["Offset"]) if not pd.isna(row["Offset"]) else 0  # kept for episode tag parity
    adult_only = bool(row["AdultOnly"])
    show = str(row.get("Show", "")).strip()
    move_only = bool(row.get("MoveOnly", 0))

    # Versioning info for TV episodes
    episode_for_versioning = None
    version_num = None
    if media_type == "tv" and season > 0:
        info = extract_episode_number_and_version(file_path.name, offset)
        if info is not None:
            episode_for_versioning, version_num = info


    # ==== TV-only Anime lookup (avoid hitting AniList/Jikan for movies) ====
    if media_type == "tv" and not show:
        guess = extract_title_from_filename(file_path.name)
        title, year = lookup_anilist(guess)
        if not title:
            title, year = lookup_jikan(guess)
        if title:
            show = f"{title} ({year})" if year else title
            row["Show"] = show
        else:
            show = guess or show
    # For movies, folder naming comes from filename via derive_movie_folder_name(); `show` is not required.

    # Choose base destination (NAS)
    dest_dir = (AO_MOVIE_DIR if adult_only else MOVIE_DIR) if media_type == "movie" else (AO_TV_DIR if adult_only else TV_DIR)

    # Compute final destination (Movies: Title (Year); TV: Show[/Season NN])
    if media_type == "movie":
        final_dest_dir = _movie_final_dest_dir(dest_dir, file_path)
    else:
        final_dest_dir = get_final_dest_dir(dest_dir, show, media_type == "tv", season)

    final_dest_dir.mkdir(parents=True, exist_ok=True)

    # Version check for TV episodes: skip processing if a newer (or same) version already exists
    if (
        media_type == "tv"
        and season > 0
        and episode_for_versioning is not None
        and version_num is not None
    ):
        existing_max = _find_existing_episode_version(final_dest_dir, season, episode_for_versioning)
        if existing_max > 0:
            if existing_max > version_num:
                # Example: v3 already exists, this is v2 -> fail as "newer version already exists"
                logger.info(
                    f"Skipping {file_path.name}: newer version v{existing_max} for "
                    f"S{season:02d}E{episode_for_versioning:02d} already exists in {final_dest_dir}"
                )
                _move_to_failures(file_path, tv_like=True)
                return False
            if existing_max == version_num:
                # Same version also treated as duplicate and failed
                logger.info(
                    f"Skipping {file_path.name}: same version v{version_num} for "
                    f"S{season:02d}E{episode_for_versioning:02d} already exists in {final_dest_dir}"
                )
                _move_to_failures(file_path, tv_like=True)
                return False


    # Probe codec of the input
    codec_info = run_ffprobe_json([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=codec_name", "-of", "json", str(file_path)
    ])
    codec = codec_info.get("streams", [{}])[0].get("codec_name", "unknown")

    # Move-only or already HEVC/AV1 and re-encode not forced => just move to NAS
    if move_only or (codec in ["hevc", "av1"] and not FORCE_REENCODE):
        shutil.move(str(file_path), str(final_dest_dir / file_path.name))
        logger.info(f"Moved {file_path.name} -> {final_dest_dir}")

        if (
            media_type == "tv"
            and season > 0
            and episode_for_versioning is not None
            and version_num is not None
        ):
            _delete_older_episode_versions(final_dest_dir, season, episode_for_versioning, version_num)

        _refresh_plex_libraries()
        return True


    # ==== Encode on local disk (TMP_DIR), then move result to NAS ====
    TMP_DIR = get_tmp_dir()

    # Determine CRF and output bit depth tag from source
    crf = determine_crf(row, file_path, show, media_type == "tv")
    if crf is None:
        logger.error(f"CRF could not be determined for {file_path.name}")
        return False

    source_bit = get_source_bit_depth(file_path)  # 8 or 10

    # Naming: substitutions + SxxExx tag with correct {bit}
    if media_type == "tv":
        output_stem = build_output_name(file_path.stem, crf, source_bit)
        if season > 0:
            output_stem = tag_episode_in_name(file_path.name, output_stem, season, offset)
    else:
        output_stem = build_output_name(file_path.stem, crf, source_bit)

    tmp_output = TMP_DIR / f"{output_stem}.mkv"
    logger.info(f"Encoding to local TMP: {tmp_output}")

    cmd = build_ffmpeg_cmd(file_path, tmp_output, crf)

    logger.info(f"Starting conversion {file_path.name} -> {tmp_output.name}")
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        final_output = final_dest_dir / tmp_output.name
        shutil.move(str(tmp_output), str(final_output))
        file_path.unlink(missing_ok=True)
        logger.info(f"Successfully converted {file_path.name} -> {final_output}")

        if (
            media_type == "tv"
            and season > 0
            and episode_for_versioning is not None
            and version_num is not None
        ):
            _delete_older_episode_versions(final_dest_dir, season, episode_for_versioning, version_num)

        _refresh_plex_libraries()
        return True
    except subprocess.CalledProcessError as e:
        stderr = e.stderr or ""
        if "No such file or directory" in stderr:
            logger.warning(f"Source vanished during encode (likely NFS race): {file_path.name}")
        else:
            logger.error(
                f"FFmpeg failed for {file_path.name}:\n"
                f"STDOUT:\n{e.stdout}\n"
                f"STDERR:\n{stderr}"
            )
        try:
            if tmp_output.exists():
                tmp_output.unlink()
        except Exception:
            pass
        return False
