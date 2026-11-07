"""Recover an exact original span; no lexical edits or fuzzy evidence matching."""
import re


def original_quote_span(quote, original):
    if not isinstance(quote, str) or not isinstance(original, str) or not quote.strip():
        return None
    if quote in original:
        return quote
    words = quote.split()
    pattern = r'\s+'.join(re.escape(word) for word in words)
    matches = re.finditer(pattern, original)
    first = next(matches, None)
    if first is None:
        # PDF line wrapping may split an alphabetical word as "mini-\nma".
        # Match only this explicit source layout, then return the untouched
        # source span, including its hyphen/newline. Numbers, ordinary hyphens
        # and other spelling changes receive no tolerance.
        pieces = []
        candidate = quote.strip()
        for index, char in enumerate(candidate):
            if char.isspace():
                if not pieces or pieces[-1] != r'\s+':
                    pieces.append(r'\s+')
                continue
            if (index and candidate[index - 1].isascii()
                    and candidate[index - 1].isalpha()
                    and char.isascii() and char.islower()):
                pieces.append(r'(?:-[ \t]*\r?\n[ \t]*)?')
            pieces.append(re.escape(char))
            if (char == '-' and index and candidate[index - 1].isalpha()
                    and index + 1 < len(candidate) and candidate[index + 1].islower()):
                pieces.append(r'(?:[ \t]*\r?\n[ \t]*)?')
        matches = re.finditer(''.join(pieces), original)
        first = next(matches, None)
    if first is None or next(matches, None) is not None:
        return None
    return original[first.start():first.end()]
