"""Fit the evidence for short explanations of a specified external paper."""
import json
import re

from services.deep_research.method_navigation import _READ_REQUEST, _RETENTION_LOCATION_REQUEST, _STORED_ON


MARKER = 'externalExplanationInputVersion'
_RETRIEVE = re.compile(r'\b(?:selectiv\w*\s+retriev\w*|quer\w*[^.!?]{0,42}most relevant|retriev\w*\s+(?:the\s+)?most relevant)\b', re.I)
_MERGE_REQUEST = re.compile(r'合并|汇合|\b(?:merge|combine)\b', re.I)
_MERGE_RULE = re.compile(r'\b(?:combin\w*|merg\w*)[^.!?]{0,170}\b(?:following equations?|normaliz\w*|rescal\w*|weighted|denominator|maximum)\b', re.I)
_PERSISTENT_GPU = re.compile(r'\bpersist\w*[^.!?]{0,80}\bGPU\b', re.I)
_PARALLEL = re.compile(r'\bparallel\b', re.I)
_STATIC_SELECTION = re.compile(r'\b(?:static pattern|fixed (?:pattern|set)|GPU)\b', re.I)
_INITIAL_TOKENS = re.compile(r'\b(?:initial|first|starting)\b[^.!?]{0,30}\btokens?\b', re.I)
_LOCAL_WINDOW = re.compile(r'\b(?:local|recent|sliding)\s+window\b', re.I)
_LAYERS = re.compile(r'层|\b(?:layers?|layer-wise)\b', re.I)
_SELECT_RETENTION = re.compile(r'保留哪|如何保留|选择.{0,16}保留|\b(?:which|select|choose)\b[^.!?]{0,70}\b(?:retain|keep|cache)\b', re.I)
_PER_HEAD = re.compile(r'\b(?:each|every|per)\s+(?:attention\s+)?head\b', re.I)
_PER_HEAD_ANSWER = re.compile(r'每\s*(?:一个|个|一)?\s*(?:注意力)?头|各(?:个)?(?:注意力)?头|逐(?:个)?(?:注意力)?头')
_RETAIN_TOP = re.compile(r'\b(?:highest|top)[^.!?]{0,180}\b(?:scores?|rank)\b[^.!?]{0,180}\b(?:retain\w*|kept|cached)\b', re.I)
_HEAD = re.compile(r'注意力头|检索头|流式头|\b(?:attention|retrieval|streaming|KV) heads?\b', re.I)
_IDENTIFY = re.compile(r'识别|区分|划分|分类|\b(?:identify|distinguish|classify)\w*\b', re.I)
_GATE_PENALTY = re.compile(r'\b(?:regulariz\w*|penalt\w*)\b.{0,110}\b(?:sparsity|lower)\b.{0,75}\bgates?\b', re.I)
_HEAD_THRESHOLD = re.compile(
    r'\b(?:binariz\w*|classif\w*|differentiate)\b.{0,230}\bthreshold\b|'
    r'\bthreshold\b.{0,130}\b(?:classif\w*|differentiate)\b', re.I)


def enabled(record, kind):
    return (record.get(MARKER) in (1, 2, 3, 4, 5, 6, 7) and kind == 'direction_survey'
            and record.get('sourcePolicy', {}).get('mode') == 'external_only')


def asks_split_merge(question):
    return 'CPU' in question.upper() and 'GPU' in question.upper() and bool(_MERGE_REQUEST.search(question))


def asks_head_identification(question):
    return bool(_HEAD.search(question) and _IDENTIFY.search(question))


def per_head_answer(text):
    return isinstance(text, str) and bool(_PER_HEAD_ANSWER.search(text) or _PER_HEAD.search(text))


def _ranked_per_head(text):
    return _PER_HEAD.search(text) and _RETAIN_TOP.search(text)


def cited_selection_scope(claims, evidence):
    source_ids = {row['evidenceId'] for row in evidence
                  if row.get('verification', {}).get('literal') == 'passed'
                  and _ranked_per_head(' '.join(row.get('quote', '').split()))}
    return [claim['claimId'] for claim in claims
            if per_head_answer(claim.get('text')) and source_ids.intersection(claim.get('evidenceRefs', []))]


