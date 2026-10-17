"""Literal device identity checks; matching a name never proves its scope."""
import re

from services.deep_research.prose_checks import claim_prose
from services.deep_research.selection import surrounding_context

DEVICE = re.compile(r'(?<![A-Za-z0-9])(?:[AHV]\d{2,4}|(?:RTX|GTX)\s*(?:A\s*)?\d{3,4}(?:\s*Ti)?)(?![A-Za-z0-9])', re.I)


def unsupported_device_condition(claim, evidence):
    text = ' '.join(claim_prose(claim))
    if not re.search(r'GPU|显卡|硬件|\bhardware\b', text, re.I):
        return False
    identities = {re.sub(r'\s+', '', value).casefold() for value in DEVICE.findall(text)}
    if not identities:
        return False
    # Exactly the cited literal quote/context seen by independent verification.
    # Another claim's citation or model-extracted conditions cannot fill it.
    originals = []
    for row in evidence:
        context = surrounding_context(row)
        originals.append(row.get('quote', ''))
        originals.extend(context.get(key, '') for key in ('before', 'after') if isinstance(context.get(key), str))
    found = {re.sub(r'\s+', '', value).casefold() for value in DEVICE.findall(' '.join(originals))}
    return not identities <= found
