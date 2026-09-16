"""Per-character font fallback for the translation overlay renderer.

Pillow binds exactly one font file per ``ImageFont.truetype()`` call, and a
single file rarely covers more than a couple of scripts. Rendering Simplified
Chinese with a Japanese font therefore produces ``.notdef`` boxes (tofu) even
though both are "CJK". This module answers two questions for the renderer:

    * which single font covers the most of this line (``resolve_font_for_text``)
    * how do I split a line that no single font covers (``split_by_coverage``)

Reading a font's cmap costs ~100 ms per file, so every lookup is cached at
module level and the resolver is safe to call once per rendered line.
"""

import logging
import os
import subprocess
import sys
from typing import (
    Dict,
    FrozenSet,
    Iterable,
    List,
    NamedTuple,
    Optional,
    Sequence,
    Tuple,
)

logger = logging.getLogger(__name__)

try:
    from fontTools.ttLib import TTFont

    FONTTOOLS_AVAILABLE = True
except ImportError:  # Optional dependency; we degrade to the curated tables below.
    TTFont = None  # type: ignore[assignment]
    FONTTOOLS_AVAILABLE = False


class FontFace(NamedTuple):
    """One renderable face. ``index`` is the face inside a .ttc/.otc collection."""

    path: str
    index: int = 0


# Script tags used as keys into the per-platform tables. Han is split into the
# four regional variants because Unicode unifies their codepoints but the fonts
# do not: a cmap lookup cannot tell "this is Japanese", so the caller-visible
# text has to be classified first (see _han_variant).
LATIN = "latin"
CYRILLIC = "cyrillic"
GREEK = "greek"
HAN_SC = "han_sc"
HAN_TC = "han_tc"
JAPANESE = "japanese"
KOREAN = "korean"
ARABIC = "arabic"
HEBREW = "hebrew"
THAI = "thai"
DEVANAGARI = "devanagari"

# Fallback order for Han when the script the line asked for comes up short.
_CJK_SCRIPTS = (HAN_SC, HAN_TC, JAPANESE, KOREAN)

# How narrow a script's font support is. A line mixing Latin with Chinese has to
# be resolved against the Chinese font, because the Latin fonts almost never
# carry Han while the Han fonts almost always carry Latin.
_SCRIPT_SPECIFICITY: Dict[str, int] = {
    HAN_SC: 0,
    HAN_TC: 0,
    JAPANESE: 0,
    KOREAN: 0,
    THAI: 0,
    DEVANAGARI: 0,
    ARABIC: 1,
    HEBREW: 1,
    GREEK: 2,
    CYRILLIC: 2,
    LATIN: 3,
}

# Inclusive codepoint ranges per script. Ordered most-specific first so that the
# CJK blocks are tested before the generic Han block.
_SCRIPT_RANGES: Tuple[Tuple[str, Tuple[Tuple[int, int], ...]], ...] = (
    (
        JAPANESE,
        (
            (0x3040, 0x309F),  # Hiragana
            (0x30A0, 0x30FF),  # Katakana
            (0x31F0, 0x31FF),  # Katakana phonetic extensions
            (0xFF66, 0xFF9F),  # Halfwidth katakana
        ),
    ),
    (
        KOREAN,
        (
            (0x1100, 0x11FF),  # Hangul Jamo
            (0x3130, 0x318F),  # Hangul compatibility Jamo
            (0xA960, 0xA97F),  # Hangul Jamo extended-A
            (0xAC00, 0xD7A3),  # Hangul syllables
            (0xD7B0, 0xD7FF),  # Hangul Jamo extended-B
            (0xFFA0, 0xFFDC),  # Halfwidth Jamo
        ),
    ),
    (
        HAN_TC,
        (
            (0x3100, 0x312F),  # Bopomofo, only used for Traditional Chinese
            (0x31A0, 0x31BF),  # Bopomofo extended
        ),
    ),
    (
        HAN_SC,
        (
            (0x2E80, 0x2EFF),  # Kangxi radicals supplement
            (0x3400, 0x4DBF),  # CJK extension A
            (0x4E00, 0x9FFF),  # CJK unified ideographs
            (0xF900, 0xFAFF),  # CJK compatibility ideographs
            (0x20000, 0x2A6DF),  # CJK extension B
        ),
    ),
    (
        CYRILLIC,
        ((0x0400, 0x052F), (0x1C80, 0x1C8F), (0x2DE0, 0x2DFF), (0xA640, 0xA69F)),
    ),
    (GREEK, ((0x0370, 0x03FF), (0x1F00, 0x1FFF))),
    (
        ARABIC,
        (
            (0x0600, 0x06FF),
            (0x0750, 0x077F),
            (0x08A0, 0x08FF),
            (0xFB50, 0xFDFF),
            (0xFE70, 0xFEFF),
        ),
    ),
    (HEBREW, ((0x0590, 0x05FF), (0xFB1D, 0xFB4F))),
    (THAI, ((0x0E00, 0x0E7F),)),
    (DEVANAGARI, ((0x0900, 0x097F), (0xA8E0, 0xA8FF))),
    (LATIN, ((0x0041, 0x024F), (0x1E00, 0x1EFF), (0x2C60, 0x2C7F), (0xA720, 0xA7FF))),
)

