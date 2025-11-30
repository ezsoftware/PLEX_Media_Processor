# -*- coding: utf-8 -*-
"""
All package-wide settings derive from JSON config via config_loader.CFG.
No file paths are hard-coded anywhere in code; all paths come from config.json.

Static, non-sensitive regex maps remain here.
"""
from __future__ import annotations
from pathlib import Path
import sys
import re
from typing import List, Dict, Any
from .config_loader import CFG


def _require(cfg: Dict[str, Any], *keys: str):
    """Fetch nested key chain; raise if missing."""
    cur = cfg
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            chain = " -> ".join(keys)
            raise RuntimeError(f"Missing required config key: {chain}")
        cur = cur[k]
    return cur


def _path(val: str) -> Path:
    p = Path(val)
    return p if p.is_absolute() else Path.cwd() / p


# ---------- Paths (all required) ----------
ROOT_DIR = _path(_require(CFG, "paths", "root_dir"))
TV_DIR = _path(_require(CFG, "paths", "tv_dir"))
AO_TV_DIR = _path(_require(CFG, "paths", "ao_tv_dir"))
MOVIE_DIR = _path(_require(CFG, "paths", "movie_dir"))
AO_MOVIE_DIR = _path(_require(CFG, "paths", "ao_movie_dir"))
CSV_FILE_PATH = _path(_require(CFG, "paths", "csv_file_path"))
FAILURE_DIR = _path(_require(CFG, "paths", "failure_dir"))
TMP_BASE_DIR = _path(_require(CFG, "paths", "tmp_base_dir"))

# Per-run locks (files in ROOT_DIR)
ROOT_SLOT_LOCK = ROOT_DIR / ".root_conversion.lock"
SUBDIR_SLOT_LOCK = ROOT_DIR / ".subdir_conversion.lock"

# Movie inbox subdirs under ROOT_DIR (names + adult flag)
_movie_subdirs_cfg = _require(CFG, "paths", "root_movie_subdirs")
if not isinstance(_movie_subdirs_cfg, list):
    raise RuntimeError("paths.root_movie_subdirs must be a list of {name, adult_only} objects")
MOVIE_SUBDIRS = [(str(entry["name"]), bool(entry.get("adult_only", False))) for entry in _movie_subdirs_cfg]

# ---------- Plex ----------
# Build refresh URLs from scheme/ip/port/token/sections
plex_cfg = _require(CFG, "plex")
PLEX_SCHEME = str(plex_cfg.get("scheme", "http")).strip() or "http"
PLEX_IP = str(_require(plex_cfg, "ip")).strip()
PLEX_PORT = int(_require(plex_cfg, "port"))
PLEX_TOKEN = str(_require(plex_cfg, "token")).strip()
PLEX_SECTIONS = [int(s) for s in _require(plex_cfg, "sections")]
PLEX_REFRESH_URLS: List[str] = [
    f"{PLEX_SCHEME}://{PLEX_IP}:{PLEX_PORT}/library/sections/{sid}/refresh?X-Plex-Token={PLEX_TOKEN}"
    for sid in PLEX_SECTIONS
]

# ---------- Encoding / behavior knobs ----------
FORCE_REENCODE = "-r" in sys.argv
PRESET_DEFAULT = int(_require(CFG, "encode", "preset_default"))
TIMEOUT_SECONDS = int(_require(CFG, "encode", "timeout_seconds"))
TV_CRF_FALLBACK = int(_require(CFG, "encode", "tv_crf_fallback"))
MOVIE_CRF_DEFAULTS = dict(_require(CFG, "encode", "movie_crf_defaults"))

# ---------- Temp / retention ----------
STALE_TMP_AGE = int(_require(CFG, "temp", "stale_tmp_age_seconds"))
FAILURE_RETENTION_DAYS = int(_require(CFG, "retention", "failure_retention_days"))
_warn_list = _require(CFG, "retention", "failure_warn_days_before")
FAILURE_WARN_DAYS_BEFORE = tuple(int(x) for x in _warn_list)

# ---------- Static patterns (not sensitive) ----------
EPISODE_PATTERNS = [
    # Matches "E03", "e03", "E3" (not part of a longer token)
    re.compile(r"(?:^|[^A-Za-z0-9])E(\d{1,3})(?!\d)", re.IGNORECASE),

    # Matches "x03", "x3"
    re.compile(r"\bx(\d{1,3})(?!\d)", re.IGNORECASE),

    # Matches a hyphen (any dash) followed by episode number before a bracket/paren/period/end
    # e.g. "Part 2 - 03 [1080p...]" or "S3 - 03 (1080p)" or "Show - 12.mkv"
    re.compile(r"[-–—]\s*(\d{1,3})(?=\s*(?:\[|\(|\.|$))"),

    # Matches "Episode 03", "Ep 03", "Ep.03", "Ep-03"
    re.compile(r"\b(?:Episode|Ep|Ep\.)[\s\.\-:]*?(\d{1,3})\b", re.IGNORECASE),
]

# Filename substitutions for output naming; includes {crf} and {bit}
SUBSTITUTIONS = {
    r'(?i)\b2160p\b': '2160p_AV1_{bit}Bit_C{crf}',
    r'(?i)\b1080p\b': '1080p_AV1_{bit}Bit_C{crf}',
    r'(?i)\b720p\b':  '720p_AV1_{bit}Bit_C{crf}',
    r'(?i)\b(hevc|x265|x264|h\.265|h\.264|avc)\b': 'AV1',
}
