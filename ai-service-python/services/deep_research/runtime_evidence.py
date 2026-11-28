"""Navigation for explicit runtime rates and their measured trade-offs."""
import re
from decimal import Decimal


_RUNTIME = re.compile(r'速度|测速|加速|提速|吞吐|\b(?:speed|speedup|runtime|accelerat\w*|throughput|latency)\b', re.I)
_TRADEOFF = re.compile(r'取舍|牺牲|精度|准确率|\b(?:trade[- ]?offs?|accuracy|precision|fidelity)\b', re.I)
_RATE = re.compile(r'(?<![\d.])(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>Hz|FPS)'
                   r'(?=\b|(?:with|at|on|for)\b)', re.I)
_FASTER = re.compile(r'\b(?:faster|accelerated|optimized)\s+(?:version|variant|model)\b|'
                     r'\b(?:larger|coarser|smaller)\b.{0,110}\bfaster\b|加速版', re.I | re.S)
_CHANGE = re.compile(r'\b(?:larger|coarser|smaller|lower|higher|reducing|increasing|reduced)\s+'
                     r'(?:the\s+)?(?:bins?|pillars?|grids?|resolution|batch|samples?|tokens?|width|depth|precision)\b'
                     r'.{0,150}\b(?:faster|speed\w*|runtime|latency)\b|'
                     r'(?:增大|减小|降低|减少).{0,50}(?:提速|耗时)', re.I | re.S)
_LOSS = re.compile(r'\b(?:decrease|drop|loss|reduction)\s+(?:in|of)\s+'
                   r'(?:detection\s+)?(?:performance|accuracy|precision|fidelity)\b|精度(?:下降|损失)', re.I)
_LOSS_DETAIL = re.compile(r'\b(?:mainly|primarily)\s+(?:due to|in|on|from)\b|'
                          r'\b(?:while|whereas)\b.{0,70}\b(?:stable|unchanged)\b|主要(?:来自|发生|影响)', re.I | re.S)


def rate_requested(query):
    return bool(_RUNTIME.search(query))


def tradeoff_requested(query):
    return rate_requested(query) and bool(_TRADEOFF.search(query))


def rate_values(text):
    """Find explicit per-second rates in the quote, excluding bare cells."""
    return {(Decimal(m['value']), m['unit'].casefold()) for m in _RATE.finditer(text)}


def faster_variant(text):
    return bool(_FASTER.search(text))


def tradeoff_roles(text):
    text = re.sub(r'(?<=[A-Za-z])-\s*\n\s*(?=[A-Za-z])', '', text)
    return bool(_CHANGE.search(text)), bool(_LOSS.search(text) and _LOSS_DETAIL.search(text))


def include_pdf_tradeoff(rows, passages, limit):
    """Retain one exact slice connecting runtime and a reported trade-off."""
    if limit < 2:
        return rows
    matched = [row for row in passages if row.get('retrievalMode') == 'pdf_lexical_fallback'
               and rate_values(row['text']) and any(tradeoff_roles(row['text']))]
    if not matched:
        return rows
    lead = max(matched, key=lambda row: (sum(tradeoff_roles(row['text'])), faster_variant(row['text'])))
    return [lead, *(row for row in rows if row['sourceId'] != lead['sourceId'])][:limit]
