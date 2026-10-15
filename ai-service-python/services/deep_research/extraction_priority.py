"""Prioritize explanatory passages before a bounded extraction batch."""
import re

from services.deep_research.obligation_binding import eligible_obligation_ids
from services.deep_research.selection import balanced_sample

_STOP = {'the', 'and', 'for', 'with', 'from', 'this', 'that', 'what', 'which', 'how',
         'why', 'does', 'are', 'its', 'paper', 'arxiv', 'http', 'https', 'org'}
_CAUSAL = [r'\b(?:gradient|loss|error|objective|reward|input|signal|stimulus)\w*',
           r'\b(?:updat|increas|decreas|optimi|adjust|learn|chang|modif|reduc|regulat)\w*',
           r'\b(?:if|when|case|given|condition)\w*',
           r'\b(?:result|effect|outcome|output|predict|sampl|probabil|concentrat)\w*']


def prioritize_extraction_passages(pending, obligations):
    """Keep every unchanged passage and its permissions; this is not relevance proof.

    Explanations benefit from a complete signal/change/condition/effect chain.
    Identification-only requests keep their order. Paper round-robin prevents
    one rich source from displacing the other selected papers' first passages.
    """
    def requirement(source):
        rows = [obligations[key] for key in eligible_obligation_ids(source, obligations)]
        explain = any(any(c.get('responseType') == 'explanation' for c in row.get('completionCriteria', []))
                      or not row.get('completionCriteria') and re.search(
                          r'\b(?:how|why)\b|如何|为什么|机制|原理|怎样', row.get('question', ''), re.I)
                      for row in rows)
        query = ' '.join(str(row.get(key, '')) for row in rows for key in ('question', 'searchQuery'))
        terms = set(re.findall(r'[a-z]{3,}', query.lower())) - _STOP
        label, separator, _ = str(source.get('title', '')).partition(':')
        if separator and re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*', label.strip()):
            terms -= set(re.findall(r'[a-z]{3,}', label.lower()))
        return bool(explain), terms

    requirements = [requirement(source) for source, _, _ in pending]
    if not any(explain for explain, _ in requirements):
        return list(pending)
    ranked = []
    for index, (item, (explain, terms)) in enumerate(zip(pending, requirements)):
        # Normalize line-wrap hyphens only for ranking; supplied text is untouched.
        text = re.sub(r'(?<=[A-Za-z])-[ \t]*\r?\n[ \t]*(?=[A-Za-z])', '', item[2]).lower()
        causal = sum(bool(re.search(pattern, text)) for pattern in _CAUSAL) if explain else 0
        counts = [text.count(term) for term in terms]
        score = (causal, sum(count > 0 for count in counts), sum(min(count, 3) for count in counts), -index)
        ranked.append((score, item))
    ordered = [item for _, item in sorted(ranked, key=lambda row: row[0], reverse=True)]
    return balanced_sample(ordered, lambda item: item[0]['workId'], len(ordered))
