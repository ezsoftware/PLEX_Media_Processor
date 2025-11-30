import re
import json
import urllib.request
from .logging_setup import logger
from .logging_setup import LOGS_DIR

ANILIST_CACHE_FILE = LOGS_DIR / 'anilist_cache.json'
try:
    if ANILIST_CACHE_FILE.exists():
        with open(ANILIST_CACHE_FILE, 'r', encoding='utf-8') as f:
            ANILIST_CACHE = json.load(f)
    else:
        ANILIST_CACHE = {}
except Exception:
    ANILIST_CACHE = {}

def _save_cache():
    try:
        with open(ANILIST_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(ANILIST_CACHE, f)
    except Exception as e:
        logger.warning(f"Failed to save AniList cache: {e}")

def extract_title_from_filename(filename: str) -> str:
    name = re.sub(r'^\[[^\]]+\]\s*', '', filename)
    name = re.sub(r'\.[a-zA-Z0-9]{2,4}$', '', name)
    name = re.sub(r'\([^)]*\)', '', name)
    name = re.sub(r'\[[^\]]*\]', '', name)
    name = name.replace('_', ' ').replace('.', ' ')
        # Strip trailing " - 22" or " - 22v2" style episode markers from title
    name = re.split(r'\s+-\s+\d{1,4}(?:v\d+)?\b?', name, maxsplit=1)[0]
    name = re.sub(r'\b(S(?:eason)?\s*\d{1,2})\b', '', name, flags=re.I)
    name = re.sub(r'\b(480p|720p|1080p|2160p|4k|x264|x265|hevc|avc|h\.?264|h\.?265|webrip|web[- ]?dl|bluray|brrip|repack)\b', '', name, flags=re.I)
    name = re.sub(r'\b\d{1,4}\b$', '', name)
    name = re.sub(r'\s+', ' ', name).strip(' .-_')
    return name

def lookup_anilist(query: str):
    if not query:
        return None, None
    key = query.strip().lower()
    if key in ANILIST_CACHE:
        cached = ANILIST_CACHE[key]
        return cached.get("title"), cached.get("year")
    gql = '{ Media(search: "%s", type: ANIME) { title { english romaji } startDate { year } } }' % query.replace('"','')
    req = urllib.request.Request(
        'https://graphql.anilist.co',
        data=json.dumps({'query': gql}).encode(),
        headers={'Content-Type':'application/json'}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.load(resp)
        media = data.get('data',{}).get('Media')
        if media:
            title = (media['title'].get('english') or media['title'].get('romaji') or '').strip() or None
            year = media['startDate'].get('year')
            ANILIST_CACHE[key] = {"title": title, "year": year}
            _save_cache()
            return title, year
    except Exception as e:
        logger.warning(f"AniList lookup failed for {query}: {e}")
    return None, None

def lookup_jikan(query: str):
    if not query:
        return None, None
    try:
        import urllib.parse
        url = f"https://api.jikan.moe/v4/anime?q={urllib.parse.quote(query)}&limit=5&sfw=true&order_by=members&sort=desc"
        req = urllib.request.Request(url, headers={'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.load(resp)
        items = data.get('data') or []
        if not items:
            return None, None
        best = items[0]
        title = (best.get('title_english') or best.get('title') or '').strip() or None
        aired_from = (best.get('aired') or {}).get('from') or ''
        year = None
        if aired_from and isinstance(aired_from, str) and len(aired_from) >= 4 and aired_from[:4].isdigit():
            year = int(aired_from[:4])
        return title, year
    except Exception as e:
        logger.warning(f"Jikan lookup failed for {query}: {e}")
        return None, None
