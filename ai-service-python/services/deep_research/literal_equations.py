"""Retain explicitly labelled method equations as unreviewed literal evidence."""
import re
from services.deep_research.method_intent import query_intents


def method_equations(text,questions):
    if not any(intent in {'input','temporal','training','operation'}
               for question in questions for intent in query_intents(question)):
        return []
    for match in re.finditer(r'(?m)^[ \t]*Equation:[^\r\n]+',text):
        span=match.group().strip()
        if len(span)>1200 or '…' in span or '...' in span or not re.search(r'[^=＝]+[=＝]\s*\S',span):
            continue
        if any(span.count(left)!=span.count(right) for left,right in [('(',')'),('[',']'),('{','}')]):
            continue
        # One of the existing three extraction slots, never an extra approval
        # or an interpretation of its operation/variables. Preserve exact text.
        return [span]
    return []
