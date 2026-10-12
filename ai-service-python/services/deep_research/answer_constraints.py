"""User-visible length constraints, separate from model token budgets."""
import json
import re


def normalize_conditions(report):
    for claim in report.get('claims', []):
        if not isinstance(claim, dict):
            continue
        conditions = claim.get('conditions')
        if isinstance(conditions, str):
            claim['conditions'] = {'context': conditions} if conditions.strip() else {}
        elif isinstance(conditions, list) and all(isinstance(value, str) for value in conditions):
            claim['conditions'] = {str(index + 1): value for index, value in enumerate(conditions)}
    return report


def requested_character_limit(question):
    match = re.search(r'(\d{2,5})\s*(?:字|个字符|characters)\s*(?:以内|以下|内|maximum|max)?', question, re.I)
    return min(int(match[1]), 10000) if match else None


def answer_character_count(report):
    count = 0
    for claim in report.get('claims', []):
        if not isinstance(claim, dict) or not isinstance(claim.get('text'), str):
            return float('inf')
        conditions = claim.get('conditions') or {}
        if not isinstance(conditions, dict):
            return float('inf')
        count += len(claim['text']) + sum(len(str(key)) + len(str(value)) + 2 for key, value in conditions.items())
    return count


def compact_answer(report, question, invoke, parse):
    report = normalize_conditions(report)
    limit = requested_character_limit(question)
    if not limit or answer_character_count(report) <= limit:
        return report
    # One bounded rewrite before verification. Every rewritten fact is checked later.
    prompt = f'''Shorten this structured research answer to at most {limit} characters total
across ALL claim text and conditions. Question: {question}
Return at most {2 if limit <= 300 else 4} short claims that directly answer the user's question. You MAY DROP
less important claims and their sections entirely. Keep necessary conditions and remove tangential numbers.
For comparison, preserve a supported conclusion for EACH compared paper plus the comparability
judgment. Do not drop one paper just to keep detailed numbers for another. Keep row/method labels exact.
Use concise Chinese, embedding conditions in text when possible instead of repeating them.
For claims you retain, keep their original claimId, kind and evidenceRefs. Do not add facts,
references or new claims. Do NOT copy the original answer unchanged. Target {max(40, int(limit * .7))}
characters so necessary conditions also fit the strict {limit} character maximum.
Return ONLY JSON with sections and claims.
Answer:\n{json.dumps(report, ensure_ascii=False)}'''
    result = invoke(prompt)
    compact = parse(result.get('content', '') if isinstance(result, dict) else result.content)
    if not isinstance(compact, dict) or not isinstance(compact.get('claims'), list) or not compact['claims']:
        return None
    compact = normalize_conditions(compact)
    original = {c.get('claimId'): c for c in report['claims'] if isinstance(c, dict)}
    for claim in compact['claims']:
        if not isinstance(claim, dict) or claim.get('claimId') not in original:
            return None
        before = original[claim['claimId']]
        if claim.get('kind') != before.get('kind') or claim.get('evidenceRefs') != before.get('evidenceRefs'):
            return None
    return compact if answer_character_count(compact) <= limit else None
