"""Bind asserted main-result measurements to their own experiment's purpose.

Structural checks reject missing/foreign/conflicting premises. Passing these
checks never establishes scientific support; the independent verdict is required.
"""
import re

_MAIN = re.compile(r'主表|主要结果表|\bmain (?:results? )?table\b', re.I)
_METRIC = re.compile(r'FPS|帧率|速度|PSNR|SSIM|LPIPS|压缩率|存储|内存|\b(?:speed|memory|compression)\b', re.I)
_PREDICATE = re.compile(r'来自|取自|出自|(?:是|为|使用|采用|基于|测得|测量|报告)|\b(?:from|on|uses?|measured|reported|with)\b', re.I)
_NEGATIVE = re.compile(r'并非|不是|而非|不代表|不属于|不能|无法|不足以|尚不能|未建立|是否|\b(?:not|cannot|insufficient|whether)\b', re.I)
_NONPRIMARY = re.compile(r'profil\w*|overhead|ablation|sensitivity|parameter sweep|'
    r'(?:FPS|frames per second) with respect to|with varying|varying (?:the )?(?:number|count)|'
    r'渲染剖析|渲染分解|消融|敏感性|参数扫描', re.I)
_PRIMARY = re.compile(r'\bmain results?\b|quantitative comparison|benchmark comparison|'
    r'comparison with (?:the )?state.of.the.art|主表|主要结果|定量比较', re.I)


def targets(claim):
    if claim.get('kind') not in {'reported', 'inference'}:
        return []
    fields = [(['text'], claim.get('text', ''))]
    if isinstance(claim.get('conditions'), dict):
        fields.extend((['conditions', key], value) for key, value in claim['conditions'].items()
                      if isinstance(value, str))
    result = []
    for path, text in fields:
        # Separate a known measurement premise from a later no-ranking verdict.
        for part in re.split(r'[，,。；;!?！？\n]', text):
            part = part.strip()
            if (_MAIN.search(part) and _METRIC.search(part) and _PREDICATE.search(part)
                    and not _NEGATIVE.search(part)):
                result.append({'statementPath': path, 'statementExcerpt': part})
    return result


def audit_prompt(required):
    import json
    return '\nMain-result attribution targets (each exact clause must be audited):\n' + json.dumps(
        required, ensure_ascii=False, separators=(',', ':')) + '''
A passed verdict for these claims also requires resultPurposeAudit: one row per target:
{"statementPath":["text"],"statementExcerpt":"exact listed clause",
 "resultRole":"primary_comparison","supported":true,
 "measurementPremise":{"evidenceId":"own E ID","path":["quote"]},
 "purposePremise":{"evidenceId":"own E ID","quote":"exact caption/purpose excerpt"}}.
Use the listed condition path when applicable. Both premises must belong to the SAME
paper AND version, and the SAME experiment/table. Check the actual paper named in
the target, its measured quantity/conditions, and the original experiment's purpose.
The purpose excerpt must explicitly identify a main result or quantitative/benchmark
comparison; a generic GPU/FPS sentence, metadata label, ablation, point-count sweep or
profiling is insufficient. A different table's caption in surrounding context cannot
license this measurement. Use exact own quote/context fields or exact original excerpts.
Fail if the role/connection is unestablished. Other papers' valid captions, the question,
and a correct final no-ranking conclusion do not license a wrong measurement premise.
Do not rewrite an unsupported target and pass the weaker version.
'''


def _bind(binding, own):
    if isinstance(binding, dict) and 'path' in binding:
        from services.deep_research.audit_source_fields import resolve
        return resolve(binding, own)
    if not isinstance(binding, dict) or set(binding) != {'evidenceId', 'quote'}:
        return None
    row = own.get(binding.get('evidenceId'))
    quote = binding.get('quote')
    if not row or not isinstance(quote, str) or not quote.strip():
        return None
    context = row.get('sourceContext', '')
    contexts = list(context.values()) if isinstance(context, dict) else [context]
    normalize = lambda text: re.sub(r'\s+', ' ', text).strip()
    if any(isinstance(text, str) and normalize(quote) in normalize(text)
           for text in [row.get('quote', ''), *contexts]):
        return row, quote
    return None


def validate_audit(claim, verdict, evidence):
    required = targets(claim)
    if not required:
        return []
    rows = verdict.get('resultPurposeAudit')
    if not isinstance(rows, list) or len(rows) != len(required):
        return ['result_purpose_audit_missing']
    own = {e['evidenceId']: e for e in evidence if e['evidenceId'] in claim.get('evidenceRefs', [])}
    remaining = list(required)
    for row in rows:
        if not isinstance(row, dict):
            return ['result_purpose_audit_invalid']
        target = {key: row.get(key) for key in ('statementPath', 'statementExcerpt')}
        if target not in remaining or row.get('supported') is not True or row.get('resultRole') != 'primary_comparison':
            return ['result_purpose_target_not_bound']
        remaining.remove(target)
        measured, purpose = _bind(row.get('measurementPremise'), own), _bind(row.get('purposePremise'), own)
        if not measured or not purpose:
            return ['result_purpose_premises_not_bound']
        identities = [(item[0].get('sourceWorkId') or item[0].get('workId'),
                       item[0].get('sourceVersionId') or item[0].get('versionId')) for item in (measured, purpose)]
        if not all(identities[0]) or identities[0] != identities[1]:
            return ['result_purpose_source_mismatch']
        def table_ids(bound):
            text=bound[1]+' '+str(bound[0].get('location',{}).get('section',''))
            return set(re.findall(r'(?:\bTable\s*|表\s*)(\d+)\b', text, re.I))
        measured_tables, purpose_tables=table_ids(measured),table_ids(purpose)
        if measured_tables and purpose_tables and not measured_tables & purpose_tables:
            return ['result_purpose_table_mismatch']
        if not _PRIMARY.search(purpose[1]) or _NONPRIMARY.search(purpose[1]) or _NONPRIMARY.search(measured[1]):
            return ['result_purpose_not_established']
    return []