# Characters that are simplified-only or traditional-only. Han codepoints are
# unified, so this is the only cheap signal for picking between a Simplified and
# a Traditional font when the text carries no kana, hangul or bopomofo.
_SIMPLIFIED_MARKERS = frozenset(
    "错风汉语国见学会这个时说们后来对开关话门东车马鸟长头买卖过还进远运"
    "该证识义习书难题应当种样点问间电业务体万与专丛丝丢两严丧丰临为岁爱儿华"
)
_TRADITIONAL_MARKERS = frozenset(
    "錯風漢語國見學會這個時說們後來對開關話門東車馬鳥長頭買賣過還進遠運"
    "該證識義習書難題應當種樣點問間電業務體萬與專叢絲丟兩嚴喪豐臨為歲愛兒華"
)

# Codepoints we never let drive font selection: whitespace, ASCII punctuation,
# digits and CJK punctuation are present in nearly every font and would
# otherwise fragment runs or inflate a candidate's coverage score.
_NEUTRAL_RANGES: Tuple[Tuple[int, int], ...] = (
    (0x0000, 0x0040),
    (0x005B, 0x0060),
    (0x007B, 0x00BF),
    (0x2000, 0x206F),
    (0x3000, 0x303F),
    (0xFE30, 0xFE4F),
    (0xFF00, 0xFF20),
)


class _Candidate(NamedTuple):
    """A font file to try, plus an optional family-name hint for collections."""

    filename: str
    face_name: Optional[str] = None


# Per-platform candidate tables, best first. Entries that do not exist on the
# running machine are dropped silently when the table is materialised.
_WINDOWS_FONTS: Dict[str, Tuple[_Candidate, ...]] = {
    LATIN: (
        _Candidate("segoeui.ttf"),
        _Candidate("arial.ttf"),
        _Candidate("tahoma.ttf"),
        _Candidate("calibri.ttf"),
        _Candidate("times.ttf"),
        _Candidate("verdana.ttf"),
    ),
    CYRILLIC: (
        _Candidate("segoeui.ttf"),
        _Candidate("arial.ttf"),
        _Candidate("tahoma.ttf"),
        _Candidate("times.ttf"),
        _Candidate("calibri.ttf"),
    ),
    GREEK: (
        _Candidate("segoeui.ttf"),
        _Candidate("arial.ttf"),
        _Candidate("tahoma.ttf"),
        _Candidate("times.ttf"),
    ),
    HAN_SC: (
        _Candidate("msyh.ttc", "Microsoft YaHei"),
        _Candidate("simsun.ttc", "SimSun"),
        _Candidate("simhei.ttf"),
        _Candidate("msyhl.ttc", "Microsoft YaHei Light"),
        _Candidate("Deng.ttf"),
    ),
    HAN_TC: (
        _Candidate("msjh.ttc", "Microsoft JhengHei"),
        _Candidate("mingliu.ttc", "MingLiU"),
        _Candidate("kaiu.ttf"),
        _Candidate("msyh.ttc", "Microsoft YaHei"),
    ),
    JAPANESE: (
        _Candidate("YuGothR.ttc", "Yu Gothic"),
        _Candidate("YuGothM.ttc", "Yu Gothic"),
        _Candidate("meiryo.ttc", "Meiryo"),
        _Candidate("msgothic.ttc", "MS Gothic"),
        _Candidate("msmincho.ttc", "MS Mincho"),
    ),
    KOREAN: (
        _Candidate("malgun.ttf"),
        _Candidate("malgunsl.ttf"),
        _Candidate("batang.ttc", "Batang"),
        _Candidate("gulim.ttc", "Gulim"),
    ),
    ARABIC: (
        _Candidate("segoeui.ttf"),
        _Candidate("arial.ttf"),
        _Candidate("tahoma.ttf"),
        _Candidate("DUBAI-REGULAR.TTF"),
        _Candidate("trado.ttf"),
        _Candidate("majalla.ttf"),
        _Candidate("andlso.ttf"),
    ),
    HEBREW: (
        _Candidate("segoeui.ttf"),
        _Candidate("arial.ttf"),
        _Candidate("tahoma.ttf"),
        _Candidate("david.ttf"),
        _Candidate("frank.ttf"),
        _Candidate("gisha.ttf"),
        _Candidate("times.ttf"),
    ),
    THAI: (
        _Candidate("LeelawUI.ttf"),
        _Candidate("tahoma.ttf"),
        _Candidate("micross.ttf"),
        _Candidate("upcel.ttf"),
        _Candidate("angsa.ttf"),
    ),
    DEVANAGARI: (
        _Candidate("Nirmala.ttc", "Nirmala UI"),
        _Candidate("mangal.ttf"),
        _Candidate("aparaj.ttf"),
        _Candidate("kokila.ttf"),
        _Candidate("utsaah.ttf"),
    ),
}

