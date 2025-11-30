import subprocess
import re
import time
from pathlib import Path
from .logging_setup import logger
from .config import PRESET_DEFAULT, TIMEOUT_SECONDS, TV_CRF_FALLBACK, MOVIE_CRF_DEFAULTS
from .utils import get_tmp_dir

VMAF_CRF_CACHE = {}


def detect_resolution_from_name(name: str) -> str:
    for tag in ["2160p", "1080p", "720p", "480p"]:
        if tag in name.lower():
            return tag
    return "unknown"


def calculate_vmaf_crf(file_path: Path, show: str) -> int | None:
    res = detect_resolution_from_name(file_path.name)
    cache_key = (show.strip().lower(), res, PRESET_DEFAULT)
    if cache_key in VMAF_CRF_CACHE:
        return VMAF_CRF_CACHE[cache_key]

    # quick check: has a video stream?
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_streams", str(file_path)],
            capture_output=True, text=True, check=False
        )
        if r.returncode != 0 or "codec_type=video" not in r.stdout:
            logger.warning(f"No video stream detected in {file_path.name}; skipping VMAF.")
            return None
    except Exception:
        return None

    TMP_DIR = get_tmp_dir()
    logger.info(f"[ab-av1] Working directory: {TMP_DIR}")
    remux_path = TMP_DIR / (file_path.stem + ".vmafprobe.mkv")
    probe_input = file_path

    # Lightweight remux for probe input
    try:
        cmd = ["ffmpeg", "-y", "-i", str(file_path), "-map", "0:v:0", "-c", "copy", str(remux_path)]
        rr = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=str(TMP_DIR))
        if rr.returncode == 0 and remux_path.exists() and remux_path.stat().st_size > 0:
            probe_input = remux_path
            logger.info(f"[ab-av1] Using remuxed probe source: {remux_path.name}")
    except Exception as e:
        logger.warning(f"Remux for probe threw exception for {file_path.name}: {e}")

    def run_once(inp: Path):
        t0 = time.time()
        try:
            r = subprocess.run(
                ["ab-av1", "crf-search", "--max-crf", "40", "--min-crf", "26",
                 "--min-vmaf", "92", "--input", str(inp), "--preset", str(PRESET_DEFAULT)],
                capture_output=True, text=True, check=True, cwd=str(TMP_DIR), timeout=TIMEOUT_SECONDS
            )
            m = re.search(r"crf\s+(\d+)", r.stdout, re.I)
            return (int(m.group(1)) if m else None), (time.time() - t0), (r.stderr or "")[:500]
        except subprocess.TimeoutExpired as e:
            return None, (time.time() - t0), ((e.stderr or "")[:500] if hasattr(e, "stderr") else "")
        except subprocess.CalledProcessError as e:
            return None, (time.time() - t0), (e.stderr or "")[:500]
        except Exception as e:
            return None, (time.time() - t0), str(e)[:500]

    crf, elapsed, err = run_once(probe_input)
    if crf is None and probe_input != file_path:
        crf2, elapsed2, err2 = run_once(file_path)
        elapsed += elapsed2
        crf = crf2 if crf2 is not None else None

    try:
        if remux_path.exists():
            remux_path.unlink()
    except Exception:
        pass

    if crf is not None:
        VMAF_CRF_CACHE[cache_key] = crf
        logger.info(f"[ab-av1] Optimal CRF {crf} for {file_path.name} ({res}) @ preset {PRESET_DEFAULT} in {elapsed:.1f}s")
        return crf

    logger.warning(f"[ab-av1] CRF search failed for {file_path.name}: {err}")
    return None


def default_crf_for_movie(profile: str) -> int:
    return MOVIE_CRF_DEFAULTS.get(profile, 32)


def determine_crf(row, file_path: Path, show: str, tv_like: bool):
    crf_val = row.get("CRF", "")
    if isinstance(crf_val, str) and crf_val.strip().lower() == "vmaf":
        vmaf_crf = calculate_vmaf_crf(file_path, show)
        if vmaf_crf is None:
            return TV_CRF_FALLBACK
        return vmaf_crf - 4

    try:
        return int(crf_val)
    except Exception:
        return TV_CRF_FALLBACK
