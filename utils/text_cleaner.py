"""
File-name cleaning and volume extraction.

Comic files downloaded from websites and Telegram channels usually carry
advertising noise in their names::

    Batman 001 (2016) [دانلود از سایت example.com] @my_channel
    Spider-Man_Vol_1_#05_[www.ircomics.com] (Digital)

``clean_name`` removes that noise while keeping the meaningful parts (title,
volume, year, issue number). ``extract_volume_number`` finds the issue/volume
number used by the import algorithm.

The rules are deliberately conservative: anything inside brackets is only
dropped when it looks like an advertisement or a generic release tag, and the
original name is never lost because the importer shows a preview before saving.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

# ---------------------------------------------------------------- URLs / links
_NOISE_CHARS = r"[^\s\[\]\(\)\{\}<>\"'|]"
_NOISE = _NOISE_CHARS + "*"
_NOISE_REQUIRED = _NOISE_CHARS + "+"
_URL_RE = re.compile(rf"(?:https?://|ftp://){_NOISE_REQUIRED}", re.IGNORECASE)
_WWW_RE = re.compile(rf"\bwww\.{_NOISE_REQUIRED}", re.IGNORECASE)

# Common top level domains seen in pirated/comic download names. Matching is
# restricted to a known list so that titles such as "Mr. Robot" are untouched.
_TLDS = (
    "com|net|org|ir|me|tv|co|io|xyz|info|site|online|club|link|app|dev|blog|"
    "shop|store|top|website|space|fun|live|pro|biz|us|uk|de|fr|ru|tr|ar|ca"
)
_DOMAIN_RE = re.compile(
    rf"(?<![\w@.])(?:[\w-]+\.)+(?:{_TLDS})(?:/{_NOISE_REQUIRED})?\b", re.IGNORECASE
)

# Telegram / Instagram / social handles
_TME_RE = re.compile(rf"\bt\.me/{_NOISE_REQUIRED}", re.IGNORECASE)
_SOCIAL_RE = re.compile(
    rf"\b(?:telegram|instagram|facebook|twitter|youtube|whatsapp|"
    rf"t\.me|insta|joinchat)\b\s*[:/\-]?\s*{_NOISE}?",
    re.IGNORECASE,
)
_HANDLE_RE = re.compile(r"(?<!\w)@[\w.]{2,}", re.UNICODE)

# Advertising phrases (Persian + English). Matched case-insensitively and
# stripped together with whatever follows them on the same segment.
# An advert can run for a few words ("دانلود از کانال کمیک"), so phrases that
# start one swallow up to four following words. Volume numbers come from the
# original file name, not from the cleaned title, so this is safe.
_AD_TAIL = rf"(?:\s+{_NOISE}){{0,4}}"

_AD_PHRASES: Tuple[str, ...] = (
    rf"دانلود\s+از\s+سایت{_AD_TAIL}",
    rf"دانلود\s+از{_AD_TAIL}",
    rf"دانلود\s+رایگان{_AD_TAIL}",
    rf"دانلود\s+کمیک{_AD_TAIL}",
    rf"بهترین\s+سایت{_AD_TAIL}",
    rf"سایت\s+کمیک{_AD_TAIL}",
    rf"کانال\s+ما{_AD_TAIL}",
    rf"کانال\s+تلگرام{_AD_TAIL}",
    rf"کانال\s*[:/\-]?\s*{_NOISE_REQUIRED}{_AD_TAIL}",
    rf"تبلیغ\s*[:/\-]?\s*{_NOISE}{_AD_TAIL}",
    rf"عضو\s+شوید{_AD_TAIL}",
    rf"عضو\s+کانال{_AD_TAIL}",
    rf"برای\s+خرید{_AD_TAIL}",
    rf"ادامه\s+مطلب{_AD_TAIL}",
    rf"مشاهده\s+سایت{_AD_TAIL}",
    rf"ترجمه\s+اختصاصی{_AD_TAIL}",
    rf"اختصاصی\s+کانال{_AD_TAIL}",
    rf"با\s+کیفیت\s+عالی{_AD_TAIL}",
    rf"لینک\s+دانلود{_AD_TAIL}",
    rf"downloaded\s+from{_AD_TAIL}",
    rf"read\s+(?:more|online)\s*(?:at|on)?{_AD_TAIL}",
    rf"free\s+download{_AD_TAIL}",
    rf"visit\s+(?:us|our\s+site){_AD_TAIL}",
    rf"join\s+(?:us|our\s+channel){_AD_TAIL}",
    rf"follow\s+us{_AD_TAIL}",
    rf"subscribe{_AD_TAIL}",
    rf"support\s+us{_AD_TAIL}",
)
_AD_RE = re.compile("|".join(f"(?:{p})" for p in _AD_PHRASES), re.IGNORECASE)

# Generic release tags that only add noise inside brackets.
_RELEASE_TAGS = {
    "digital",
    "webrip",
    "web-dl",
    "webdl",
    "scan",
    "scanned",
    "c2c",
    "fixed",
    "repack",
    "complete",
    "ongoing",
    "hd",
    "1080p",
    "720p",
    "480p",
    "2160p",
    "4k",
    "true",
    "retail",
    "minutemen",
    "glorith",
    "empire",
    "zone-empire",
    "zone",
    "dcp",
    "dcp-minutemen",
}

_BRACKETS_RE = re.compile(r"[\[\(\{]([^\[\]\(\)\{\}]*)[\]\)\}]", re.UNICODE)
_EMPTY_BRACKETS_RE = re.compile(r"[\[\(\{]\s*[\]\)\}]")
_SEPARATORS_RE = re.compile(r"[\s\-_.,;:|/\\]+")
_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def normalize_digits(text: str) -> str:
    """Convert Persian/Arabic-Indic digits to ASCII digits."""
    return str(text).translate(_PERSIAN_DIGITS)


def _has_ad_signal(inner: str) -> bool:
    """True when bracket content is a link, a handle or an advert."""
    return any(
        pattern.search(inner)
        for pattern in (
            _URL_RE,
            _WWW_RE,
            _TME_RE,
            _DOMAIN_RE,
            _SOCIAL_RE,
            _HANDLE_RE,
            _AD_RE,
        )
    )


def _is_noise_bracket(inner: str) -> bool:
    """Decide whether a whole bracket can be removed."""
    if _has_ad_signal(inner):
        return True

    cleaned = _DOMAIN_RE.sub(" ", inner)
    core = re.sub(r"[\s\-_.,;:|/\\]+", " ", cleaned).strip().lower()
    if not core:
        return True
    if core in _RELEASE_TAGS:
        return True

    tokens = core.replace("-", " ").split()
    if len(tokens) <= 3 and all(token in _RELEASE_TAGS for token in tokens):
        return True
    return False


def _strip_bracketed_noise(text: str) -> str:
    """Remove brackets whose content is advertising or a generic release tag."""

    def replace(match: re.Match) -> str:
        if _is_noise_bracket(match.group(1)):
            return " "
        return match.group(0)

    previous = None
    while previous != text:
        previous = text
        text = _BRACKETS_RE.sub(replace, text)
    return text


def _drop_unbalanced_brackets(text: str) -> str:
    """Remove bracket characters that no longer have a partner."""
    pairs = (("[", "]"), ("(", ")"), ("{", "}"))
    for opening, closing in pairs:
        if text.count(opening) != text.count(closing):
            text = text.replace(opening, " ").replace(closing, " ")
    return text


def clean_name(text: str, strip_release_tags: bool = True) -> str:
    """Return *text* without links, handles, ad phrases or empty brackets."""
    if not text:
        return ""

    original = str(text)
    result = unicodedata.normalize("NFC", original)

    if strip_release_tags:
        result = _strip_bracketed_noise(result)

    result = _TME_RE.sub(" ", result)
    result = _URL_RE.sub(" ", result)
    result = _WWW_RE.sub(" ", result)
    result = _DOMAIN_RE.sub(" ", result)
    result = _SOCIAL_RE.sub(" ", result)
    result = _HANDLE_RE.sub(" ", result)
    result = _AD_RE.sub(" ", result)

    # Collapse the leftovers: duplicated separators, empty brackets, stray dots.
    result = _EMPTY_BRACKETS_RE.sub(" ", result)
    result = re.sub(r"\([\s\-_.:,;/|]*\)", " ", result)
    result = re.sub(r"\[[\s\-_.:,;/|]*\]", " ", result)
    result = re.sub(r"[\[\{]\s+", "[", result)
    result = re.sub(r"\s+[\]\}]", "]", result)
    result = re.sub(r"\(\s+", "(", result)
    result = re.sub(r"\s+\)", ")", result)
    result = re.sub(r"\s*([\-|/])\s*(?=[\-|/])", "", result)
    result = result.replace("_", " ")
    result = re.sub(r"\s{2,}", " ", result)
    result = _drop_unbalanced_brackets(result)
    result = result.strip(" -_.|,;:،؛")

    # A name that became empty (rare: the whole name was an advert) falls back to
    # the original so files never lose their identity.
    if not result.strip():
        return original.strip()

    return result


def clean_file_stem(filepath: str, strip_release_tags: bool = True) -> str:
    """Clean the file name (without its comic extension) of a path.

    ``Path.stem`` is not used because a name such as ``Batman [www.site.com]``
    would lose everything after the first dot. Only known comic extensions are
    removed.
    """
    from config import ALL_EXTENSIONS

    name = Path(filepath).name
    lowered = name.lower()
    for extension in ALL_EXTENSIONS:
        if lowered.endswith(extension) and len(name) > len(extension):
            name = name[: -len(extension)]
            break
    return clean_name(name, strip_release_tags=strip_release_tags)


def clean_series_name(folder_name: str) -> str:
    """Clean a folder name so it can be used as a series name."""
    return clean_name(folder_name)


# ---------------------------------------------------------------- volumes
_YEAR_RE = re.compile(r"(?:19|20)\d{2}")
_RESOLUTION_NUMBERS = {360, 480, 576, 720, 1080, 1440, 2160, 4320}
_RANGE_RE = re.compile(r"(?<![\d])(\d{1,4})\s*[-–~]\s*(\d{1,4})(?![\d])")

_VOLUME_PATTERNS = (
    re.compile(
        r"(?:\bvol(?:ume)?\b|\bv\b|\bجلد\b|\bشماره\b|\bقسمت\b|\bchapter\b|"
        r"\bchap\b|\bch\b|\bissue\b|\bbook\b)\s*[._\-:# ]?\s*(\d{1,4})",
        re.IGNORECASE,
    ),
    re.compile(r"#\s*(\d{1,4})"),
    re.compile(r"(?<![\d])(\d{1,4})\s*(?:of|از)\s*\d{1,4}(?![\d])", re.IGNORECASE),
)

_STANDALONE_RE = re.compile(r"(?<![\d])(\d{1,4})(?![\d])")


def _is_noise_number(value: int, token: str) -> bool:
    if value in _RESOLUTION_NUMBERS:
        return True
    if len(token) == 4 and 1900 <= value <= 2099:
        return True
    return False


def extract_volume_number(name: str) -> Optional[int]:
    """Extract the volume/issue number from a file or folder name.

    Explicit markers ("vol 3", "جلد ۳", "#5") win; otherwise the first
    meaningful standalone number is used, ignoring years and resolutions.
    """
    if not name:
        return None

    text = normalize_digits(str(name))

    for pattern in _VOLUME_PATTERNS:
        match = pattern.search(text)
        if match:
            return int(match.group(1))

    # A range such as "Batman 001-003" describes issues 1..3; the lowest wins.
    range_match = _RANGE_RE.search(text)
    if range_match:
        first = int(range_match.group(1))
        if not _is_noise_number(first, range_match.group(1)):
            return first

    candidates: List[Tuple[int, str]] = []
    for match in _STANDALONE_RE.finditer(text):
        token = match.group(1)
        value = int(token)
        if _is_noise_number(value, token):
            continue
        candidates.append((value, token))

    if not candidates:
        return None

    # Prefer zero-padded numbers ("001"), which are almost always issue numbers.
    padded = [candidate for candidate in candidates if len(candidate[1]) > 1 and candidate[1].startswith("0")]
    if padded:
        return padded[0][0]

    return candidates[0][0]


def looks_like_volume_series(names: Iterable[str], threshold: float = 0.6) -> bool:
    """True when most names in a series carry a usable volume number."""
    names = list(names)
    if not names:
        return False
    found = sum(1 for name in names if extract_volume_number(name) is not None)
    return (found / len(names)) >= threshold
