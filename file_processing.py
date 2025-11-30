import shutil
import subprocess
import pandas as pd
import time
import os
from pathlib import Path

from .config import (
    AO_MOVIE_DIR, MOVIE_DIR, AO_TV_DIR, TV_DIR, FORCE_REENCODE, FAILURE_DIR, PLEX_REFRESH_URLS
)
from .logging_setup import logger
from .ffmpeg_helpers import build_ffmpeg_cmd, run_ffprobe_json, get_source_bit_depth
from .metadata_lookup import extract_title_from_filename, lookup_anilist, lookup_jikan
from .crf_helpers import determine_crf
from .utils import sanitize_folder_name, get_tmp_dir, is_lock_file, is_nfs_file
from .naming import derive_movie_folder_name, get_final_dest_dir, build_output_name, tag_episode_in_name


def _refresh_plex_libraries():
    if not PLEX_REFRESH_URLS:
        return
    for url in PLEX_REFRESH_URLS:
        try:
            import urllib.request
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


def process_file(file_path: Path, row: pd.Series, media_type: str) -> bool:
    # Skip junk/locks
    if not file_path.is_file() or is_lock_file(file_path) or is_nfs_file(file_path):
        return False

    season = int(row["Season"]) if not pd.isna(row["Season"]) else 0
    offset = int(row["Offset"]) if not pd.isna(row["Offset"]) else 0  # kept for episode tag parity
    adult_only = bool(row["AdultOnly"])
    show = str(row.get("Show", "")).strip()
    move_only = bool(row.get("MoveOnly", 0))

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
