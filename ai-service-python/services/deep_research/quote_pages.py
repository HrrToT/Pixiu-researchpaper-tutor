"""Resolve the true physical page of a quote against parsed PDF pages.

Standard library only.  Matching is exact after deterministic normalization
(NFKC, soft-hyphen removal, PDF wrap-hyphen rejoining, whitespace collapse).
No fuzzy matching, network access, or PDF parsing is performed.
"""

from __future__ import annotations

import re
import unicodedata

__all__ = ["resolve_quote_location"]

_MIN_QUOTE_CHARS = 20

# Invisible/formatting characters that PDF extraction sprinkles into text.
_SOFT_HYPHENS_RE = re.compile(r"\u00ad")
# Hyphen ending a wrapped line between letters: rejoin the word.
_WRAP_HYPHEN_RE = re.compile(r"(?<=[A-Za-z])-\s*\n\s*(?=[A-Za-z])")
_WHITESPACE_RE = re.compile(r"\s+")

# Keys copied from stale location metadata that must not survive re-resolution.
_POSITIONAL_KEYS = ("page", "pageIndex", "page_index", "pageStart", "pageEnd")
_GEOMETRY_KEYS = (
    "bbox", "bboxes", "coords", "coordinates",
    "offset", "offsets", "startOffset", "endOffset",
    "charStart", "charEnd", "span", "spans",
    "x", "y", "x0", "y0", "x1", "y1", "width", "height",
)


def _normalize(text):
    """Deterministic normalization shared by quotes and page texts."""
    if not isinstance(text, str):
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = _SOFT_HYPHENS_RE.sub("", text)
    text = _WRAP_HYPHEN_RE.sub("", text)
    # Different PDF extractors place spaces around styled inline punctuation.
    # Keep punctuation and word boundaries; never join number ranges or tokens.
    text = re.sub(r"(?<=[A-Za-z])[^\S\n]*-[^\S\n]*(?=[A-Za-z])", "-", text)
    text = re.sub(r"([\(\[])\s+", r"\1", text)
    text = re.sub(r"\s+([\)\],;])", r"\1", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def _normalize_typography(text):
    text = _normalize(text)
    # These forms differ between the index and physical PDF extraction.
    # Preserve ordinary word boundaries, digits and the mathematical minus.
    text = re.sub(r'(?<=[A-Za-z]{2}) [–—] (?=[A-Za-z]{2})', '-', text)
    text = re.sub(r' *• *', ' • ', text)
    text = re.sub(r'\b((?:Fig|Eq|Sec)\.) *(?=\d)', r'\1 ', text, flags=re.I)
    text = re.sub(r'(?<=[αβγσ]) *(?=(?:and|values?|coefficients?)\b)', ' ', text)
    text = re.sub(r'([≥≤]) *(?=\d)', r'\1', text)
    return re.sub(r'(?<=\d) *(?=fps\b)', ' ', text, flags=re.I).strip()


def _valid_page_texts(pages, normalize):
    """Yield (page_number, normalized_text) for well-formed page records."""
    if not isinstance(pages, (list, tuple)):
        return
    for record in pages:
        if not isinstance(record, dict):
            continue
        page = record.get("page")
        # bool is a subclass of int; reject it explicitly.
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            continue
        text = record.get("text")
        if not isinstance(text, str):
            continue
        yield page, normalize(text)


def resolve_quote_location(quote, pages, location, *, typography=False):
    """Return a new location dict with the physically verified page.

    ``pages`` are trusted physically parsed PDF pages: dicts with a positive
    1-based ``page`` integer and a ``text`` string.  ``location`` is old
    indexed metadata whose claimed page may be wrong; it is never mutated and
    is never used to break ties.
    """
    result = dict(location) if isinstance(location, dict) else {}

    for key in _POSITIONAL_KEYS + _GEOMETRY_KEYS + ("pageCandidates",):
        result.pop(key, None)

    normalize = _normalize_typography if typography else _normalize
    norm_quote = normalize(quote) if isinstance(quote, str) else ""

    matched = set()
    if len(norm_quote) >= _MIN_QUOTE_CHARS:
        for page, text in _valid_page_texts(pages, normalize):
            if norm_quote in text:
                matched.add(page)

    if len(matched) == 1:
        physical_page = next(iter(matched))
        result["page"] = physical_page
        result["pageIndex"] = physical_page - 1
        result["pageResolution"] = "exact"
    elif matched:
        result["pageResolution"] = "ambiguous"
        result["pageCandidates"] = sorted(matched)
    else:
        result["pageResolution"] = "unresolved"

    return result
