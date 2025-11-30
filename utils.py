import os
import shutil
import time
from pathlib import Path
from contextlib import contextmanager
from .config import STALE_TMP_AGE, ROOT_SLOT_LOCK, SUBDIR_SLOT_LOCK, TMP_BASE_DIR
from .logging_setup import logger


# ---------- Sanitization ----------
def sanitize_folder_name(name: str) -> str:
    """
    Remove or strip reserved characters for cross-platform safety (Windows/Linux).
    """
    reserved = r'<>:"/\\|?*'
    trans = str.maketrans("", "", reserved)
    cleaned = name.translate(trans).strip()
    # Remove trailing dots/spaces (invalid on Windows)
    return cleaned.rstrip(" .")


# ---------- Temp dir management ----------
def cleanup_stale_tmp_dirs(base_dir: Path, max_age: int = STALE_TMP_AGE) -> None:
    """
    Remove any TMP subdirs older than max_age seconds.
    Logs a warning if a stale directory is found and removed.
    """
    if not base_dir.exists():
        return
    now = time.time()
    for sub in base_dir.iterdir():
        try:
            if not sub.is_dir():
                continue
            age = now - sub.stat().st_mtime
            if age > max_age:
                shutil.rmtree(sub, ignore_errors=True)
                logger.warning(
                    f"Removed stale TMP dir {sub} (age {age/3600:.1f}h > {max_age/3600:.1f}h)"
                )
        except Exception as e:
            logger.error(f"Failed to check/remove stale TMP dir {sub}: {e}")


def get_tmp_dir() -> Path:
    """
    Return a process-specific TMP dir (<TMP_BASE_DIR>/<pid>).
    Creates it if missing. Also runs stale cleanup each call.
    """
    base = TMP_BASE_DIR
    base.mkdir(parents=True, exist_ok=True)
    cleanup_stale_tmp_dirs(base, STALE_TMP_AGE)
    pid_dir = base / str(os.getpid())
    pid_dir.mkdir(parents=True, exist_ok=True)
    return pid_dir


# ---------- Slot locking (coarse-grained) ----------
def _lock_dir_atomic(lock_path: Path):
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
        os.write(fd, str(os.getpid()).encode())
        return fd
    except FileExistsError:
        return None
    except Exception as e:
        logger.error(f"Unexpected error creating lock {lock_path}: {e}")
        return None


def _unlock_dir_fd(lock_path: Path, fd):
    try:
        if fd is not None:
            os.close(fd)
        if lock_path.exists():
            lock_path.unlink()
    except Exception as e:
        logger.warning(f"Failed to release lock {lock_path}: {e}")


@contextmanager
def with_lock(lock_path: Path):
    fd = _lock_dir_atomic(lock_path)
    try:
        if fd is None:
            yield False
        else:
            yield True
    finally:
        if fd is not None:
            _unlock_dir_fd(lock_path, fd)


# ---------- File sidecar lock (fine-grained; prevents double-processing) ----------
@contextmanager
def file_sidecar_lock(p: Path):
    """
    Create <filename>.lock alongside the file to claim it for this run.
    If the lock already exists, yield False (skip this file).
    Lock is removed automatically on exit.
    """
    lock = p.with_suffix(p.suffix + ".lock")
    fd = None
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_RDWR)
        os.write(fd, str(os.getpid()).encode())
    except FileExistsError:
        yield False
        return
    except Exception as e:
        logger.warning(f"Could not create sidecar lock for {p.name}: {e}")
        yield False
        return

    try:
        yield True
    finally:
        try:
            if fd is not None:
                os.close(fd)
            lock.unlink(missing_ok=True)
        except Exception:
            pass


# ---------- Skips ----------
def is_lock_file(path: Path) -> bool:
    try:
        return path.resolve() in {ROOT_SLOT_LOCK.resolve(), SUBDIR_SLOT_LOCK.resolve()} or path.suffix == ".lock"
    except FileNotFoundError:
        return path.suffix == ".lock"


def is_nfs_file(path: Path) -> bool:
    return path.name.startswith(".nfs")
