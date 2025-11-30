# -*- coding: utf-8 -*-
"""
Centralized configuration loader for process_media.

Rules:
- The ONLY active config is JSON.
- Load order:
    1) Path from env var PM_CONFIG_PATH (if set), else
    2) ./config.json located at the repository root (sibling of process_media/)

- A companion file named config.default.json is OPTIONAL and NEVER LOADED.
  It exists only as an example template for users to copy to config.json.

If no config is found, raise a clear RuntimeError.
"""

from __future__ import annotations
import os
import json
from pathlib import Path
from typing import Any, Dict


def _repo_root() -> Path:
    # repo_root/.../process_media/config_loader.py -> repo_root
    return Path(__file__).resolve().parent.parent


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise RuntimeError(f"Failed to parse JSON config at {path}: {e}") from e


def load_cfg() -> Dict[str, Any]:
    # 1) Env var wins
    env_path = os.environ.get("PM_CONFIG_PATH", "").strip()
    if env_path:
        p = Path(env_path)
        if not p.exists():
            raise RuntimeError(f"PM_CONFIG_PATH points to a missing file: {p}")
        return _read_json(p)

    # 2) Local config.json at repo root
    repo_root = _repo_root()
    local = repo_root / "config.json"
    if local.exists():
        return _read_json(local)

    # Nothing found
    raise RuntimeError(
        "No configuration found. Provide a JSON config via PM_CONFIG_PATH or create config.json at the repo root. "
        "config.default.json is only an example and is never loaded."
    )


# Public singleton for the package to import
CFG = load_cfg()