_MACOS_FONTS: Dict[str, Tuple[_Candidate, ...]] = {
    LATIN: (
        _Candidate("SFNS.ttf"),
        _Candidate("Helvetica.ttc", "Helvetica"),
        _Candidate("Arial.ttf"),
        _Candidate("HelveticaNeue.ttc", "Helvetica Neue"),
        _Candidate("Geneva.ttf"),
    ),
    CYRILLIC: (
        _Candidate("SFNS.ttf"),
        _Candidate("Helvetica.ttc", "Helvetica"),
        _Candidate("Arial.ttf"),
        _Candidate("Arial Unicode.ttf"),
    ),
    GREEK: (
        _Candidate("SFNS.ttf"),
        _Candidate("Helvetica.ttc", "Helvetica"),
        _Candidate("Arial.ttf"),
        _Candidate("Arial Unicode.ttf"),
    ),
    HAN_SC: (
        _Candidate("PingFang.ttc", "PingFang SC"),
        _Candidate("Hiragino Sans GB.ttc", "Hiragino Sans GB"),
        _Candidate("STHeiti Light.ttc", "Heiti SC"),
        _Candidate("Songti.ttc", "Songti SC"),
        _Candidate("Arial Unicode.ttf"),
    ),
    HAN_TC: (
        _Candidate("PingFang.ttc", "PingFang TC"),
        _Candidate("STHeiti Light.ttc", "Heiti TC"),
        _Candidate("Songti.ttc", "Songti TC"),
        _Candidate("Apple LiGothic Medium.ttf"),
        _Candidate("Arial Unicode.ttf"),
    ),
    JAPANESE: (
        _Candidate("ヒラギノ角ゴシック W4.ttc", "Hiragino Sans"),
        _Candidate("Hiragino Sans GB.ttc", "Hiragino Sans GB"),
        _Candidate("ヒラギノ丸ゴ ProN W4.ttc"),
        _Candidate("Osaka.ttf"),
        _Candidate("Arial Unicode.ttf"),
    ),
    KOREAN: (
        _Candidate("AppleSDGothicNeo.ttc", "Apple SD Gothic Neo"),
        _Candidate("AppleGothic.ttf"),
        _Candidate("NanumGothic.ttc", "NanumGothic"),
        _Candidate("Arial Unicode.ttf"),
    ),
    ARABIC: (
        _Candidate("GeezaPro.ttc", "Geeza Pro"),
        _Candidate("Baghdad.ttc"),
        _Candidate("Al Bayan.ttc"),
        _Candidate("Arial Unicode.ttf"),
    ),
    HEBREW: (
        _Candidate("ArialHB.ttc", "Arial Hebrew"),
        _Candidate("Corsiva.ttc"),
        _Candidate("Arial Unicode.ttf"),
    ),
    THAI: (
        _Candidate("Thonburi.ttc", "Thonburi"),
        _Candidate("Ayuthaya.ttf"),
        _Candidate("Arial Unicode.ttf"),
    ),
    DEVANAGARI: (
        _Candidate("DevanagariSangamMN.ttc", "Devanagari Sangam MN"),
        _Candidate("Kohinoor.ttc", "Kohinoor Devanagari"),
        _Candidate("ITFDevanagari.ttc"),
        _Candidate("Arial Unicode.ttf"),
    ),
}

