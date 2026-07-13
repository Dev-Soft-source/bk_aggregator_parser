from __future__ import annotations

import re
from pathlib import Path

# Fonbet internal sport id -> Sportradar sport_id (Appendix A)
FONBET_SPORT_TO_REFERENCE: dict[int, int] = {
    1: 1,       # Football (Fonbet) -> reference sport_id 1
    2: 4,       # Hockey -> Ice Hockey
    3: 2,       # Basketball
    4: 5,       # Tennis
    5: 3,       # Baseball
    9: 23,      # Volleyball
    3088: 20,   # Table tennis
    11624: 34,  # Beach volley -> Beach Volley
    11630: 31,  # Badminton
    11634: 21,  # Cricket
    29086: 107,  # Esports
}

# Fallback by Fonbet display name / alias when id is unknown
FONBET_NAME_TO_REFERENCE: dict[str, int] = {
    "football": 1,
    "soccer": 1,
    "hockey": 4,
    "ice hockey": 4,
    "basketball": 2,
    "tennis": 5,
    "baseball": 3,
    "volleyball": 23,
    "table tennis": 20,
    "table-tennis": 20,
    "beach volley": 34,
    "beach-volley": 34,
    "badminton": 31,
    "cricket": 21,
    "esports": 107,
}

# UI / bookmaker-facing labels (Appendix A keeps UOF canonical names e.g. "Soccer").
DISPLAY_NAME_OVERRIDES: dict[int, str] = {
    1: "Football",
}


def display_name_en(reference_sport_id: int | None, appendix_name: str | None) -> str | None:
    """Prefer bookmaker-friendly label; fall back to Appendix A name."""
    if reference_sport_id is not None and reference_sport_id in DISPLAY_NAME_OVERRIDES:
        return DISPLAY_NAME_OVERRIDES[reference_sport_id]
    return appendix_name


_TABLE_ROW = re.compile(
    r"^\|\s*(\d+)\s*\|\s*sr:sport:\d+\s*\|\s*([^|]+?)\s*\|",
    re.IGNORECASE,
)

_FONBET_DIR = Path(__file__).resolve().parent
_REPO_DOCS_APPENDIX = _FONBET_DIR.parent.parent / "docs" / "Appendix_A_sports_EN.md"
_LOCAL_APPENDIX = _FONBET_DIR / "Appendix_A_sports_EN.md"


def resolve_appendix_path(path: Path | None = None) -> Path | None:
    """
    Locate Appendix A sports markdown.

    Order: explicit path (if it exists) → fonbet/Appendix_A_sports_EN.md →
    docs/Appendix_A_sports_EN.md.
    """
    candidates: list[Path] = []
    if path is not None:
        candidates.append(Path(path))
    candidates.extend((_LOCAL_APPENDIX, _REPO_DOCS_APPENDIX))
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            key = candidate.resolve()
        except OSError:
            key = candidate
        if key in seen:
            continue
        seen.add(key)
        if candidate.exists():
            return candidate
    return None


def load_appendix_sports_en(path: Path | None = None) -> dict[int, str]:
    """Parse Appendix_A_sports_EN.md -> {sport_id: name_en}."""
    md_path = resolve_appendix_path(path)
    if md_path is None:
        return {}

    names: dict[int, str] = {}
    for line in md_path.read_text(encoding="utf-8").splitlines():
        match = _TABLE_ROW.match(line.strip())
        if match:
            names[int(match.group(1))] = match.group(2).strip()
    return names


def resolve_reference_sport_id(
    fonbet_sport_id: int,
    name: str | None = None,
    alias: str | None = None,
) -> int | None:
    ref_id = FONBET_SPORT_TO_REFERENCE.get(fonbet_sport_id)
    if ref_id is not None:
        return ref_id

    for key in (name, alias):
        if not key:
            continue
        ref_id = FONBET_NAME_TO_REFERENCE.get(key.strip().lower())
        if ref_id is not None:
            return ref_id
    return None


def resolve_name_en(
    fonbet_sport_id: int,
    appendix: dict[int, str],
    name: str | None = None,
    alias: str | None = None,
) -> tuple[int | None, str | None]:
    ref_id = resolve_reference_sport_id(fonbet_sport_id, name, alias)
    if ref_id is None:
        return None, None
    appendix_name = appendix.get(ref_id)
    return ref_id, display_name_en(ref_id, appendix_name)
