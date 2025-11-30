from pathlib import Path
import re
from .utils import sanitize_folder_name
from .config import EPISODE_PATTERNS, SUBSTITUTIONS

# Year detection for movie filenames
MOVIE_YEAR_RE = re.compile(r'(?<!\d)(19\d{2}|20\d{2})(?!\d)')


def _clean_title_segment(seg: str) -> str:
    seg = re.sub(r'[._]+', ' ', seg)
    seg = re.sub(r'\s+', ' ', seg).strip()
    small = {
        "a", "an", "and", "as", "at", "but", "by", "for", "from", 
        "in", "into", "nor", "of", "on", "or", "over", "per", 
        "the", "to", "via", "with"
    }
    words = seg.split()
    out = []
    for i, w in enumerate(words):
        lw = w.lower()
        if i not in (0, len(words) - 1) and lw in small:
            out.append(lw)
        else:
            out.append(w if (w.isupper() and len(w) > 1) else w.capitalize())
    return " ".join(out)


def parse_movie_title_year_from_filename(file_path: Path) -> tuple[str, int | None]:
    stem = file_path.stem
    m = MOVIE_YEAR_RE.search(stem)
    if not m:
        clip = re.split(
            r'\b(1080p|2160p|720p|480p|WEB[- ]?DL|WEBRip|BluRay|BRRip|REPACK)\b',
            stem, maxsplit=1
        )[0]
        return _clean_title_segment(clip), None
    year = int(m.group(1))
    title_part = stem[:m.start()]
    title = _clean_title_segment(title_part) or _clean_title_segment(stem[:m.end()])
    return title, year


def derive_movie_folder_name(file_path: Path) -> str:
    title, year = parse_movie_title_year_from_filename(file_path)
    return f"{title} ({year})" if year else title


def get_final_dest_dir(base_dir: Path, show: str, tv_like: bool, season: int = 0) -> Path:
    return base_dir / sanitize_folder_name(show) / (f"Season {season:02d}" if tv_like and season else "")


def build_output_name(stem: str, crf: int, bit: int) -> str:
    """
    Apply substitutions and CRF/Bit tag (e.g., 1080p -> 1080p_AV1_10Bit_C40).
    'bit' is 8 or 10 depending on source.
    """
    name = stem
    for pat, repl in SUBSTITUTIONS.items():
        name = re.sub(pat, repl.format(crf=crf, bit=bit), name)
    return name


def tag_episode_in_name(original_name: str, base_name: str, season: int, offset: int) -> str:
    # If already tagged, leave it alone
    if re.search(r"S\d{2}E\d{2}", base_name, re.IGNORECASE):
        return base_name

    ep_num = None
    ep_ver = None
    for pat in EPISODE_PATTERNS:
        m = pat.search(original_name)
        if m:
            try:
                ep_num = int(m.group(1))
                ep_ver = str(m.group(2))
                break
            except Exception:
                pass
    if ep_num is None:
        return base_name

    corrected_episode = ep_num - offset if offset > 0 else ep_num
    if corrected_episode < 1:
        corrected_episode = ep_num

    ep_fmt = f"S{season:02d}E{corrected_episode:02d}"

    # Check for the presence of " - " followed by a digit and replace it if found
    if isinstance(ep_ver, str) and ep_ver.strip():
        base_name = re.sub(r"(?: - )\d{1,3}", f" - {ep_fmt} ", base_name)
    else:
        base_name = re.sub(r"(?: - )\d{1,3}", f" - {ep_fmt}", base_name)
    
    return base_name
