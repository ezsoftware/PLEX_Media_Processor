import re

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



def tag_episode_in_name(original_name: str, base_name: str, season: int, offset: int) -> str:
    # If already tagged, leave it alone
    if re.search(r"S\d{2}E\d{2}", base_name, re.IGNORECASE):
        return base_name

    ep_num = None
    ep_ver = None
    for pat in EPISODE_PATTERNS:
        m = pat.search(original_name)
        print(original_name)
        print(m)
        if m:
            try:
                ep_num = int(m.group(1))
                ep_ver = str(m.group(2))
                break
            except Exception:
                pass
    if ep_num is None:
        return base_name

    # need to support negative offsets for issues where the release has "Part 2" in the name and episode numbering reset
    corrected_episode = ep_num - offset 
    print(ep_num)
    print(offset)
    print(corrected_episode)
    if corrected_episode < 1:
        corrected_episode = ep_num

    ep_fmt = f"S{season:02d}E{corrected_episode:02d}"

    # Check for the presence of " - " followed by a digit and replace it if found
    if isinstance(ep_ver, str) and ep_ver.strip():
        base_name = re.sub(r"(?: - )\d{1,3}", f" - {ep_fmt} ", base_name)
    else:
        base_name = re.sub(r"(?: - )\d{1,3}", f" - {ep_fmt}", base_name)
    
    return base_name

# Test the function with your input
original_name = "[Erai-raws] Uma Musume - Cinderella Gray Part 2 - 03 [1080p AMZN WEB-DL AVC EAC3][MultiSub][DA622436].mkv"
base_name = original_name
season = 1
offset = -14

new_name = tag_episode_in_name(original_name, base_name, season, offset)
print(new_name)  # Expected: "[SubsPlease] Clevatess - S01E11v3 (1080p) [D2EECB67].mkv"