# Linux distributions do not agree on paths, so these absolute entries are only
# a backstop; _fc_match is tried first whenever fontconfig is installed.
_LINUX_FONTS: Dict[str, Tuple[_Candidate, ...]] = {
    LATIN: (
        _Candidate("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        _Candidate("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        _Candidate("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"),
        _Candidate("/usr/share/fonts/TTF/DejaVuSans.ttf"),
    ),
    CYRILLIC: (
        _Candidate("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        _Candidate("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        _Candidate("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"),
    ),
    GREEK: (
        _Candidate("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        _Candidate("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        _Candidate("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"),
    ),
    HAN_SC: (
        _Candidate(
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "Noto Sans CJK SC"
        ),
        _Candidate("/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf"),
        _Candidate("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
        _Candidate("/usr/share/fonts/truetype/arphic/uming.ttc"),
    ),
    HAN_TC: (
        _Candidate(
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "Noto Sans CJK TC"
        ),
        _Candidate("/usr/share/fonts/opentype/noto/NotoSansCJKtc-Regular.otf"),
        _Candidate("/usr/share/fonts/truetype/arphic/uming.ttc"),
        _Candidate("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
    ),
    JAPANESE: (
        _Candidate(
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "Noto Sans CJK JP"
        ),
        _Candidate("/usr/share/fonts/opentype/noto/NotoSansCJKjp-Regular.otf"),
        _Candidate("/usr/share/fonts/truetype/fonts-japanese-gothic.ttf"),
    ),
    KOREAN: (
        _Candidate(
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "Noto Sans CJK KR"
        ),
        _Candidate("/usr/share/fonts/opentype/noto/NotoSansCJKkr-Regular.otf"),
        _Candidate("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
    ),
    ARABIC: (
        _Candidate("/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf"),
        _Candidate("/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf"),
        _Candidate("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        _Candidate("/usr/share/fonts/truetype/kacst/KacstOne.ttf"),
    ),
    HEBREW: (
        _Candidate("/usr/share/fonts/truetype/noto/NotoSansHebrew-Regular.ttf"),
        _Candidate("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        _Candidate("/usr/share/fonts/truetype/culmus/DejaVuSansHebrew.ttf"),
    ),
    THAI: (
        _Candidate("/usr/share/fonts/truetype/noto/NotoSansThai-Regular.ttf"),
        _Candidate("/usr/share/fonts/truetype/tlwg/Garuda.ttf"),
        _Candidate("/usr/share/fonts/truetype/tlwg/Loma.ttf"),
    ),
    DEVANAGARI: (
        _Candidate("/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf"),
        _Candidate("/usr/share/fonts/truetype/lohit-devanagari/Lohit-Devanagari.ttf"),
        _Candidate("/usr/share/fonts/truetype/ttf-indic-fonts-core/lohit_hi.ttf"),
    ),
}

# fontconfig language tags, used to ask the system which font it would pick.
_FC_LANGS: Dict[str, str] = {
    LATIN: "en",
    CYRILLIC: "ru",
    GREEK: "el",
    HAN_SC: "zh-cn",
    HAN_TC: "zh-tw",
    JAPANESE: "ja",
    KOREAN: "ko",
    ARABIC: "ar",
    HEBREW: "he",
    THAI: "th",
    DEVANAGARI: "hi",
}

_SUPPORTED_SUFFIXES = (".ttf", ".ttc", ".otf", ".otc")

# Module-level caches. Reading a cmap costs ~100 ms, and the renderer calls this
# once per line, so nothing here may be recomputed per call.
_coverage_cache: Dict[FontFace, FrozenSet[int]] = {}
_faces_cache: Dict[str, Tuple[FontFace, ...]] = {}
_face_names_cache: Dict[str, Tuple[Optional[str], ...]] = {}
_script_candidates_cache: Dict[str, Tuple[FontFace, ...]] = {}
_resolve_cache: Dict[Tuple[FrozenSet[int], Optional[str], str], Optional[FontFace]] = {}
_fc_match_cache: Dict[str, Optional[str]] = {}
_font_dirs_cache: Optional[Tuple[str, ...]] = None

# Bound on _resolve_cache so a long-running service cannot grow it without end.
_RESOLVE_CACHE_LIMIT = 4096


def clear_font_caches() -> None:
    """Drop every cached cmap and candidate list. Mainly for tests."""
    global _font_dirs_cache
    _coverage_cache.clear()
    _faces_cache.clear()
    _face_names_cache.clear()
    _script_candidates_cache.clear()
    _resolve_cache.clear()
    _fc_match_cache.clear()
    _font_dirs_cache = None


def _font_dirs() -> Tuple[str, ...]:
    """Directories that hold system fonts on this platform, existing ones only."""
    global _font_dirs_cache
    if _font_dirs_cache is not None:
        return _font_dirs_cache

    if sys.platform.startswith("win"):
        system_root = os.environ.get("SystemRoot", "C:\\Windows")
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        raw = [os.path.join(system_root, "Fonts")]
        if local_app_data:
            raw.append(os.path.join(local_app_data, "Microsoft", "Windows", "Fonts"))
    elif sys.platform == "darwin":
        raw = [
            "/System/Library/Fonts",
            "/System/Library/Fonts/Supplemental",
            "/Library/Fonts",
            os.path.expanduser("~/Library/Fonts"),
        ]
    else:
        raw = [
            "/usr/share/fonts",
            "/usr/local/share/fonts",
            os.path.expanduser("~/.local/share/fonts"),
            os.path.expanduser("~/.fonts"),
        ]

    _font_dirs_cache = tuple(d for d in raw if os.path.isdir(d))
    return _font_dirs_cache


def _platform_table() -> Dict[str, Tuple[_Candidate, ...]]:
    if sys.platform.startswith("win"):
        return _WINDOWS_FONTS
    if sys.platform == "darwin":
        return _MACOS_FONTS
    return _LINUX_FONTS


def _locate(filename: str) -> Optional[str]:
    """Resolve a table entry to an existing file, absolute paths passed through."""
    if os.path.isabs(filename):
        return filename if os.path.isfile(filename) else None
    for directory in _font_dirs():
        candidate = os.path.join(directory, filename)
        if os.path.isfile(candidate):
            return candidate
    return None


def _fc_match(script: str) -> Optional[str]:
    """Ask fontconfig which file it would use for a script. Linux/BSD only."""
    if script in _fc_match_cache:
        return _fc_match_cache[script]

    result: Optional[str] = None
    lang = _FC_LANGS.get(script)
    if lang:
        try:
            completed = subprocess.run(
                ["fc-match", "-f", "%{file}", f":lang={lang}"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            if completed.returncode == 0:
                path = completed.stdout.strip()
                if path and os.path.isfile(path):
                    result = path
        except (OSError, subprocess.SubprocessError) as e:
            logger.debug(f"fc-match unavailable for lang '{lang}': {e}")

    _fc_match_cache[script] = result
    return result


def _face_count(path: str) -> int:
    """Number of faces in a collection; 1 for a plain .ttf/.otf."""
    if not FONTTOOLS_AVAILABLE or not path.lower().endswith((".ttc", ".otc")):
        return 1
    try:
        font = TTFont(path, fontNumber=0, lazy=True)
        try:
            return int(getattr(font.reader, "numFonts", 1) or 1)
        finally:
            font.close()
    except Exception as e:
        logger.debug(f"Could not read face count of '{path}': {e}")
        return 1


def _face_names(path: str) -> Tuple[Optional[str], ...]:
    """Family name of every face in a file, indexed by face number."""
    if path in _face_names_cache:
        return _face_names_cache[path]

    names: List[Optional[str]] = []
    if FONTTOOLS_AVAILABLE:
        for index in range(_face_count(path)):
            try:
                font = TTFont(path, fontNumber=index, lazy=True)
                try:
                    names.append(font["name"].getDebugName(1))
                finally:
                    font.close()
            except Exception as e:
                logger.debug(f"Could not read name of '{path}' face {index}: {e}")
                names.append(None)
    if not names:
        names = [None]

    _face_names_cache[path] = tuple(names)
    return _face_names_cache[path]


def _faces(path: str, face_name: Optional[str] = None) -> Tuple[FontFace, ...]:
    """Faces of a file, ordered so the hinted family (if any) comes first.

    PingFang.ttc and NotoSansCJK-Regular.ttc bundle the SC, TC, JP and KR
    designs in one file with identical cmaps, so the regional face can only be
    picked by name, never by coverage.
    """
    cache_key = f"{path}\x00{face_name or ''}"
    if cache_key in _faces_cache:
        return _faces_cache[cache_key]

    count = _face_count(path)
    ordered = [FontFace(path, index) for index in range(count)]
    if face_name and count > 1:
        names = _face_names(path)
        wanted = face_name.casefold()
        ordered.sort(
            key=lambda face: (
                (
                    0
                    if face.index < len(names)
                    and names[face.index]
                    and names[face.index].casefold().startswith(wanted)
                    else 1
                ),
                face.index,
            )
        )

    _faces_cache[cache_key] = tuple(ordered)
    return _faces_cache[cache_key]


def _coverage(face: FontFace) -> Optional[FrozenSet[int]]:
    """Codepoints a face maps to a glyph, or None when it cannot be determined."""
    if not FONTTOOLS_AVAILABLE:
        return None
    if face in _coverage_cache:
        return _coverage_cache[face]

    chars: FrozenSet[int] = frozenset()
    try:
        font = TTFont(face.path, fontNumber=face.index, lazy=True)
        try:
            chars = frozenset(font["cmap"].getBestCmap().keys())
        finally:
            font.close()
    except Exception as e:
        logger.debug(f"Could not read cmap of '{face.path}' face {face.index}: {e}")

    _coverage_cache[face] = chars
    return chars


def _is_neutral(codepoint: int) -> bool:
    for low, high in _NEUTRAL_RANGES:
        if low <= codepoint <= high:
            return True
    return False


def _script_of(codepoint: int) -> Optional[str]:
    for script, ranges in _SCRIPT_RANGES:
        for low, high in ranges:
            if low <= codepoint <= high:
                return script
    return None


def _han_variant(text: str) -> str:
    """Decide which regional Han font the unified ideographs in a string want.

    Kana is decisive, and hangul is decisive as long as it is not a minority in
    a line that is mostly Han (Korean uses hanja, but a polyglot line that
    happens to contain a Korean word does not make its Chinese Korean).
    Otherwise we look for simplified-only or traditional-only characters and
    fall back to Simplified, which is what Lens produces for ``zh``.
    """
    has_kana = False
    hangul = 0
    han = 0
    simplified = 0
    traditional = 0
    for char in text:
        script = _script_of(ord(char))
        if script == JAPANESE:
            has_kana = True
        elif script == KOREAN:
            hangul += 1
        elif script == HAN_TC:
            traditional += 4  # Bopomofo is a strong Traditional signal.
        elif script == HAN_SC:
            han += 1
        if char in _SIMPLIFIED_MARKERS:
            simplified += 1
        elif char in _TRADITIONAL_MARKERS:
            traditional += 1

    if has_kana:
        return JAPANESE
    if hangul and hangul >= han:
        return KOREAN
    if traditional > simplified:
        return HAN_TC
    return HAN_SC


def _scripts_in(text: str) -> Tuple[str, ...]:
    """Scripts present in `text`, most specific first, Han already specialised."""
    counts: Dict[str, int] = {}
    for char in text:
        codepoint = ord(char)
        if _is_neutral(codepoint):
            continue
        script = _script_of(codepoint)
        if script is None:
            continue
        counts[script] = counts.get(script, 0) + 1

    if not counts:
        return ()

    # Only the unified-ideograph bucket is ambiguous; kana, hangul and bopomofo
    # already name their region and stay as separate entries so that a line
    # mixing them still pulls in each one's font.
    han = counts.pop(HAN_SC, 0)
    if han:
        variant = _han_variant(text)
        counts[variant] = counts.get(variant, 0) + han

    return tuple(
        sorted(
            counts,
            key=lambda script: (
                _SCRIPT_SPECIFICITY.get(script, 0),
                -counts[script],
                script,
            ),
        )
    )


def _char_scripts(text: str) -> Tuple[Optional[str], ...]:
    """Script of every character, with Han resolved against the whole line.

    Per-character classification has to see the full line: a lone kanji carries
    no hint of its own about which regional font it belongs to.
    """
    variant: Optional[str] = None
    scripts: List[Optional[str]] = []
    for char in text:
        codepoint = ord(char)
        if _is_neutral(codepoint) or char.isspace():
            scripts.append(None)
            continue
        script = _script_of(codepoint)
        if script == HAN_SC:
            if variant is None:
                variant = _han_variant(text)
            script = variant
        scripts.append(script)
    return tuple(scripts)


def _candidates_for_script(script: str) -> Tuple[FontFace, ...]:
    if script in _script_candidates_cache:
        return _script_candidates_cache[script]

    faces: List[FontFace] = []
    seen = set()

    def add(path: str, face_name: Optional[str]) -> None:
        # Only the leading face: _faces puts the hinted regional design first,
        # and the remaining faces of a collection are weights of the same
        # design with the same cmap, so reading them would just cost time.
        for face in _faces(path, face_name)[:1]:
            if face not in seen:
                seen.add(face)
                faces.append(face)

    if not sys.platform.startswith("win") and sys.platform != "darwin":
        matched = _fc_match(script)
        if matched and matched.lower().endswith(_SUPPORTED_SUFFIXES):
            add(matched, None)

    for candidate in _platform_table().get(script, ()):
        path = _locate(candidate.filename)
        if path and path.lower().endswith(_SUPPORTED_SUFFIXES):
            add(path, candidate.face_name)

    if not faces:
        logger.debug(f"No font candidates found for script '{script}' on this system.")

    _script_candidates_cache[script] = tuple(faces)
    return _script_candidates_cache[script]


def _candidates_for_text(text: str) -> Tuple[FontFace, ...]:
    """Candidate faces ordered by the scripts the text actually uses."""
    scripts = _scripts_in(text)
    ordered_scripts = list(scripts)

    # A regional CJK font is not a superset of the others: Malgun Gothic carries
    # most Han but not the GB-only simplified forms, so a line mixing Hangul and
    # Simplified Chinese needs the other regional designs as a second tier
    # rather than a hole where the characters it lacks should be.
    if any(script in _CJK_SCRIPTS for script in scripts):
        for script in _CJK_SCRIPTS:
            if script not in ordered_scripts:
                ordered_scripts.append(script)
    ordered_scripts.append(LATIN)

    ordered: List[FontFace] = []
    seen = set()
    for script in ordered_scripts:
        for face in _candidates_for_script(script):
            if face not in seen:
                seen.add(face)
                ordered.append(face)
    return tuple(ordered)


def _significant(text: str) -> FrozenSet[int]:
    """Codepoints that font selection should actually care about."""
    return frozenset(
        ord(char) for char in text if not _is_neutral(ord(char)) and not char.isspace()
    )


def _face_covers(
    face: Optional[FontFace],
    codepoints: Iterable[int],
    scripts: Sequence[str] = (),
) -> bool:
    if face is None:
        return False
    coverage = _coverage(face)
    if coverage is None:
        # Without fontTools the file cannot be inspected, so the curated tables
        # answer instead and `scripts` is what the question reduces to.
        return _static_supports(face, scripts)
    return all(codepoint in coverage for codepoint in codepoints)


def _static_supports(face: FontFace, scripts: Sequence[str]) -> bool:
    """Curated-table answer for "does this file handle these scripts?".

    Used only when fontTools is missing. Anything not listed in the tables is
    assumed to be a Latin-only font, which is the safe assumption for a random
    file a user passed via --font.
    """
    basename = os.path.basename(face.path).casefold()
    table = _platform_table()
    for script in scripts:
        listed = any(
            os.path.basename(candidate.filename).casefold() == basename
            for candidate in table.get(script, ())
        )
        if not listed:
            return False
    return True


def _preferred_face(
    preferred_path: Optional[str], codepoints: FrozenSet[int]
) -> Optional[FontFace]:
    """Best face inside a user-supplied file, or None if it covers nothing."""
    if not preferred_path or not os.path.isfile(preferred_path):
        return None

    faces = _faces(preferred_path)
    if not FONTTOOLS_AVAILABLE:
        return faces[0] if faces else None

    best: Optional[FontFace] = None
    best_score = -1
    for face in faces:
        coverage = _coverage(face) or frozenset()
        score = sum(1 for codepoint in codepoints if codepoint in coverage)
        if score > best_score:
            best, best_score = face, score
        if best_score == len(codepoints):
            break
    return best


def _resolve_face(text: str, preferred_path: Optional[str]) -> Optional[FontFace]:
    codepoints = _significant(text)
    scripts = _scripts_in(text)
    cache_key = (codepoints, preferred_path, "|".join(scripts))
    if cache_key in _resolve_cache:
        return _resolve_cache[cache_key]

    preferred = _preferred_face(preferred_path, codepoints)

    if not codepoints:
        result = preferred or (_candidates_for_script(LATIN) or (None,))[0]
        _store_resolution(cache_key, result)
        return result

    if not FONTTOOLS_AVAILABLE:
        # Curated-table mode: trust the script tables, and keep --font only when
        # the tables say it handles every script in the line.
        if preferred is not None and _static_supports(preferred, scripts):
            _store_resolution(cache_key, preferred)
            return preferred
        candidates = _candidates_for_text(text)
        result = candidates[0] if candidates else preferred
        _store_resolution(cache_key, result)
        return result

    # A user who passed --font must not be overridden while it still works.
    if preferred is not None and _face_covers(preferred, codepoints, scripts):
        _store_resolution(cache_key, preferred)
        return preferred

    best: Optional[FontFace] = None
    best_score = 0
    for face in _candidates_for_text(text):
        coverage = _coverage(face) or frozenset()
        score = sum(1 for codepoint in codepoints if codepoint in coverage)
        if score > best_score:
            best, best_score = face, score
        if best_score == len(codepoints):
            break

    if best is None:
        best = preferred
    elif preferred is not None:
        preferred_coverage = _coverage(preferred) or frozenset()
        preferred_score = sum(1 for cp in codepoints if cp in preferred_coverage)
        # Ties go to the user's font; it only loses when it covers strictly less.
        if preferred_score >= best_score:
            best = preferred

    _store_resolution(cache_key, best)
    return best


def _store_resolution(
    key: Tuple[FrozenSet[int], Optional[str], str], face: Optional[FontFace]
) -> None:
    if len(_resolve_cache) >= _RESOLVE_CACHE_LIMIT:
        _resolve_cache.clear()
    _resolve_cache[key] = face


def _merge_runs(
    runs: Sequence[Tuple[str, Optional[FontFace]]],
) -> List[Tuple[str, Optional[FontFace]]]:
    merged: List[Tuple[str, Optional[FontFace]]] = []
    for chunk, face in runs:
        if merged and merged[-1][1] == face:
            merged[-1] = (merged[-1][0] + chunk, face)
        else:
            merged.append((chunk, face))
    return merged


def font_supports_text(font_path: str, text: str, index: int = 0) -> bool:
    """Whether `font_path` maps every meaningful character of `text`.

    Without fontTools the file cannot be inspected, so the answer falls back to
    whether the curated tables list this font for the scripts `text` uses.
    """
    if not font_path or not os.path.isfile(font_path):
        return False
    return _face_covers(
        FontFace(font_path, index), _significant(text), _scripts_in(text)
    )


def resolve_font_face_for_text(
    text: str, preferred_path: Optional[str] = None
) -> Optional[FontFace]:
    """Index-aware form of :func:`resolve_font_for_text`.

    Use this when the chosen file may be a collection whose faces differ, e.g.
    macOS ``PingFang.ttc`` (PingFang SC / TC / HK) or Linux
    ``NotoSansCJK-Regular.ttc`` (JP / KR / SC / TC / HK)::

        face = resolve_font_face_for_text(line)
        font = ImageFont.truetype(face.path, size, index=face.index)
    """
    if not text:
        return _resolve_face("", preferred_path)
    return _resolve_face(text, preferred_path)


def resolve_font_for_text(
    text: str, preferred_path: Optional[str] = None
) -> Optional[str]:
    """Return a font path that covers the most characters in `text`.

    `preferred_path` (the user's ``--font``) wins whenever it covers the text,
    and is never replaced by a font that covers no more than it does. Returns
    None only when no usable font file was found on this system.

    The returned path is meant for ``ImageFont.truetype(path, size)``, which
    loads face 0 of a collection. Face 0 is the right face for every collection
    in the built-in tables on Windows, but on macOS and Linux the regional CJK
    designs live in one .ttc; callers that must be exact should use
    :func:`resolve_font_face_for_text` and pass ``index=face.index``.
    """
    face = resolve_font_face_for_text(text, preferred_path)
    return face.path if face is not None else None


def split_by_coverage_faces(
    text: str, preferred_path: Optional[str] = None
) -> List[Tuple[str, Optional[FontFace]]]:
    """Index-aware form of :func:`split_by_coverage`.

    Each run is ``(substring, FontFace | None)``; None means no candidate font
    covers that substring, and the caller should render it with whatever
    fallback it uses for unknown glyphs.
    """
    if not text:
        return []

    significant = _significant(text)
    scripts = _scripts_in(text)
    whole = _resolve_face(text, preferred_path)
    if _face_covers(whole, significant, scripts):
        return [(text, whole)]

    candidates: List[FontFace] = []
    if whole is not None:
        candidates.append(whole)
    preferred = _preferred_face(preferred_path, significant)
    if preferred is not None and preferred not in candidates:
        candidates.insert(0, preferred)
    for face in _candidates_for_text(text):
        if face not in candidates:
            candidates.append(face)

    char_scripts = _char_scripts(text)

    def takes(face: FontFace, position: int) -> bool:
        script = char_scripts[position]
        if script is None:
            return True  # Neutral characters never force a font switch.
        coverage = _coverage(face)
        if coverage is None:
            return _static_supports(face, (script,))
        return ord(text[position]) in coverage

    runs: List[Tuple[str, Optional[FontFace]]] = []
    position = 0
    length = len(text)
    while position < length:
        if char_scripts[position] is None:
            # Spaces and punctuation attach to the preceding run instead of
            # splitting a sentence in the middle.
            runs.append((text[position], runs[-1][1] if runs else whole))
            position += 1
            continue

        chosen: Optional[FontFace] = None
        reach = position
        for face in candidates:
            if not takes(face, position):
                continue
            end = position
            while end < length and takes(face, end):
                end += 1
            if end > reach:
                chosen, reach = face, end

        if chosen is None:
            runs.append((text[position], None))
            position += 1
        else:
            runs.append((text[position:reach], chosen))
            position = reach

    return _merge_runs(runs)


def split_by_coverage(
    text: str, preferred_path: Optional[str] = None
) -> List[Tuple[str, Optional[str]]]:
    """Split text into runs of (substring, font_path) so each run renders with a
    font that covers it.

    Concatenating the substrings reproduces `text` exactly. A run's font path is
    None when nothing on this system covers it. When one font covers everything
    a single run is returned, which is the common case, so callers can keep
    their fast path::

        runs = split_by_coverage(line, user_font)
        for chunk, path in runs:
            font = ImageFont.truetype(path, size) if path else ImageFont.load_default()
            draw.text((x, y), chunk, font=font, fill=colour)
            x += draw.textlength(chunk, font=font)

    As with :func:`resolve_font_for_text` the path assumes face 0 of a
    collection; use :func:`split_by_coverage_faces` to get the face index too.
    """
    return [
        (chunk, face.path if face is not None else None)
        for chunk, face in split_by_coverage_faces(text, preferred_path)
    ]
