import subprocess
import json
from pathlib import Path
from typing import List, Dict, Any
from .logging_setup import logger
from .config import PRESET_DEFAULT

def run_ffprobe_json(args: List[str]) -> Dict[str, Any]:
    try:
        p = subprocess.run(args, capture_output=True, text=True, check=True)
        return json.loads(p.stdout or "{}")
    except Exception as e:
        logger.warning("ffprobe failed: %s", e)
        return {}

def probe_streams_with_indices(input_path: Path) -> List[Dict[str, Any]]:
    info = run_ffprobe_json([
        "ffprobe", "-v", "error",
        "-show_streams", "-of", "json",
        str(input_path),
    ])
    streams = info.get("streams") or []
    counters = {"video": 0, "audio": 0, "subtitle": 0, "data": 0, "attachment": 0}
    type_letter = {"video": "v", "audio": "a", "subtitle": "s", "data": "d", "attachment": "t"}
    for s in streams:
        ctype = s.get("codec_type", "")
        if ctype not in counters:
            if ctype == "unknown":
                ctype = "data"
                s["codec_type"] = "data"
            else:
                continue
        s["_per_type_index"] = counters[ctype]
        s["_type_letter"] = type_letter[ctype]
        counters[ctype] += 1
    return streams

def video_indices_marked_attached_pic(streams: List[Dict[str, Any]]) -> List[int]:
    out = []
    for s in streams:
        if s.get("codec_type") == "video":
            disp = s.get("disposition") or {}
            if disp.get("attached_pic", 0) == 1:
                out.append(int(s.get("_per_type_index", 0)))
    return out

def get_source_bit_depth(file_path: Path) -> int:
    """
    Return 10 for 10-bit sources (yuv420p10le, p10, etc.), else 8.
    """
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error",
             "-select_streams", "v:0",
             "-show_entries", "stream=pix_fmt,bits_per_raw_sample",
             "-of", "json", str(file_path)],
            capture_output=True, text=True, check=True
        )
        info = json.loads(r.stdout or "{}")
        s = (info.get("streams") or [{}])[0]
        pix = (s.get("pix_fmt") or "").lower()
        bprs = str(s.get("bits_per_raw_sample") or "").strip()
        if "10" in pix or "p10" in pix or bprs == "10":
            return 10
    except Exception as e:
        logger.warning(f"ffprobe bit-depth detection failed for {file_path.name}: {e}")
    return 8

def choose_output_pix_fmt_from_bit(bit: int) -> str:
    return "yuv420p10le" if bit >= 10 else "yuv420p"

def get_duration_seconds(file_path: Path) -> float | None:
    """
    Probe the container duration in seconds.
    """
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error",
             "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(file_path)],
            capture_output=True, text=True, check=True
        )
        s = (r.stdout or "").strip()
        return float(s) if s else None
    except Exception as e:
        logger.warning(f"ffprobe duration failed for {file_path.name}: {e}")
        return None

def build_ffmpeg_cmd(file_path: Path, output_path: Path, crf: int):
    """
    Build ffmpeg command that copies all non-video streams and encodes only video streams to AV1,
    matching source bit depth (8 or 10).
    """
    streams = probe_streams_with_indices(file_path)
    attached_pic_vid_idxs = video_indices_marked_attached_pic(streams)

    bit = get_source_bit_depth(file_path)
    pix_fmt = choose_output_pix_fmt_from_bit(bit)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(file_path),
        "-map", "0",
        "-map_chapters", "0",
        "-map_metadata", "0",
        "-c", "copy",
        "-c:v", "libsvtav1",
        "-preset", str(PRESET_DEFAULT),
        "-crf", str(crf),
        "-pix_fmt", pix_fmt,
        "-g", "240",
        "-svtav1-params", "tune=0",
    ]
    for vid_idx in attached_pic_vid_idxs:
        cmd += [f"-c:v:{vid_idx}", "copy"]
    cmd += [str(output_path)]
    return cmd