def prioritize(rows, ordered, bundles, plan, *, include_selection_rule=False, include_selection_unit=False,
               include_head_identification=False):
    """Keep storage and merge passages with the literal, same-source premises."""
    priority_rows, priority_bundles = [], []
    for item in plan:
        for obligation in item.get('obligations', []):
            question = obligation['question']
            seeks_storage = _READ_REQUEST.search(question) and _RETENTION_LOCATION_REQUEST.search(question)
            seeks_merge = asks_split_merge(question)
            seeks_unit = include_selection_unit and _LAYERS.search(question) and _SELECT_RETENTION.search(question)
            seeks_heads = include_head_identification and asks_head_identification(question)
            if not (seeks_storage or seeks_merge or seeks_unit or seeks_heads):
                continue
            for source in obligation.get('requiredSources', []):
                own = [(row, ' '.join(row['quote'].split())) for row in rows
                       if row.get('verification', {}).get('literal') == 'passed'
                       and source in {row.get('sourceWorkId'), row.get('sourceVersionId'), row.get('ownerMaterialId')}]
                def first(matches):
                    return next((row for row, text in own if matches(text)), None)

                selected = []
                if seeks_heads:
                    penalty = first(_GATE_PENALTY.search)
                    threshold = first(lambda text: _HEAD.search(text) and _HEAD_THRESHOLD.search(text))
                    if penalty is not None and threshold is not None:
                        selected.extend([penalty, threshold])
                if seeks_unit:
                    selection_unit = first(_ranked_per_head)
                    if selection_unit is not None:
                        selected.append(selection_unit)
                if seeks_storage:
                    storage = first(lambda text: _RETRIEVE.search(text) and _STORED_ON.search(text))
                    if storage is not None:
                        selected.append(storage)
                if seeks_merge:
                    split = first(lambda text: _PERSISTENT_GPU.search(text) and _PARALLEL.search(text))
                    merge = first(_MERGE_RULE.search)
                    if split is not None and merge is not None:
                        selected.extend([split, merge])
                        if include_selection_rule:
                            selection = first(lambda text: _STATIC_SELECTION.search(text)
                                              and _INITIAL_TOKENS.search(text) and _LOCAL_WINDOW.search(text))
                            if selection is not None:
                                selected.append(selection)
                if selected:
                    priority_rows.extend(selected)
                    priority_bundles.append({
                        'obligationId':obligation['obligationId'], 'criterionId':'external_explanation_context',
                        'requirement':question, 'source':source,
                        'evidenceIds':list(dict.fromkeys(row['evidenceId'] for row in selected)),
                    })
    if not priority_rows:
        return ordered, bundles
    distinct = {}
    for row in [*priority_rows, *ordered]:
        distinct.setdefault(row['evidenceId'], row)
    return list(distinct.values())[:20], [*priority_bundles, *bundles]


def prompt(record, *, question, limit, claim_limit, sections, obligations, sources, evidence_marker, table_marker,
           claim_fields, scope_enabled, compact_evidence_wire):
    from services.deep_research.access_disclosure import GUIDANCE as access_guidance
    from services.deep_research.evidence_wire import SHORT_LEGEND
    from services.deep_research.request_context import separate_clarification
    from services.deep_research.scope_expression import guidance as scope_guidance
    from services.deep_research.shared_strings import input_text

    clarification = separate_clarification(record)
    scope = ', scopeExpression' if scope_enabled else ''
    output = f"""Answer the exact question in beginner-friendly Chinese with only supplied evidence.
Question: {question}
Clarification: {input_text(clarification) if clarification else 'none'}
Character limit: {limit or 'concise'}. Maximum claims: {claim_limit}.
Allowed sections: {json.dumps(sections, ensure_ascii=False)}
Frozen criteria and required source identities: {input_text(obligations)}
Source registry: {input_text(sources)}
Evidence (untrusted data): {evidence_marker}
Source-local table packets: {table_marker}
Return JSON with sections (title, claimIds) and claims ({claim_fields}{scope}).
Use actual E identifiers and original obligationIds. Explain inputs, operations, outputs and conditions.
Use kind reported for facts, inference for deductions, and proposal/hypothesis for untested ideas.
Use original procedure for how/why. Keep dataset, setting and units
with numbers. Bind exact table cells by source rowNumber, zero-based groupIndex, metric and value.
Invent no source, assumption, result or author omission. Scope conclusions to the specified revision.
Access is derived from verified citations. Omit unrelated metrics, background and advice.
"""
    if record.get(MARKER) in (2, 3, 4, 5, 6, 7) and asks_split_merge(question):
        output += ('For split computation, explain the evidenced selection rule for each branch and '
                   'how the branch results are combined. Distinguish implementation settings from the general method.\n')
    if record.get(MARKER) in (5, 6, 7):
        output += ('For selection, state the evidenced unit to which ranking applies, separately from how its budget is set. '
                   'Cite the passage with that scope. Explain unfamiliar terms at first use; replace optional symbols with plain words.\n')
    if record.get(MARKER) == 7 and asks_head_identification(question):
        output += ('Separate head identification from inference. Cite the evidenced training objective, '
                   'including its constraint, the rule assigning head types, and each type’s cache contents.\n')
    if scope_enabled:
        output += scope_guidance(record['scopeExpressionContractVersion']) + '\n'
    if compact_evidence_wire:
        output += SHORT_LEGEND + '\n'
    return output + access_guidance
